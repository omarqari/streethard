#!/usr/bin/env python3
"""
StreetHard — Apify Pull Script (Incremental / Puzzle Model)

Accumulates listing data into a canonical store (data/db.json). Each run
fills in what's missing rather than re-fetching everything:

  Pass 1 — Search URL → discover active listing IDs, merge basic data into db
  Pass 2 — Only fetch detail pages for listings that don't have full data yet
            (capped at PASS2_PER_RUN_CAP per run to stay within actor reliability)

After 5-10 runs, most listings reach pass2 quality (fees, taxes, agent, history).
Subsequent runs only scrape new listings and price changes.

Usage:
  python scripts/pull.py [--mode both|sale|rent] [--max-items N] [--dry-run]

Environment:
  APIFY_TOKEN  — required. Set in .env locally or as GitHub Secret in CI.

Output:
  data/db.json              — canonical store (never overwritten destructively)
  data/latest.json          — generated from db.json for the app
  data/YYYY-MM-DD.json      — immutable dated archive
"""

import os
import re
import sys
import json
import time
import argparse
import datetime
import requests
from pathlib import Path
from dotenv import load_dotenv

# ─── Exceptions ────────────────────────────────────────────────────
class ApifyRunError(Exception):
    """Raised when an Apify run fails, aborts, or times out.
    Catchable at the batch level so a single failed batch doesn't
    discard results from batches that already succeeded."""
    pass

# ─── Config ────────────────────────────────────────────────────────
ACTOR_ID             = "memo23/streeteasy-ppr"
MIN_LISTINGS         = 10
POLL_INTERVAL_SEC    = 5
PASS1_TIMEOUT_SEC    = 600    # 10 min — search pages are fast
PASS2_TIMEOUT_SEC    = 600    # 10 min per batch — abort and salvage if stuck
PASS2_BATCH_SIZE     = 50     # max URLs per Pass 2 Apify run (tested up to 100 in Session 9; 50 balances speed vs. blast radius)
PASS2_PER_RUN_CAP   = 100    # max listings to send through Pass 2 per run; rest queue for next run
DELIST_DAYS          = 14    # DEPRECATED — see PIPELINE-RESILIENCE-PLAN.md (W2). detect_delistings() is no longer called from the pipeline. Staleness is now expressed via last_pass1 (W3 stale pill) and confirmed off-market via Pass 2 sniffing (W7), never by absence-timer alone.
W7_STALE_DAYS        = 7     # W7: shortlisted listings unseen in Pass 1 this many days are run through Pass 2 to definitively check for off-market state
W7_PER_RUN_CAP       = 20    # W7: max stale shortlists to verify per cron run; caps actor cost
PARTIAL_RETRY_DAYS   = 7     # if a listing came back partial (PX_api_v6 block), wait this many days before retrying — avoids hammering the actor while memo23 is fixing the block. See SQFT-METHODOLOGY.md / CHANGELOG Session 12.

# Bedrooms (universally published) instead of sqft (null for co-ops).
# This URL filter is robust against the kind of behavior change StreetEasy
# made around 2026-04-22 — when they started excluding null-sqft listings
# from sqft-filtered searches, dropping ~240 co-ops from Pass 1 results.
# See PIPELINE-RESILIENCE-PLAN.md (W1) for full rationale.
SALE_URL = (
    "https://streeteasy.com/for-sale/upper-east-side"
    "/price:2000000-5000000%7Cbeds:3-"
)
RENTAL_URL = (
    "https://streeteasy.com/for-rent/upper-east-side"
    "/price:10000-20000%7Cbeds:3-"
)
DEFAULT_MAX_ITEMS = 500

# ─── Argument Parsing ──────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="Pull StreetEasy listings via Apify")
    p.add_argument("--mode",        default="both",       choices=["both", "sale", "rent"],
                   help="Which listing types to pull (default: both)")
    p.add_argument("--sale-url",    default=SALE_URL,     help="StreetEasy for-sale search URL")
    p.add_argument("--rental-url",  default=RENTAL_URL,   help="StreetEasy for-rent search URL")
    p.add_argument("--max-items",   default=DEFAULT_MAX_ITEMS, type=int,
                   help="Max listings per type")
    p.add_argument("--dry-run",     action="store_true",  help="Fetch data but don't write files")
    p.add_argument("--pass1-only",  action="store_true",
                   help="Skip Pass 2 (detail pages). Normalize Pass 1 search data only. "
                        "Use when the actor's individual listing scraping is broken.")
    p.add_argument("--force-pass2", action="store_true",
                   help="Queue all listings for Pass 2 (not just pass1-quality ones). "
                        "Still capped at PASS2_PER_RUN_CAP. Use to refresh stale pass2 data.")
    p.add_argument("--force-merge", action="store_true",
                   help="W5: bypass the Pass 1 coverage cliff guard. Use only after "
                        "investigating a legitimate <50% drop (StreetEasy down, real "
                        "market shift, etc.). Without this flag, runs that look like "
                        "the 2026-04-22 cliff incident abort before merging.")
    return p.parse_args()

# ─── Apify Client ──────────────────────────────────────────────────
class ApifyClient:
    BASE = "https://api.apify.com/v2"

    def __init__(self, token):
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def start_run(self, actor_id, input_data):
        actor_path = actor_id.replace("/", "~")
        resp = self.session.post(
            f"{self.BASE}/acts/{actor_path}/runs",
            json=input_data,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["data"]

    def get_run(self, run_id):
        # Retry transient 5xx from api.apify.com — observed in run #23
        # (2026-05-02): Pass 1 succeeded, Pass 2 batch was running on Apify,
        # but get_run polling hit a 502 Bad Gateway, the uncaught HTTPError
        # bubbled up and killed the whole pipeline before any commit.
        # Five attempts with exponential backoff (1s, 2s, 4s, 8s) covers the
        # typical Apify infrastructure blip without delaying healthy polls.
        last_err = None
        for attempt in range(5):
            try:
                resp = self.session.get(
                    f"{self.BASE}/actor-runs/{run_id}", timeout=30)
                if 500 <= resp.status_code < 600:
                    last_err = requests.HTTPError(
                        f"{resp.status_code} {resp.reason} for {resp.url}",
                        response=resp)
                    if attempt < 4:
                        sleep_s = 1 << attempt   # 1, 2, 4, 8
                        print(f"\n  WARN: get_run({run_id}) returned "
                              f"{resp.status_code}; retrying in {sleep_s}s "
                              f"(attempt {attempt+1}/5)…", file=sys.stderr)
                        time.sleep(sleep_s)
                        continue
                resp.raise_for_status()
                return resp.json()["data"]
            except requests.RequestException as e:
                # Network timeouts, connection errors — also worth retrying
                last_err = e
                if attempt < 4:
                    sleep_s = 1 << attempt
                    print(f"\n  WARN: get_run({run_id}) network error: {e}; "
                          f"retrying in {sleep_s}s (attempt {attempt+1}/5)…",
                          file=sys.stderr)
                    time.sleep(sleep_s)
                    continue
                raise
        # Out of retries — re-raise the last error so the caller (which now
        # catches both ApifyRunError and HTTPError) can decide what to do.
        raise last_err

    def abort_run(self, run_id):
        """Abort a running actor run. Returns the run status dict."""
        try:
            resp = self.session.post(
                f"{self.BASE}/actor-runs/{run_id}/abort", timeout=30)
            resp.raise_for_status()
            return resp.json()["data"]
        except Exception as e:
            print(f"\n  WARN: Failed to abort run {run_id}: {e}", file=sys.stderr)
            return None

    def get_dataset_items(self, dataset_id):
        items = []
        offset = 0
        limit  = 1000
        while True:
            resp = self.session.get(
                f"{self.BASE}/datasets/{dataset_id}/items",
                params={"offset": offset, "limit": limit, "clean": "true"},
                timeout=60,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            items.extend(batch)
            if len(batch) < limit:
                break
            offset += limit
        return items

    def run_and_wait(self, start_urls, max_items, label="",
                     timeout_sec=PASS1_TIMEOUT_SEC, paginate=True):
        """Submit an Apify run and poll until complete.

        paginate: pass True for Pass 1 search URLs (actor needs to page through
        results), False for Pass 2 individual listing URLs (pagination is
        meaningless and causes unnecessary extra requests).

        Raises ApifyRunError on timeout or non-SUCCEEDED status so the caller
        can decide whether to abort or continue with remaining batches.
        """
        print(f"\n{'─'*50}")
        print(f"  {label}")
        print(f"  URLs:      {len(start_urls)}")
        print(f"  Max items: {max_items}")

        run_input = {
            "startUrls":         [{"url": u} for u in start_urls],
            "maxItems":          max_items,
            # moreResults: only for Pass 1 search pages. Pass 2 individual
            # listing URLs have nothing to paginate — setting this True there
            # causes the actor to make unnecessary extra requests.
            "moreResults":       paginate,
            # flattenDatasetItems: true is required so that the deeply-nested
            # GraphQL response fields are stored as top-level keys with long
            # prefixed names (e.g. saleListingDetailsFederated_data_...).
            # Without this, normalize() cannot find price, sqft, fees, etc.
            "flattenDatasetItems": True,
            # Residential proxies are required — without them StreetEasy's
            # bot detection blocks search page scraping and the actor only
            # returns internal queue/status objects (message, timestamp, urls_json)
            # instead of actual listing data.
            "proxy": {
                "useApifyProxy":      True,
                "apifyProxyGroups":   ["RESIDENTIAL"],
            },
        }
        try:
            run = self.start_run(ACTOR_ID, run_input)
        except requests.HTTPError as e:
            raise ApifyRunError(f"Failed to start Apify run: {e}")

        run_id     = run["id"]
        dataset_id = run["defaultDatasetId"]
        print(f"  Run ID:    {run_id}")
        print(f"  Dataset:   {dataset_id}")

        print("  Waiting for completion…", end="", flush=True)
        timed_out = False
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            run_status = self.get_run(run_id)
            status = run_status.get("status", "")
            print(f" {status}", end="", flush=True)
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break
            time.sleep(POLL_INTERVAL_SEC)
        else:
            timed_out = True
            print(f"\n  TIMEOUT after {timeout_sec}s — aborting run and salvaging partial results…",
                  flush=True)
            self.abort_run(run_id)
            # Give Apify a moment to finalize the dataset after abort
            time.sleep(5)

        print()

        if not timed_out and status not in ("SUCCEEDED",):
            raise ApifyRunError(f"Run {run_id} ended with status {status}")

        items = self.get_dataset_items(dataset_id)
        print(f"  Items received: {len(items)}"
              + (f"  (PARTIAL — run was aborted after timeout)" if timed_out else ""))
        return items

# ─── Field Resolution Helpers ─────────────────────────────────────
def _get(*candidates):
    """Return the first non-None candidate value.

    Use this instead of `or`-chaining for fields where 0 is a valid value
    (beds=0 for studios, days_on_market=0 for just-listed, fees=0 for
    tax-abated units). Plain `or` would skip a legitimate 0 and fall through
    to the next candidate silently.
    """
    for v in candidates:
        if v is not None:
            return v
    return None

# ─── Field Normalization — Sales ───────────────────────────────────
# memo23/streeteasy-ppr flattens StreetEasy's federated GraphQL into
# top-level keys with these namespace prefixes (Pass 2 / individual pages).
# Pass 1 (search results) uses short field names — kept as fallbacks.
_P1 = "saleListingDetailsFederated_data_saleByListingId_"
_P2 = "saleDetailsToCombineWithFederated_data_sale_"
_P3 = "saleListingDetailsFederated_data_buildingBySaleListingId_"
_P4 = "extraListingDetails_data_sale_"
# _PP = bare "sale_" prefix used by memo23's partial fallback endpoint
# (when the federated endpoint is PX_api_v6-blocked). Verified 2026-05-02
# from run TImFFxgbWPt8M7MQZ. Has 66 sale_* fields including building info,
# price_histories_json, contacts_json, area_name, days_on_market, listed_at.
# Lacks the financial fields (taxes/maint/fees) — those live in the blocked
# endpoint.
_PP = "sale_"
# _SC = "saleCombineResponse_sale_" prefix used by memo23's 2026-05-02 build
# when individual listing URLs (/sale/{id}) are fetched. This build pulls
# financials from a non-PX-blocked source. Has pricing_*, propertyDetails_*,
# and deeply nested saleCombineResponse_sale_* fields. Top-level convenience
# fields (maintenance, monthly_taxes, monthly_fees) are also present.
_SC = "saleCombineResponse_sale_"

def normalize(raw):
    """Normalize a sale listing. Returns None if price is missing."""
    price = (
        raw.get(f"{_P1}pricing_price")
        or raw.get("pricing_price")
        or raw.get(f"{_SC}pricing_price")  # 2026-05-02 build
        or raw.get("price")
        or raw.get("askingPrice")
        or raw.get("asking_price")
    )
    # Partial-response fallback (memo23 actor when SaleListingDetailsFederated
    # is PX-blocked): the asking price isn't returned at the top level, but
    # the most recent LISTED event in sale_price_histories_json has it.
    if not price:
        ph_raw = (raw.get(f"{_P4}price_histories_json")
                  or raw.get(f"{_P2}price_histories_json")
                  or raw.get(f"{_PP}price_histories_json")
                  or raw.get(f"{_SC}price_histories_json"))
        if ph_raw:
            try:
                ph_list = json.loads(ph_raw) if isinstance(ph_raw, str) else ph_raw
                for h in (ph_list or []):
                    if (h.get("event") or "").upper() == "LISTED" and h.get("price"):
                        price = h["price"]
                        break
            except (json.JSONDecodeError, AttributeError):
                pass
    if not price:
        return None

    listing_id = str(
        raw.get("listingId") or raw.get(f"{_P1}id") or raw.get("id")
        or raw.get(f"{_PP}id") or raw.get(f"{_SC}id")  # 2026-05-02 build
        or ""
    )
    url = (
        raw.get("originalUrl") or raw.get("url")
        or (f"https://streeteasy.com/sale/{listing_id}" if listing_id else "")
    )

    beds = _get(
        raw.get(f"{_P1}propertyDetails_bedroomCount"),
        raw.get("propertyDetails_bedroomCount"),  # 2026-05-02 build
        raw.get("bedroomCount"), raw.get("bedrooms"), raw.get("beds"),
    )
    full = _get(raw.get(f"{_P1}propertyDetails_fullBathroomCount"),
                raw.get("propertyDetails_fullBathroomCount"),  # 2026-05-02 build
                raw.get("fullBathroomCount"), raw.get("bathrooms")) or 0
    half = _get(raw.get(f"{_P1}propertyDetails_halfBathroomCount"),
                raw.get("propertyDetails_halfBathroomCount"),  # 2026-05-02 build
                raw.get("halfBathroomCount")) or 0
    baths = (full or 0) + (half or 0) * 0.5

    btype = (
        raw.get(f"{_P2}building_building_type")
        or raw.get(f"{_P3}type")
        or raw.get("building_building_type")
        or raw.get(f"{_PP}building_building_type")
        or raw.get(f"{_SC}building_building_type")  # 2026-05-02 build
        or raw.get("propertyType") or raw.get("buildingType") or ""
    ).lower()
    ptype = "coop" if any(s in btype for s in ("co-op", "coop", "co_op")) else "condo"

    street = (
        raw.get(f"{_P1}propertyDetails_address_street")
        or raw.get("propertyDetails_address_street")  # 2026-05-02 build
        or raw.get(f"{_P3}address_street")
        or raw.get("address_street") or raw.get("addressStreet")
        or raw.get(f"{_PP}building_subtitle")  # partial response: "200 East 66th Street"
        or raw.get(f"{_SC}building_subtitle")  # 2026-05-02 build
        or raw.get("street") or ""   # Pass 1 search results use "street" directly
    )
    if not street:
        addr_raw = raw.get("address") or {}
        if isinstance(addr_raw, dict):
            street = addr_raw.get("street") or addr_raw.get("streetAddress") or ""
        elif isinstance(addr_raw, str):
            street = addr_raw

    unit = (
        raw.get(f"{_P1}propertyDetails_address_unit")
        or raw.get("propertyDetails_address_displayUnit")  # 2026-05-02 build
        or raw.get("address_unit") or raw.get("addressUnit") or raw.get("unit") or ""
    )

    _bldg_obj = raw.get("building")
    building = (
        raw.get(f"{_P2}building_title") or raw.get(f"{_P3}name")
        or raw.get("building_title") or raw.get("buildingTitle") or raw.get("buildingName")
        or raw.get(f"{_PP}building_title")
        or raw.get(f"{_SC}building_title")  # 2026-05-02 build
        or ((_bldg_obj or {}).get("name") if isinstance(_bldg_obj, dict) else None)
        or street or ""
    )

    neighborhood = (
        raw.get(f"{_P2}area_name") or raw.get(f"{_P3}area_name")
        or raw.get("area_name") or raw.get("neighborhood") or raw.get("neighborhoodName")
        or raw.get(f"{_PP}area_name")
        or raw.get(f"{_SC}area_name")  # 2026-05-02 build
        or raw.get("areaName") or ""   # Pass 1 search results use "areaName"
    )

    sqft = (
        raw.get(f"{_P1}propertyDetails_livingAreaSize")
        or raw.get("propertyDetails_livingAreaSize")  # 2026-05-02 build
        or raw.get("livingAreaSize") or raw.get("sqft") or raw.get("squareFeet")
    )
    ppsqft = (raw.get(f"{_P2}price_per_sqft") or raw.get("price_per_sqft")
              or raw.get(f"{_PP}price_per_sqft")
              or raw.get(f"{_SC}price_per_sqft")  # 2026-05-02 build
              or raw.get("ppsqft"))
    if not ppsqft and sqft and price:
        ppsqft = round(int(price) / sqft)

    year_built = (
        raw.get(f"{_P2}building_year_built") or raw.get(f"{_P3}yearBuilt")
        or raw.get("building_year_built") or raw.get("yearBuilt") or raw.get("builtIn")
        or raw.get(f"{_PP}building_year_built")
        or raw.get(f"{_SC}building_year_built")  # 2026-05-02 build
    )
    days_on_market = _get(
        raw.get(f"{_P2}days_on_market"),
        raw.get("days_on_market"), raw.get("daysOnMarket"),
        raw.get(f"{_PP}days_on_market"),
        raw.get(f"{_SC}days_on_market"),  # 2026-05-02 build
    )

    # Use _get (not or) for fees/taxes — $0 is valid (tax abatements, some condos)
    #
    # 2026-05-02 build adds top-level convenience fields (maintenance,
    # monthly_taxes, monthly_fees) AND nested pricing_monthly* fields.
    # These are checked first because they're the most reliable source
    # when the new build is active.
    maint_fee = _get(
        raw.get(f"{_P1}pricing_maintenanceFee"),
        raw.get("pricing_monthlyCommonCharges"),  # 2026-05-02 build (condo common charges)
        raw.get("pricing_monthly_fees"), raw.get("monthlyHoa"), raw.get("commonCharges"),
    )
    taxes_fee = _get(
        raw.get(f"{_P1}pricing_taxes"),
        raw.get("pricing_monthlyTaxes"),  # 2026-05-02 build
        raw.get("monthly_taxes"),  # 2026-05-02 build top-level
        raw.get("pricing_monthly_taxes"), raw.get("monthlyTax"), raw.get("realEstateTaxes"),
    )
    old_maint = _get(
        raw.get("pricing_monthlyMaintenance"),  # 2026-05-02 build
        raw.get("maintenance"),  # 2026-05-02 build top-level
        raw.get("pricing_monthly_maintenance"),
        raw.get("monthlyMaintenance"),
    )

    if ptype == "coop":
        maint  = old_maint or maint_fee
        fees   = None
        taxes  = None
    else:
        fees   = maint_fee
        taxes  = taxes_fee if taxes_fee else None
        maint  = None

    agent_name = agent_phone = agent_email = agent_firm = None
    contacts_raw = (raw.get(f"{_P2}contacts_json")
                    or raw.get(f"{_PP}contacts_json")
                    or raw.get(f"{_SC}contacts_json"))  # 2026-05-02 build
    if contacts_raw:
        try:
            contacts = json.loads(contacts_raw) if isinstance(contacts_raw, str) else contacts_raw
            if contacts:
                c = contacts[0]
                agent_name  = c.get("name")
                agent_phone = c.get("primary_phone")
                agent_email = c.get("email")
                agent_firm  = (c.get("source_group") or {}).get("label")
        except (json.JSONDecodeError, AttributeError, IndexError):
            pass
    else:
        agent_name  = raw.get("agent_name")  or raw.get("agentName")
        agent_phone = raw.get("agent_phone") or raw.get("agentPhone")
        agent_email = raw.get("agent_email") or raw.get("agentEmail")
        # sourceGroupLabel = brokerage from Pass 1 search results (e.g. "Compass", "Douglas Elliman")
        agent_firm  = (raw.get("agent_firm")  or raw.get("agentFirm") or raw.get("brokerageName")
                       or raw.get("sourceGroupLabel"))

    history = []
    ph_raw = (raw.get(f"{_P4}price_histories_json")
              or raw.get(f"{_P2}price_histories_json")
              or raw.get(f"{_PP}price_histories_json")
              or raw.get(f"{_SC}price_histories_json")  # 2026-05-02 build (flat format)
              # NOTE: propertyHistory_json (also 2026-05-02) has a nested
              # saleEventsOfInterest structure — NOT the flat date/price/event
              # format. Don't add it here; the flat source above is preferred.
              )
    if ph_raw:
        try:
            ph_list = json.loads(ph_raw) if isinstance(ph_raw, str) else ph_raw
            for h in (ph_list or []):
                date   = h.get("date")
                hprice = h.get("price")
                event  = (h.get("event") or "").upper()
                broker = h.get("source_group_label") or h.get("description")
                if date or hprice:
                    history.append({"date": date, "price": int(hprice) if hprice else None,
                                    "event": event, "broker": broker})
        except (json.JSONDecodeError, AttributeError):
            pass
    else:
        for h in (raw.get("priceHistory") or raw.get("price_history") or raw.get("listingHistory") or []):
            date   = h.get("date") or h.get("eventDate")
            hprice = h.get("price") or h.get("askingPrice")
            event  = (h.get("event") or h.get("eventType") or "").upper().replace(" ", "_")
            broker = h.get("broker") or h.get("brokerageName")
            if date or hprice:
                history.append({"date": date, "price": int(hprice) if hprice else None,
                                "event": event, "broker": broker})

    # Extract listed_date: prefer explicit listed_at timestamp (2026-05-02
    # build), fall back to most recent LISTED event in price history. Stored
    # so the JS app can compute days-on-market at render time.
    listed_date = None
    listed_at_raw = (raw.get(f"{_SC}listed_at")  # 2026-05-02 build
                     or raw.get(f"{_PP}listed_at"))
    if listed_at_raw:
        listed_date = listed_at_raw[:10]  # "2026-04-30" from "2026-04-30T12:43:04-04:00"
    else:
        for h in history:
            if h.get("event") == "LISTED" and h.get("date"):
                listed_date = h["date"]
                break   # history is reverse-chronological; first LISTED = most recent

    # Partial-response flags from memo23's actor (added 2026-05-02). When the
    # actor's primary endpoint (SaleListingDetailsFederated) is blocked by
    # PerimeterX, the actor falls back to a partial endpoint that returns
    # price_history, agent contacts, year_built, etc. but lacks the financial
    # fields (monthly_taxes, maintenance, monthly_fees). Pass these through so
    # merge_pass2_into_db can flag the listing as partial-quality and skip
    # immediate retries.
    is_partial    = bool(raw.get("partial"))
    partial_reason = raw.get("partialReason") or raw.get("partial_reason")
    partial_error  = raw.get("partialError") or raw.get("partial_error")

    return {
        "listing_type":   "sale",
        "id":             listing_id,
        "url":            url,
        "building":       building,
        "address":        street,
        "unit":           unit,
        "neighborhood":   neighborhood,
        "price":          int(price),
        "sqft":           sqft,
        "beds":           beds,
        "baths":          baths if baths > 0 else None,
        "price_per_sqft": ppsqft,
        "type":           ptype,
        "year_built":     year_built,
        "days_on_market": days_on_market,
        "listed_date":    listed_date,
        "monthly_fees":   int(fees)  if fees  else None,
        "monthly_taxes":  int(taxes) if taxes else None,
        "maintenance":    int(maint) if maint else None,
        "agent_name":     agent_name,
        "agent_phone":    agent_phone,
        "agent_email":    agent_email,
        "agent_firm":     agent_firm,
        "price_history":  history,
        # Partial-response markers from memo23 actor (None when full)
        "_is_partial":     is_partial,
        "_partial_reason": partial_reason,
        "_partial_error":  partial_error,
    }

# ─── Field Normalization — Rentals ─────────────────────────────────
# Pass 2 rental schema verified 2026-04-21 (run KIaeh9L2v7LkUSyZo, listing 5015416).
# Actual namespace: "combineData_rental_*" — completely different from the
# sale namespace and from what was originally guessed.
#
# 2026-05-10: memo23 shipped a rental bypass fix ("same approach as /sale/").
# The sale bypass uses "saleCombineResponse_sale_*" (_SC). By analogy, the
# rental bypass may use "rentalCombineResponse_rental_*" (_RCnew) or bare
# "rental_*" (_RCP). All three namespaces are checked below so normalize_rental
# works regardless of which one memo23's new build emits.
#
# Key gaps vs. sale Pass 2:
#   - No direct price field — extract from price_histories_json[0].price
#   - No beds/baths/sqft/unit — not in Pass 2 at all; come from Pass 1 search
#   - run_two_pass() merges Pass 1 stub data back in after normalization
#
# Pass 1 rental search items use "node_*" prefix (__typename == OrganicRentalEdge).
_RC    = "combineData_rental_"          # Pass 2 rental namespace (verified Apr 2026)
_RCnew = "rentalCombineResponse_rental_"  # May 2026 bypass (mirrors _SC for sales)
_RCP   = "rental_"                      # bare prefix fallback (mirrors _PP for sales)

def normalize_rental(raw):
    """Normalize a rental listing. Returns None if rent price is missing.
    For rentals, price = monthly rent (not a purchase price).

    Schemas handled (in priority order):
      Pass 2 detail  — combineData_rental_* prefix (verified Apr 2026)
      Pass 2 bypass  — rentalCombineResponse_rental_* (May 2026 fix, mirrors sale _SC)
      Pass 2 bare    — rental_* prefix (mirrors sale _PP fallback)
      Pass 1 search  — node_* prefix (__typename == OrganicRentalEdge)
    """
    # Price is not a top-level field in rental Pass 2 — extract from price history.
    price = _get(
        raw.get("node_price"),        # Pass 1 rental search
        raw.get("price"),
        raw.get("askingRent"), raw.get("asking_rent"),
        raw.get("monthlyRent"), raw.get("monthly_rent"),
        raw.get("rent"),
    )
    if price is None:
        # Pass 2: extract from most recent price history entry
        ph_raw = (raw.get(f"{_RC}price_histories_json")
                  or raw.get(f"{_RCnew}price_histories_json")
                  or raw.get(f"{_RCP}price_histories_json"))
        if ph_raw:
            try:
                ph = json.loads(ph_raw) if isinstance(ph_raw, str) else ph_raw
                if ph and ph[0].get("price") is not None:
                    price = ph[0]["price"]
            except (json.JSONDecodeError, AttributeError, IndexError, KeyError):
                pass
    if not price:
        return None

    listing_id = str(_get(
        raw.get(f"{_RC}id"),
        raw.get(f"{_RCnew}id"),
        raw.get(f"{_RCP}id"),
        raw.get("basicInfo_id"),
        raw.get("node_id"),           # Pass 1 rental search
        raw.get("listingId"),
        raw.get("id"),
    ) or "")

    url = (
        raw.get("originalUrl") or raw.get("url")
        or (f"https://streeteasy.com/rental/{listing_id}" if listing_id else "")
    )

    # beds/baths/sqft/unit are NOT in rental Pass 2 data.
    # These fields will be None here; run_two_pass() merges Pass 1 stub values in.
    beds = _get(
        raw.get("node_bedroomCount"),   # Pass 1 rental search
        raw.get("bedroomCount"), raw.get("bedrooms"), raw.get("beds"),
    )
    full = _get(raw.get("node_fullBathroomCount"),   # Pass 1 rental search
                raw.get("fullBathroomCount"), raw.get("bathrooms")) or 0
    half = _get(raw.get("node_halfBathroomCount"),   # Pass 1 rental search
                raw.get("halfBathroomCount")) or 0
    baths = (full or 0) + (half or 0) * 0.5

    sqft = _get(
        raw.get("node_livingAreaSize"),  # Pass 1 rental search
        raw.get("livingAreaSize"), raw.get("sqft"), raw.get("squareFeet"),
    )

    unit = _get(
        raw.get("node_unit"),            # Pass 1 rental search
        raw.get("address_unit"), raw.get("addressUnit"), raw.get("unit"),
    ) or ""

    btype = (_get(
        raw.get(f"{_RC}building_building_type"),
        raw.get(f"{_RCnew}building_building_type"),
        raw.get(f"{_RCP}building_building_type"),
        raw.get("node_buildingType"),    # Pass 1 rental search
        raw.get("building_building_type"),
        raw.get("propertyType"), raw.get("buildingType"),
    ) or "").lower()
    ptype = "coop" if any(s in btype for s in ("co-op", "coop", "co_op")) else "rental"

    # For Pass 2, building_title is the street address ("549 East 86th Street")
    building = _get(
        raw.get(f"{_RC}building_title"),
        raw.get(f"{_RCnew}building_title"),
        raw.get(f"{_RCP}building_title"),
        raw.get("building_title"), raw.get("buildingTitle"), raw.get("buildingName"),
        raw.get("node_street"),          # Pass 1 rental search
        raw.get("street"),
    ) or ""

    street = _get(
        raw.get("node_street"),          # Pass 1 rental search
        raw.get("address_street"), raw.get("addressStreet"), raw.get("street"),
        raw.get(f"{_RC}building_title"),
        raw.get(f"{_RCnew}building_title"),
        raw.get(f"{_RCP}building_title"),
    ) or ""

    neighborhood = _get(
        raw.get(f"{_RC}area_name"),
        raw.get(f"{_RCnew}area_name"),
        raw.get(f"{_RCP}area_name"),
        raw.get("node_areaName"),        # Pass 1 rental search
        raw.get("area_name"), raw.get("neighborhood"),
        raw.get("neighborhoodName"), raw.get("areaName"),
    ) or ""

    year_built = _get(
        raw.get(f"{_RC}building_year_built"),
        raw.get(f"{_RCnew}building_year_built"),
        raw.get(f"{_RCP}building_year_built"),
        raw.get("building_year_built"), raw.get("yearBuilt"), raw.get("builtIn"),
    )
    days_on_market = _get(
        raw.get(f"{_RC}days_on_market"),
        raw.get(f"{_RCnew}days_on_market"),
        raw.get(f"{_RCP}days_on_market"),
        raw.get("days_on_market"), raw.get("daysOnMarket"),
    )

    agent_name = agent_phone = agent_email = agent_firm = None
    contacts_raw = (raw.get(f"{_RC}contacts_json")
                    or raw.get(f"{_RCnew}contacts_json")
                    or raw.get(f"{_RCP}contacts_json")
                    or raw.get("contacts_json"))
    if contacts_raw:
        try:
            contacts = json.loads(contacts_raw) if isinstance(contacts_raw, str) else contacts_raw
            if contacts:
                c = contacts[0]
                agent_name  = c.get("name")
                agent_phone = c.get("primary_phone")
                agent_email = c.get("email")
                agent_firm  = (c.get("source_group") or {}).get("label")
        except (json.JSONDecodeError, AttributeError, IndexError):
            pass
    else:
        agent_name  = raw.get("agent_name")  or raw.get("agentName")
        agent_phone = raw.get("agent_phone") or raw.get("agentPhone")
        agent_email = raw.get("agent_email") or raw.get("agentEmail")
        agent_firm  = (_get(raw.get("agent_firm"), raw.get("agentFirm"),
                            raw.get("brokerageName"), raw.get("node_sourceGroupLabel"),
                            raw.get("sourceGroupLabel")))

    history = []
    ph_raw = (raw.get(f"{_RC}price_histories_json")
              or raw.get(f"{_RCnew}price_histories_json")
              or raw.get(f"{_RCP}price_histories_json"))
    if ph_raw:
        try:
            ph_list = json.loads(ph_raw) if isinstance(ph_raw, str) else ph_raw
            for h in (ph_list or []):
                date   = h.get("date")
                hprice = h.get("price")
                event  = (h.get("event") or "").upper()
                broker = h.get("source_group_label") or h.get("description")
                if date or hprice:
                    history.append({"date": date, "price": int(hprice) if hprice else None,
                                    "event": event, "broker": broker})
        except (json.JSONDecodeError, AttributeError):
            pass
    else:
        for h in (raw.get("priceHistory") or raw.get("price_history") or raw.get("listingHistory") or []):
            date   = h.get("date") or h.get("eventDate")
            hprice = h.get("price") or h.get("askingPrice") or h.get("askingRent")
            event  = (h.get("event") or h.get("eventType") or "").upper().replace(" ", "_")
            broker = h.get("broker") or h.get("brokerageName")
            if date or hprice:
                history.append({"date": date, "price": int(hprice) if hprice else None,
                                "event": event, "broker": broker})

    # listed_date: prefer the explicit listed_at timestamp (Pass 2), fall back
    # to most recent LISTED event in price history. Stored so JS can compute
    # days-on-market at render time rather than relying on a stale snapshot.
    listed_date = None
    listed_at_raw = (raw.get(f"{_RC}listed_at")
                     or raw.get(f"{_RCnew}listed_at")
                     or raw.get(f"{_RCP}listed_at"))
    if listed_at_raw:
        listed_date = listed_at_raw[:10]   # "2026-04-16" from "2026-04-16T13:33:58-04:00"
    else:
        for h in history:
            if h.get("event") == "LISTED" and h.get("date"):
                listed_date = h["date"]
                break

    # Partial-response flags (see normalize() for context)
    is_partial    = bool(raw.get("partial"))
    partial_reason = raw.get("partialReason") or raw.get("partial_reason")
    partial_error  = raw.get("partialError") or raw.get("partial_error")

    return {
        "listing_type":   "rent",
        "id":             listing_id,
        "url":            url,
        "building":       building,
        "address":        street,
        "unit":           unit,
        "neighborhood":   neighborhood,
        "price":          int(price),   # monthly rent
        "sqft":           sqft,
        "beds":           beds,
        "baths":          baths if baths > 0 else None,
        "price_per_sqft": None,         # not meaningful for rentals
        "type":           ptype,
        "year_built":     year_built,
        "days_on_market": days_on_market,
        "listed_date":    listed_date,
        "monthly_fees":   None,
        "monthly_taxes":  None,
        "maintenance":    None,
        "agent_name":     agent_name,
        "agent_phone":    agent_phone,
        "agent_email":    agent_email,
        "agent_firm":     agent_firm,
        "price_history":  history,
        "_is_partial":     is_partial,
        "_partial_reason": partial_reason,
        "_partial_error":  partial_error,
    }

# ─── Canonical Store (db.json) ─────────────────────────────────────
DB_PATH = Path(__file__).parent.parent / "data" / "db.json"

def load_db():
    """Load the canonical listing database. Returns dict keyed by listing ID."""
    if DB_PATH.exists():
        try:
            with open(DB_PATH) as f:
                data = json.load(f)
            return data.get("listings", {})
        except (json.JSONDecodeError, KeyError):
            pass
    return {}

def save_db(db, total_events=0):
    """Save the canonical listing database."""
    DB_PATH.parent.mkdir(exist_ok=True)
    today = datetime.date.today().isoformat()
    active = {lid: l for lid, l in db.items() if l.get("status") != "delisted"}
    stats = {
        "total":         len(active),
        "pass1_only":    sum(1 for l in active.values() if l.get("data_quality") == "pass1"),
        "partial":       sum(1 for l in active.values() if l.get("data_quality") == "partial"),
        "pass2_complete": sum(1 for l in active.values() if l.get("data_quality") == "pass2"),
        "sale":          sum(1 for l in active.values() if l.get("listing_type") != "rent"),
        "rent":          sum(1 for l in active.values() if l.get("listing_type") == "rent"),
        "delisted":      sum(1 for l in db.values() if l.get("status") == "delisted"),
    }
    payload = {
        "last_updated": today,
        "stats": stats,
        "listings": db,
    }
    with open(DB_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\n  ✓ db.json saved — {stats['total']} active "
          f"({stats['pass2_complete']} pass2, {stats['partial']} partial, "
          f"{stats['pass1_only']} pass1, {stats['delisted']} delisted)")

def generate_latest(db, mode, total_events, sale_url=None, rental_url=None):
    """Generate data/latest.json from the canonical db for the app to consume.

    Includes ALL listings (active + delisted), with their `status` field
    intact, so the app can keep delisted listings visible in Shortlist /
    Archive (where the user has invested triage effort) while still defaulting
    Inbox to active-only. Summary counts in the app filter on `status`.
    """
    data_dir = DB_PATH.parent
    today = datetime.date.today().isoformat()

    # Include every listing matching the mode. Keep `status` field on the
    # output so the frontend can distinguish active vs. delisted.
    keep = []
    for l in db.values():
        if mode == "sale" and l.get("listing_type") == "rent":
            continue
        if mode == "rent" and l.get("listing_type") != "rent":
            continue
        # Strip internal pipeline fields. Keep `status`, `last_pass1`,
        # `last_pass2`, `pass2_confirmed_off_market` so the app can render
        # the W3 stale pill and the W7 verified-off-market badge.
        out = {k: v for k, v in l.items()
               if k not in ("data_quality", "needs_refresh")}
        keep.append(out)

    # Sort: sales by price desc, then rentals by price desc
    sales   = sorted([l for l in keep if l.get("listing_type") != "rent"],
                     key=lambda x: x.get("price", 0), reverse=True)
    rentals = sorted([l for l in keep if l.get("listing_type") == "rent"],
                     key=lambda x: x.get("price", 0), reverse=True)
    all_listings = sales + rentals

    # Counts: headline counts are active-only (matches what user sees in Inbox)
    active_sales   = sum(1 for l in sales   if l.get("status") != "delisted")
    active_rentals = sum(1 for l in rentals if l.get("status") != "delisted")

    payload = {
        "generated_at":  today,
        "listing_count": len(all_listings),
        "sale_count":    active_sales,
        "rental_count":  active_rentals,
        "delisted_count": sum(1 for l in all_listings if l.get("status") == "delisted"),
        "run_cost_usd":  estimate_cost(total_events),
        "mode":          mode,
        "listings":      all_listings,
    }
    if sale_url:
        payload["sale_search_url"] = sale_url
    if rental_url:
        payload["rental_search_url"] = rental_url

    latest_path = data_dir / "latest.json"
    dated_path  = data_dir / f"{today}.json"
    with open(latest_path, "w") as f:
        json.dump(payload, f, indent=2)
    with open(dated_path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"  ✓ latest.json — {len(all_listings)} listings "
          f"({active_sales} active sale, {active_rentals} active rental, "
          f"{payload['delisted_count']} delisted)")
    return all_listings

def merge_pass1_into_db(db, search_items, listing_type, normalize_fn):
    """Merge Pass 1 search results into the canonical db.

    - New listings: added at data_quality='pass1'
    - Existing pass1 listings: all fields updated
    - Existing pass2 listings: only volatile fields updated (price, days_on_market)
      If price changed, sets needs_refresh=True for Pass 2 re-scrape.

    Returns (listing_ids, listing_urls, pass1_stubs) for Pass 2 queue building.
    """
    is_rental = listing_type == "rent"
    today = datetime.date.today().isoformat()
    listing_url_re = re.compile(r'https?://(?:www\.)?streeteasy\.com/(?:sale|rental)/(\d+)')

    ids_seen   = []      # ordered list of IDs discovered this run
    urls_by_id = {}      # {id: pass2_url}
    pass1_stubs = {}     # {id: normalized_pass1_dict} for rental backfill
    new_count = changed_count = updated_count = 0

    for item in search_items:
        lid = str(item.get("node_id") or item.get("id") or item.get("listingId") or "")

        # Build Pass 2 URL
        url_path = (not is_rental) and (item.get("urlPath") or "")
        if url_path:
            url = f"https://streeteasy.com{url_path}"
        elif lid:
            url = f"https://streeteasy.com/{'rental' if is_rental else 'sale'}/{lid}"
        else:
            url = item.get("url") or item.get("originalUrl") or ""

        if not lid and url:
            m = listing_url_re.search(url)
            if m:
                lid = m.group(1)

        # Parse urls_json for batch items
        if not lid:
            urls_json_raw = item.get("urls_json", "")
            if urls_json_raw:
                try:
                    batch = json.loads(urls_json_raw) if isinstance(urls_json_raw, str) else urls_json_raw
                    for entry in (batch if isinstance(batch, list) else []):
                        candidate = entry.get("url", "")
                        m = listing_url_re.search(candidate)
                        if m:
                            lid = m.group(1)
                            url = candidate.replace("www.streeteasy.com", "streeteasy.com")
                            break
                except (json.JSONDecodeError, TypeError, AttributeError):
                    pass

        if not lid or lid in set(ids_seen):
            continue

        url = url.replace("www.streeteasy.com", "streeteasy.com")
        ids_seen.append(lid)
        urls_by_id[lid] = url

        # Normalize the Pass 1 item
        stub = normalize_fn(item)
        if stub:
            stub["id"] = lid  # ensure consistent ID
            pass1_stubs[lid] = stub

        existing = db.get(lid)
        if existing is None:
            # New listing — add at pass1 quality
            if stub:
                entry = dict(stub)
                entry["data_quality"] = "pass1"
                entry["last_pass1"]   = today
                entry["last_pass2"]   = None
                entry["status"]       = "active"
                db[lid] = entry
                new_count += 1
        elif existing.get("data_quality") == "pass2":
            # Already have full data — only update volatile fields
            if stub:
                old_price = existing.get("price")
                existing["price"]          = stub.get("price") or existing.get("price")
                existing["days_on_market"] = stub.get("days_on_market") or existing.get("days_on_market")
                existing["last_pass1"]     = today
                existing["status"]         = "active"
                # Price changed? Queue for Pass 2 refresh
                if stub.get("price") and old_price and stub["price"] != old_price:
                    existing["needs_refresh"] = True
                    changed_count += 1
                else:
                    updated_count += 1
        else:
            # Existing pass1 listing — update everything from fresh Pass 1 data
            if stub:
                for k, v in stub.items():
                    if v is not None:
                        existing[k] = v
                existing["last_pass1"] = today
                existing["status"]     = "active"
                updated_count += 1

    print(f"\n  Pass 1 merge: {new_count} new, {changed_count} price-changed, "
          f"{updated_count} updated, {len(ids_seen)} total discovered")

    return ids_seen, urls_by_id, pass1_stubs

def build_pass2_queue(db, ids_seen, urls_by_id, listing_type):
    """Build the Pass 2 scrape queue from the db.

    Queue includes:
      1. Listings at data_quality='pass1' (never had Pass 2)
      2. Listings at data_quality='partial' whose last_partial_attempt is
         older than PARTIAL_RETRY_DAYS (memo23's PX_api_v6 block may have
         been fixed in the interim)
      3. Listings with needs_refresh=True (price changed)
    Capped at PASS2_PER_RUN_CAP. Prioritizes never-scraped > stale-partial
    > price-changed.
    """
    today = datetime.date.today()
    never_scraped     = []
    stale_partial     = []
    price_changed     = []

    for lid in ids_seen:
        entry = db.get(lid)
        if not entry:
            continue
        url = urls_by_id.get(lid)
        if not url:
            continue
        quality = entry.get("data_quality")
        if quality == "pass1":
            never_scraped.append((lid, url))
        elif quality == "partial":
            # Only retry if PARTIAL_RETRY_DAYS have elapsed since the last
            # partial attempt. Otherwise skip — actor is still blocked.
            last = entry.get("last_partial_attempt")
            if last:
                try:
                    days_since = (today - datetime.date.fromisoformat(last)).days
                    if days_since >= PARTIAL_RETRY_DAYS:
                        stale_partial.append((lid, url))
                except (ValueError, TypeError):
                    stale_partial.append((lid, url))   # malformed date; retry
            else:
                stale_partial.append((lid, url))
        elif entry.get("needs_refresh"):
            price_changed.append((lid, url))

    # Priority: never-scraped > stale partials > price-changed
    queue = never_scraped + stale_partial + price_changed
    capped = queue[:PASS2_PER_RUN_CAP]
    skipped = len(queue) - len(capped)

    # Count partial listings being skipped for visibility in cron logs
    fresh_partial = sum(1 for lid in ids_seen
                       if db.get(lid, {}).get("data_quality") == "partial"
                       and (lid, urls_by_id.get(lid)) not in stale_partial)

    label = "rental" if listing_type == "rent" else "sale"
    print(f"  Pass 2 queue: {len(never_scraped)} never-scraped + "
          f"{len(stale_partial)} stale-partial + {len(price_changed)} price-changed "
          f"= {len(queue)} total")
    if fresh_partial:
        print(f"  Skipping {fresh_partial} partial listings (within {PARTIAL_RETRY_DAYS}-day retry window)")
    if skipped > 0:
        print(f"  Capped at {PASS2_PER_RUN_CAP} this run — {skipped} queued for next run")

    return capped

def merge_pass2_into_db(db, detail_items, listing_type, normalize_fn, pass1_stubs):
    """Merge Pass 2 detail results into the canonical db.

    Upgrades listings from pass1 → pass2 (or → 'partial' if memo23's actor
    returned partial:true with a PerimeterX block reason). Sets the
    appropriate data_quality, last_pass2/last_partial_attempt, and clears
    needs_refresh.
    """
    is_rental = listing_type == "rent"
    today = datetime.date.today().isoformat()
    upgraded = 0
    partial_count = 0
    skipped  = 0

    for item in detail_items:
        result = normalize_fn(item)
        if not result or not result.get("id"):
            skipped += 1
            continue

        lid = result["id"]
        # Pull partial flags out of the result dict; never store the
        # underscore-prefixed keys in db.json
        is_partial    = result.pop("_is_partial", False)
        partial_reason = result.pop("_partial_reason", None)
        partial_error  = result.pop("_partial_error", None)

        # For rentals: backfill beds/baths/sqft/unit from Pass 1 stub
        if is_rental and lid in pass1_stubs:
            stub = pass1_stubs[lid]
            for field in ("beds", "baths", "sqft", "unit", "price_per_sqft"):
                if result.get(field) is None and stub.get(field) is not None:
                    result[field] = stub[field]

        existing = db.get(lid, {})

        # Merge: Pass 2 fields overwrite, but keep any Pass 1 fields that
        # Pass 2 doesn't provide (e.g. rental beds/baths come from Pass 1)
        for k, v in result.items():
            if v is not None:
                existing[k] = v

        if is_partial:
            # Actor's primary endpoint blocked. We have most fields but
            # are missing financial fields (taxes/maint/fees). Keep the
            # listing flagged 'partial' so build_pass2_queue() can throttle
            # retries until memo23 fixes the PerimeterX block.
            existing["data_quality"]         = "partial"
            existing["last_partial_attempt"] = today
            existing["partial_reason"]       = partial_reason
            existing["partial_error"]        = partial_error
            existing["needs_refresh"]        = False
            partial_count += 1
        else:
            existing["data_quality"]  = "pass2"
            existing["last_pass2"]    = today
            existing["needs_refresh"] = False
            # Clear any stale partial markers if a later run succeeds
            for k in ("partial_reason", "partial_error", "last_partial_attempt"):
                existing.pop(k, None)
            upgraded += 1

        existing["status"] = "active"
        db[lid] = existing

    print(f"  Pass 2 merge: {upgraded} upgraded to pass2, "
          f"{partial_count} partial (PX-blocked), {skipped} skipped")
    return upgraded + partial_count

# ─── W4: Pipeline health observability ──────────────────────────────
HEALTH_HISTORY_DAYS = 60   # how many days of records to keep in pipeline_health.json
COVERAGE_WINDOW     = 7    # rolling-median window for cliff guard
COVERAGE_WARN_PCT   = 0.75
COVERAGE_ABORT_PCT  = 0.50

def health_path():
    return DB_PATH.parent / "pipeline_health.json"

def load_health():
    p = health_path()
    if not p.exists():
        return []
    try:
        return json.load(p.open())
    except (json.JSONDecodeError, ValueError):
        # Fail-open: if the file is corrupt, treat as no history
        print(f"  WARNING: {p} is corrupt; treating as no history", file=sys.stderr)
        return []

def save_health(records):
    """Sort newest-first, cap at HEALTH_HISTORY_DAYS, write."""
    records = sorted(records, key=lambda r: r.get('date',''), reverse=True)[:HEALTH_HISTORY_DAYS]
    with health_path().open('w') as f:
        json.dump(records, f, indent=2)

def update_pipeline_health(today, pass1_counts_by_type, db, guard_status='ok'):
    """Append/replace today's record in pipeline_health.json.

    pass1_counts_by_type: {'sale': int, 'rent': int} — counts of unique
        listing IDs returned by Pass 1 for each listing type this run.
        A type missing from the dict means we didn't pull that type today.
    db: the listing dict for active/delisted snapshot.
    guard_status: 'ok' | 'warn' | 'abort' from W5 cliff guard.
    """
    active = sum(1 for l in db.values() if l.get('status') != 'delisted')
    delisted = sum(1 for l in db.values() if l.get('status') == 'delisted')
    record = {
        'date':     today,
        'pass1_sale': pass1_counts_by_type.get('sale'),
        'pass1_rent': pass1_counts_by_type.get('rent'),
        'active':   active,
        'delisted': delisted,
        'status':   guard_status,
    }
    history = load_health()
    history = [r for r in history if r.get('date') != today]  # replace today
    history.append(record)
    save_health(history)
    return record

# ─── W5: Pass 1 coverage cliff guard ─────────────────────────────────
def check_pass1_coverage(listing_type, today_count, force_merge=False):
    """W5 cliff guard. Compares today's Pass 1 count for this listing type
    to the rolling-7-day median of historical pass1_<type> counts.

    Returns (status, message):
      ('ok',    msg) — proceed normally
      ('warn',  msg) — proceed but log warning (50–75% of median)
      ('abort', msg) — abort the run; this looks like a coverage cliff

    --force-merge bypasses 'abort' (downgrades to 'warn') for cases where
    the user has investigated and confirmed the drop is legitimate (e.g.,
    StreetEasy temporarily down, real market shift).
    """
    history = load_health()
    key = f'pass1_{listing_type}'
    counts = sorted([r[key] for r in history[:COVERAGE_WINDOW]
                     if r.get(key) is not None and r.get(key, 0) > 0])
    if len(counts) < 3:
        return ('ok', f'no baseline yet for {listing_type} (have {len(counts)} days)')
    median = counts[len(counts)//2]
    if median == 0:
        return ('ok', f'baseline median is 0 for {listing_type}')
    pct = today_count / median
    base_msg = f'{listing_type}: today={today_count}, 7d median={median} ({pct*100:.0f}%)'
    if pct >= COVERAGE_WARN_PCT:
        return ('ok', base_msg)
    if pct >= COVERAGE_ABORT_PCT:
        return ('warn', f'⚠️  {base_msg} — below {int(COVERAGE_WARN_PCT*100)}% threshold')
    full = f'{base_msg} — below {int(COVERAGE_ABORT_PCT*100)}% threshold'
    if force_merge:
        return ('warn', f'⚠️  {full} — overridden by --force-merge')
    return ('abort', full)


# ─── W7: Per-Shortlist Pass 2 verification ──────────────────────────
# For shortlisted listings unseen in Pass 1 for ≥W7_STALE_DAYS, run the
# actor's single-listing detail endpoint to definitively check whether
# they're still on StreetEasy. Sets `pass2_confirmed_off_market: true` when
# the actor returns no data; clears the flag when it returns a real
# listing (so a re-listed apartment auto-recovers).
#
# READ-only access to Postgres status: this function calls /status to
# learn what's in the user's Shortlist bucket, but never writes there.
# Sticky-shortlist contract (see STATUS-FEATURE.md) preserved.
def verify_stale_shortlists(client, db):
    status_url = os.environ.get('STATUS_API_URL', '').rstrip('/')
    if not status_url:
        # Try .env fallback
        env_path = Path(__file__).parent.parent / '.env'
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith('STATUS_API_URL='):
                    status_url = line.split('=', 1)[1].strip().rstrip('/')
                    break
    if not status_url:
        print("  W7: skipped — STATUS_API_URL not configured")
        return

    try:
        resp = requests.get(status_url + '/status', timeout=15)
        resp.raise_for_status()
        items = resp.json().get('items', [])
    except Exception as e:
        print(f"  W7: skipped — Status API read failed ({e})")
        return

    today = datetime.date.today()
    candidates = []
    for r in items:
        if r.get('bucket') != 'shortlist':
            continue
        lid = r['listing_id']
        entry = db.get(lid)
        if not entry:
            continue   # status row points at a listing not in db (e.g. test row)
        last_pass1 = entry.get('last_pass1')
        if not last_pass1:
            candidates.append((lid, entry))
            continue
        try:
            age = (today - datetime.date.fromisoformat(last_pass1)).days
            if age >= W7_STALE_DAYS:
                candidates.append((lid, entry))
        except ValueError:
            pass

    if not candidates:
        print("  W7: no stale shortlist listings to verify")
        return

    candidates = candidates[:W7_PER_RUN_CAP]
    print(f"  W7: verifying {len(candidates)} stale shortlist listing(s) via Pass 2")

    # Build URLs (sale or rental path per listing's listing_type)
    urls = []
    for lid, entry in candidates:
        ltype = entry.get('listing_type', 'sale')
        path = 'rental' if ltype == 'rent' else 'sale'
        urls.append(f"https://streeteasy.com/{path}/{lid}")

    try:
        detail_items = client.run_and_wait(
            start_urls=urls,
            max_items=len(urls),
            label=f"W7 — Verify {len(urls)} stale shortlist",
            timeout_sec=PASS2_TIMEOUT_SEC,
        )
    except Exception as e:
        print(f"  W7: Pass 2 actor run failed — {e}")
        return

    # Map returned items by listing id (handle the actor's varying field names)
    items_by_id = {}
    for item in detail_items:
        iid = str(item.get('id') or item.get('listingId') or item.get('node_id') or '')
        if iid:
            items_by_id[iid] = item

    today_str = today.isoformat()
    confirmed_off = 0
    confirmed_active = 0
    for lid, entry in candidates:
        item = items_by_id.get(str(lid))
        # Off-market signal: no item returned for this URL, OR the actor
        # returned only its "No results found" / sentinel placeholder.
        # For rentals, price is embedded in price_histories_json (not top-level),
        # so we check all three rental namespace prefixes in addition to the
        # sale-side fields. Without this, valid rental responses would always
        # be misclassified as sentinels.
        is_rental_entry = entry.get('listing_type') == 'rent'
        has_price = bool(
            item and (
                item.get('price') or item.get('pricing_price') or
                item.get('saleCombineResponse_sale_price') or
                (is_rental_entry and (
                    item.get('combineData_rental_price_histories_json') or
                    item.get('rentalCombineResponse_rental_price_histories_json') or
                    item.get('rental_price_histories_json')
                ))
            )
        )
        is_sentinel = bool(item) and (
            item.get('message') in ('No results found',) or
            not has_price
        )
        if not item or is_sentinel:
            entry['pass2_confirmed_off_market'] = True
            entry['pass2_confirmed_at'] = today_str
            confirmed_off += 1
        else:
            # Got real data → clear any prior off-market flag (re-listed)
            if entry.get('pass2_confirmed_off_market'):
                entry.pop('pass2_confirmed_off_market', None)
                entry.pop('pass2_confirmed_at', None)
            # Also bump last_pass2 since we just confirmed presence
            entry['last_pass2'] = today_str
            confirmed_active += 1

    print(f"  W7 results: {confirmed_active} still active, {confirmed_off} confirmed off-market")


def detect_delistings(db, ids_seen_by_type):
    """Mark listings not seen in Pass 1 for DELIST_DAYS+ days as delisted."""
    today = datetime.date.today()
    delisted_count = 0

    for lid, entry in db.items():
        if entry.get("status") == "delisted":
            continue
        ltype = entry.get("listing_type", "sale")
        # Only check against the types we actually pulled this run
        if ltype not in ids_seen_by_type:
            continue
        if lid in ids_seen_by_type[ltype]:
            continue
        # Not seen this run — check last_pass1 age
        last_seen = entry.get("last_pass1")
        if last_seen:
            try:
                age = (today - datetime.date.fromisoformat(last_seen)).days
                if age >= DELIST_DAYS:
                    entry["status"] = "delisted"
                    delisted_count += 1
            except ValueError:
                pass

    if delisted_count > 0:
        print(f"  Delistings: {delisted_count} listings not seen for {DELIST_DAYS}+ days")

# ─── Debug Dump ────────────────────────────────────────────────────
def _debug_dump(samples, label=""):
    print(f"\nDEBUG — all {label} Pass 2 items failed normalization.", file=sys.stderr)
    for i, sample in enumerate(samples):
        print(f"\n  Item {i+1} keys: {sorted(sample.keys())}", file=sys.stderr)
        price_candidates = {k: v for k, v in sample.items()
                            if any(t in k.lower() for t in
                                   ["price", "ask", "cost", "fee", "tax", "list", "sale",
                                    "rent", "amount", "monthly"])}
        print(f"  Price-related fields: {price_candidates}", file=sys.stderr)
        print(f"  First 15 fields:", file=sys.stderr)
        for k, v in list(sample.items())[:15]:
            print(f"    {k}: {repr(v)[:100]}", file=sys.stderr)

# ─── Two-Pass Runner ───────────────────────────────────────────────
def run_two_pass(client, search_url, max_items, listing_type, pass1_only=False, force_pass2=False):
    """Run Pass 1 (+ optional Pass 2) for one listing type. Returns (listings, total_events).

    pass1_only=True: Skip Pass 2 entirely. Normalize and return Pass 1 search data
    directly. Use when the actor's individual listing pages are broken.

    Default (pass1_only=False): Delta strategy — Pass 1 discovers all active listing
    IDs + current prices. Compare against previous latest.json. Only new and
    price-changed listings go through Pass 2. Cuts Apify costs by ~80–90% on stable weeks.
    """
    is_rental    = listing_type == "rent"
    normalize_fn = normalize_rental if is_rental else normalize
    label_tag    = "rental" if is_rental else "sale"

    # ── Pass 1: Search → discover listing IDs + current prices ───────
    try:
        search_items = client.run_and_wait(
            start_urls=[search_url],
            max_items=max_items,
            label=f"Pass 1/2 — Search ({label_tag})",
            paginate=True,
        )
    except ApifyRunError as e:
        print(f"\nERROR: Pass 1 failed — {e}", file=sys.stderr)
        sys.exit(1)

    listing_urls = []
    listing_ids  = []   # parallel to listing_urls — lid for each entry
    pass1_prices = {}   # {id: price} — used for delta comparison
    pass1_dom    = {}   # {id: days_on_market} — fresh from search, avoids cache drift
    seen_ids     = set()
    listing_url_re = re.compile(r'https?://(?:www\.)?streeteasy\.com/(?:sale|rental)/(\d+)')

    for item in search_items:
        # Rental Pass 1 items use node_* prefix; sale Pass 1 items use bare names
        lid = str(item.get("node_id") or item.get("id") or item.get("listingId") or "")

        # For sales: prefer urlPath (e.g. /building/slug/unit) — this is the
        # format the actor handles correctly for Pass 2 sale detail pages.
        # For rentals: always use /rental/{id} — the building URL format
        # (/building/slug/unit) causes the actor to hang indefinitely on rentals
        # (verified 2026-04-21: run MPHqLxW7gqbJAy4SG never completed).
        url_path = (not is_rental) and (item.get("urlPath") or "")
        if url_path:
            url = f"https://streeteasy.com{url_path}"
        elif lid:
            url = f"https://streeteasy.com/{'rental' if is_rental else 'sale'}/{lid}"
        else:
            url = item.get("url") or item.get("originalUrl") or ""

        if not lid and url:
            m = listing_url_re.search(url)
            if m:
                lid = m.group(1)

        # Also parse urls_json — the actor emits batch items where each item's
        # urls_json field may contain individual listing URLs discovered from
        # a search results page (one batch item per search page scraped).
        if not lid:
            urls_json_raw = item.get("urls_json", "")
            if urls_json_raw:
                try:
                    batch = json.loads(urls_json_raw) if isinstance(urls_json_raw, str) else urls_json_raw
                    for entry in (batch if isinstance(batch, list) else []):
                        candidate = entry.get("url", "")
                        m = listing_url_re.search(candidate)
                        if m:
                            lid = m.group(1)
                            url = candidate.replace("www.streeteasy.com", "streeteasy.com")
                            break
                except (json.JSONDecodeError, TypeError, AttributeError):
                    pass

        if url and lid and lid not in seen_ids:
            listing_urls.append(url.replace("www.streeteasy.com", "streeteasy.com"))
            listing_ids.append(lid)
            seen_ids.add(lid)
            raw_price = (item.get("node_price")       # rental Pass 1
                         or item.get("price") or item.get("pricing_price")
                         or item.get("askingPrice") or item.get("asking_price"))
            if raw_price:
                try:
                    pass1_prices[lid] = int(raw_price)
                except (ValueError, TypeError):
                    pass
            # Capture days_on_market from Pass 1 so cached listings get a
            # fresh value rather than a synthetically incremented one. This
            # avoids drift when a listing is delisted and relisted (DOM resets
            # on StreetEasy but our cache would keep counting up).
            raw_dom = _get(item.get("node_days_on_market"),
                           item.get("days_on_market"), item.get("daysOnMarket"))
            if raw_dom is not None:
                try:
                    pass1_dom[lid] = int(raw_dom)
                except (ValueError, TypeError):
                    pass

    print(f"\n  Discovered {len(listing_urls)} unique {label_tag} listing IDs")

    # For rentals: build a Pass 1 stub map so we can backfill beds/baths/sqft/unit
    # after Pass 2 normalization. Those fields are absent from rental Pass 2 data
    # (combineData_rental_* namespace) but present in Pass 1 search results (node_*).
    pass1_stubs = {}
    if is_rental:
        for item in search_items:
            stub = normalize_fn(item)
            if stub and stub.get("id"):
                pass1_stubs[stub["id"]] = stub

    # Debug dump when 0 IDs extracted — dump ALL items so we can see what the
    # actor actually returns (not just item 0).
    if len(listing_urls) == 0 and search_items:
        print(f"\nDEBUG — 0 IDs extracted from {len(search_items)} Pass 1 {label_tag} items.",
              file=sys.stderr)
        for i, item in enumerate(search_items):
            print(f"\n  Item {i}: keys={sorted(item.keys())}", file=sys.stderr)
            for k, v in item.items():
                print(f"    {k}: {repr(v)[:200]}", file=sys.stderr)

    if len(listing_urls) < MIN_LISTINGS:
        print(f"\nWARN: Only {len(listing_urls)} {label_tag} listings in search — skipping Pass 2.",
              file=sys.stderr)
        return [], len(search_items)

    # ── Pass 1 only mode: skip Pass 2, normalize search items directly ─
    if pass1_only:
        print(f"  --pass1-only: skipping Pass 2, normalizing {len(search_items)} search items.")
        listings = []
        skipped  = 0
        for item in search_items:
            result = normalize_fn(item)
            if result:
                listings.append(result)
            else:
                skipped += 1
        print(f"  Total: {len(listings)} {label_tag} listings  (skipped/no-price: {skipped})")
        return listings, len(search_items)

    # ── Delta: load previous run, split into scrape vs. reuse ────────
    prev_by_id  = {}
    prev_date   = None
    data_dir    = Path(__file__).parent.parent / "data"
    latest_path = data_dir / "latest.json"
    if force_pass2:
        print(f"  --force-pass2: bypassing delta cache, scraping all {len(listing_urls)} listings.")
    elif latest_path.exists():
        try:
            with open(latest_path) as f:
                prev_payload = json.load(f)
            for lst in prev_payload.get("listings", []):
                if lst.get("listing_type") == listing_type and lst.get("id"):
                    prev_by_id[lst["id"]] = lst
            prev_date_str = prev_payload.get("generated_at", "")
            if prev_date_str:
                prev_date = datetime.date.fromisoformat(prev_date_str)
        except (json.JSONDecodeError, KeyError, ValueError, OSError):
            pass  # no previous data — scrape everything

    today        = datetime.date.today()
    days_elapsed = (today - prev_date).days if prev_date else 0

    to_scrape_urls = []
    to_reuse       = []
    new_count      = 0
    changed_count  = 0
    reused_count   = 0

    for url, lid in zip(listing_urls, listing_ids):
        prev = prev_by_id.get(lid)
        if force_pass2 or prev is None:
            # force_pass2: scrape everything regardless of cache
            # prev is None: new listing — always scrape for full detail
            to_scrape_urls.append(url)
            if prev is None:
                new_count += 1
            else:
                changed_count += 1   # counted as "changed" for logging purposes
        else:
            curr_price = pass1_prices.get(lid)
            prev_price = prev.get("price")
            if curr_price and prev_price and curr_price != prev_price:
                # Price changed — re-scrape to get fresh data + updated history
                to_scrape_urls.append(url)
                changed_count += 1
            else:
                # Price unchanged — reuse cached detail with fresh DOM from Pass 1.
                # Prefer the live Pass 1 value over incrementing the cached one:
                # if a listing was delisted and relisted, DOM resets on StreetEasy
                # but synthetic incrementing would keep counting up incorrectly.
                cached = dict(prev)
                if lid in pass1_dom:
                    cached["days_on_market"] = pass1_dom[lid]
                elif cached.get("days_on_market") is not None and days_elapsed > 0:
                    cached["days_on_market"] = cached["days_on_market"] + days_elapsed
                to_reuse.append(cached)
                reused_count += 1

    print(f"  Delta — new: {new_count}  price-changed: {changed_count}  "
          f"unchanged (cached): {reused_count}")
    print(f"  Scraping {len(to_scrape_urls)} listings via Pass 2  "
          f"(skipping {reused_count} unchanged)")

    # ── Pass 2: Scrape only new + changed listings (in batches) ──────
    detail_items = []
    if to_scrape_urls:
        batches    = [to_scrape_urls[i:i+PASS2_BATCH_SIZE]
                      for i in range(0, len(to_scrape_urls), PASS2_BATCH_SIZE)]
        total_urls = len(to_scrape_urls)
        for batch_num, batch in enumerate(batches, 1):
            try:
                batch_items = client.run_and_wait(
                    start_urls=batch,
                    max_items=len(batch),
                    label=(f"Pass 2/2 — Detail pages ({label_tag}, "
                           f"batch {batch_num}/{len(batches)}, "
                           f"URLs {(batch_num-1)*PASS2_BATCH_SIZE+1}–"
                           f"{min(batch_num*PASS2_BATCH_SIZE, total_urls)} of {total_urls})"),
                    timeout_sec=PASS2_TIMEOUT_SEC,
                    paginate=False,   # individual listing URLs — nothing to paginate
                )
                detail_items.extend(batch_items)
            except ApifyRunError as e:
                # One batch failing doesn't kill the whole run — log and continue.
                # Affected listings fall back to cached/Pass-1 data this week.
                print(f"\nWARN: Batch {batch_num}/{len(batches)} failed — {e}. "
                      f"Continuing with remaining batches.", file=sys.stderr)
    else:
        print(f"\n  Pass 2 skipped — all {reused_count} {label_tag} listings unchanged.")

    listings         = list(to_reuse)
    pass2_normalized = 0   # count of items successfully normalized from Pass 2
    skipped          = 0
    skipped_samples  = []
    for item in detail_items:
        result = normalize_fn(item)
        if result:
            # For rentals: backfill beds/baths/sqft/unit from Pass 1 stub if
            # Pass 2 didn't provide them (rental Pass 2 schema omits these fields).
            if is_rental and result.get("id") in pass1_stubs:
                stub = pass1_stubs[result["id"]]
                for field in ("beds", "baths", "sqft", "unit", "price_per_sqft"):
                    if result.get(field) is None and stub.get(field) is not None:
                        result[field] = stub[field]
            listings.append(result)
            pass2_normalized += 1
        else:
            skipped += 1
            if len(skipped_samples) < 3:
                skipped_samples.append(item)

    print(f"\n  Total: {len(listings)} {label_tag} listings  (skipped/no-price: {skipped})")

    # Debug dump + Pass 1 fallback if Pass 2 produced nothing new.
    # Use pass2_normalized counter (not identity comparison on dicts) to check.
    if to_scrape_urls and pass2_normalized == 0:
        _debug_dump(skipped_samples, label_tag)
        print(f"\nFalling back to Pass 1 data for {label_tag} (sparse — no agent/history).",
              file=sys.stderr)
        for item in search_items:
            result = normalize_fn(item)
            if result:
                listings.append(result)
        print(f"  Pass 1 fallback: {len(listings)} {label_tag} listings", file=sys.stderr)

    total_events = len(search_items) + len(detail_items)
    return listings, total_events

# ─── Cost Estimate ─────────────────────────────────────────────────
def estimate_cost(count):
    return round(count * 0.003, 3)   # $3.00 / 1000 events

# ─── Main ──────────────────────────────────────────────────────────
def main():
    load_dotenv()
    args = parse_args()

    token = os.environ.get("APIFY_TOKEN")
    if not token:
        print("ERROR: APIFY_TOKEN not set.", file=sys.stderr)
        sys.exit(1)

    print("StreetHard — Apify Pull (Incremental)")
    print(f"  Actor:        {ACTOR_ID}")
    print(f"  Mode:         {args.mode}")
    print(f"  Max items:    {args.max_items} per type")
    print(f"  Pass 1 only:  {args.pass1_only}")
    print(f"  Force Pass 2: {args.force_pass2}")
    print(f"  Pass 2 cap:   {PASS2_PER_RUN_CAP} per run")
    print(f"  Dry run:      {args.dry_run}")

    client = ApifyClient(token)

    # ── Load canonical store ───────────────────────────────────────
    db = load_db()
    active_before = sum(1 for l in db.values() if l.get("status") != "delisted")
    pass2_before  = sum(1 for l in db.values()
                        if l.get("data_quality") == "pass2" and l.get("status") != "delisted")
    print(f"\n  db.json loaded: {active_before} active listings "
          f"({pass2_before} pass2 complete)")

    total_events    = 0
    ids_seen_by_type = {}     # {listing_type: set(ids)} for delisting detection (deprecated, kept for W7)
    pass1_counts_by_type = {} # {listing_type: int} for W4 pipeline health

    # ── Process each listing type ──────────────────────────────────
    for listing_type in ["sale", "rent"]:
        if listing_type == "sale" and args.mode not in ("sale", "both"):
            continue
        if listing_type == "rent" and args.mode not in ("rent", "both"):
            continue

        is_rental    = listing_type == "rent"
        normalize_fn = normalize_rental if is_rental else normalize
        label_tag    = "rental" if is_rental else "sale"
        search_url   = args.rental_url if is_rental else args.sale_url

        print(f"\n{'═'*50}")
        print(f"  {'FOR RENT' if is_rental else 'FOR SALE'}: {search_url}")

        # ── Pass 1: Search → discover listing IDs ──────────────────
        try:
            search_items = client.run_and_wait(
                start_urls=[search_url],
                max_items=args.max_items,
                label=f"Pass 1 — Search ({label_tag})",
                paginate=True,
            )
        except ApifyRunError as e:
            print(f"\nERROR: Pass 1 failed — {e}", file=sys.stderr)
            # Save db with whatever we have so far, don't lose accumulated data
            if not args.dry_run:
                save_db(db, total_events)
            sys.exit(1)

        total_events += len(search_items)

        # ── Guard: detect "No results found" sentinel-only run ────────
        # When residential proxies hit a StreetEasy block, the actor returns
        # placeholder objects shaped like
        #   {"message": "No results found", "urls_json": "...", "timestamp": "..."}
        # instead of real listings. merge_pass1_into_db treats these as items
        # with no listing-id and silently discards them, but save_db then
        # re-commits the existing 373 listings as if the run succeeded — the
        # cron commit message reads "373 listings, $0.06" while we've actually
        # captured 0 fresh data. This silently masked a 12-day gap on the
        # 2026-04-23/27/30 cron runs. Fail loudly here so the cron step
        # exits non-zero and skips the commit.
        real_items = [it for it in search_items
                      if it.get("id") or it.get("listingId") or it.get("node_id")]
        if search_items and not real_items:
            sentinel_msgs = {it.get("message") for it in search_items if it.get("message")}
            print(f"\nERROR: Pass 1 ({label_tag}) returned {len(search_items)} "
                  f"items but none had a listing ID — all appear to be actor "
                  f"sentinels.", file=sys.stderr)
            print(f"  Sentinel messages: {sentinel_msgs}", file=sys.stderr)
            print(f"  This is the actor's response to a blocked StreetEasy "
                  f"request (residential proxy IP rotation issue, or actor "
                  f"regression). Aborting before commit so db.json is not "
                  f"re-saved as if the run succeeded. Retry the workflow; "
                  f"different proxy IPs typically work.", file=sys.stderr)
            sys.exit(1)

        # ── W5: Pass 1 coverage cliff guard ───────────────────────
        # Compares this Pass 1 result count to the rolling 7-day median.
        # Aborts the run *before merging* if today's count is <50% of
        # baseline — the failure mode that produced the 2026-04-22 cliff.
        guard_status, guard_msg = check_pass1_coverage(
            listing_type, len(real_items), args.force_merge)
        print(f"  W5 coverage check — {guard_msg}")
        if guard_status == 'abort':
            print(f"\nERROR: Pass 1 coverage cliff detected. {guard_msg}", file=sys.stderr)
            print(f"  This looks like the 2026-04-22 incident. Refusing to merge "
                  f"{listing_type} results. Override with --force-merge if intentional.",
                  file=sys.stderr)
            # Record the cliff in pipeline_health so the in-app strip flags it
            if not args.dry_run:
                update_pipeline_health(
                    datetime.date.today().isoformat(),
                    {listing_type: len(real_items)},
                    db, guard_status='abort')
                save_db(db, total_events)
            sys.exit(1)

        # ── Merge Pass 1 into db ──────────────────────────────────
        ids_seen, urls_by_id, pass1_stubs = merge_pass1_into_db(
            db, search_items, listing_type, normalize_fn)
        ids_seen_by_type[listing_type] = set(ids_seen)
        pass1_counts_by_type[listing_type] = len(real_items)  # W4 health

        # Save db after Pass 1 merge — even if Pass 2 fails, we keep the Pass 1 data
        if not args.dry_run:
            save_db(db, total_events)

        # ── Pass 2 (detail pages) — incremental ──────────────────
        if args.pass1_only:
            print(f"  --pass1-only: skipping Pass 2 for {label_tag}")
            continue

        # Build queue: only pass1-quality + price-changed listings
        if args.force_pass2:
            # Force mode: queue ALL listings, not just missing ones
            print(f"  --force-pass2: queuing all {len(ids_seen)} {label_tag} listings for Pass 2")
            queue = [(lid, urls_by_id[lid]) for lid in ids_seen if lid in urls_by_id]
            queue = queue[:PASS2_PER_RUN_CAP]
        else:
            queue = build_pass2_queue(db, ids_seen, urls_by_id, listing_type)

        if not queue:
            print(f"  Pass 2 skipped — all {label_tag} listings already at pass2 quality")
            continue

        # Run Pass 2 in batches
        detail_items = []
        urls_to_scrape = [url for _, url in queue]
        batches = [urls_to_scrape[i:i+PASS2_BATCH_SIZE]
                   for i in range(0, len(urls_to_scrape), PASS2_BATCH_SIZE)]

        for batch_num, batch in enumerate(batches, 1):
            try:
                batch_items = client.run_and_wait(
                    start_urls=batch,
                    max_items=len(batch),
                    label=(f"Pass 2 — Detail ({label_tag}, "
                           f"batch {batch_num}/{len(batches)}, "
                           f"{len(batch)} URLs)"),
                    timeout_sec=PASS2_TIMEOUT_SEC,
                    paginate=False,
                )
                detail_items.extend(batch_items)
                total_events += len(batch_items)
            except (ApifyRunError, requests.RequestException) as e:
                # ApifyRunError: actor run itself failed (timeout, FAILED status).
                # requests.RequestException: transient HTTP/network error talking
                # to api.apify.com (e.g., 502 Bad Gateway during status polling)
                # AFTER get_run's own retry budget was exhausted. Either way,
                # this batch is lost but Pass 1 progress is already saved and
                # subsequent batches deserve a chance — the affected listings
                # will still be queued for Pass 2 on the next run because they
                # remain at data_quality='pass1'.
                print(f"\n  WARN: Batch {batch_num}/{len(batches)} failed — {e}. "
                      f"Continuing with remaining batches.", file=sys.stderr)

            # Save db after each batch — salvage partial progress
            if detail_items and not args.dry_run:
                merge_pass2_into_db(db, detail_items, listing_type,
                                    normalize_fn, pass1_stubs)
                detail_items = []  # reset; already merged
                save_db(db, total_events)

        # Merge any remaining items from the last batch
        if detail_items and not args.dry_run:
            merge_pass2_into_db(db, detail_items, listing_type,
                                normalize_fn, pass1_stubs)
            save_db(db, total_events)

    # ── Delisting detection ────────────────────────────────────────
    # DISABLED — see PIPELINE-RESILIENCE-PLAN.md (W2). The previous absence-
    # timer logic produced a 246-listing false-flag incident on 2026-05-05
    # when StreetEasy changed null-sqft handling. Pure absence-from-Pass-1
    # is too noisy a signal to trip a status flag from. Staleness is now
    # surfaced per-listing via the W3 stale pill (last_pass1 in latest.json),
    # and shortlisted listings get definitive confirmation via Pass 2
    # sniffing (W7).
    # detect_delistings(db, ids_seen_by_type)

    # ── W7: Per-Shortlist Pass 2 verification ──────────────────────
    # For shortlisted listings unseen in Pass 1 for ≥7 days, definitively
    # check via Pass 2 detail. Replaces the absence-timer auto-delisting
    # (W2) for the listings that actually matter to the user (the ones
    # they've shortlisted).
    if not args.dry_run:
        try:
            verify_stale_shortlists(client, db)
            save_db(db, total_events)  # persist any pass2_confirmed_off_market changes
        except Exception as e:
            # W7 failure is non-fatal — pipeline continues
            print(f"  W7: verification step failed ({e}); continuing", file=sys.stderr)

    # ── W4: Update pipeline_health.json ────────────────────────────
    # Today's record: pass1 counts per type, active count, status. Drives
    # the in-app coverage strip and the W5 cliff guard's median baseline.
    if not args.dry_run:
        update_pipeline_health(
            datetime.date.today().isoformat(),
            pass1_counts_by_type,
            db,
            guard_status='ok')

    # ── Final save + generate latest.json ──────────────────────────
    if args.dry_run:
        active = sum(1 for l in db.values() if l.get("status") != "delisted")
        pass2  = sum(1 for l in db.values()
                     if l.get("data_quality") == "pass2" and l.get("status") != "delisted")
        print(f"\nDRY RUN — db has {active} active ({pass2} pass2). "
              f"Est. cost ${estimate_cost(total_events):.3f}")
        return

    save_db(db, total_events)

    sale_url_used   = args.sale_url   if args.mode in ("sale",  "both") else None
    rental_url_used = args.rental_url if args.mode in ("rent",  "both") else None
    all_listings = generate_latest(db, args.mode, total_events,
                                   sale_url=sale_url_used,
                                   rental_url=rental_url_used)

    print(f"\n  Estimated run cost: ${estimate_cost(total_events):.3f}")
    print("Done.")

if __name__ == "__main__":
    main()
