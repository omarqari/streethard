#!/usr/bin/env python3
"""
StreetHard — Apify Pull Script
Two-pass strategy per listing type:
  Pass 1 — Search URL → discover listing IDs (stub data)
  Pass 2 — Individual listing pages → full data

Usage:
  python scripts/pull.py [--mode both|sale|rent] [--max-items N] [--dry-run]
  python scripts/pull.py --sale-url URL --rental-url URL  (override search URLs)

Environment:
  APIFY_TOKEN  — required. Set in .env locally or as GitHub Secret in CI.

Output:
  data/latest.json          — overwritten on every successful run
  data/YYYY-MM-DD.json      — immutable dated archive

Guard:
  Exits with code 1 (no files written) if total listing count < MIN_LISTINGS.
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
PASS2_TIMEOUT_SEC    = 1800   # 30 min — individual pages can be slow
PASS2_BATCH_SIZE     = 50     # max URLs per Pass 2 Apify run; avoids actor timeouts

SALE_URL = (
    "https://streeteasy.com/for-sale/upper-east-side"
    "/price:2000000-5000000%7Csqft:1500-"
)
RENTAL_URL = (
    "https://streeteasy.com/for-rent/upper-east-side"
    "/price:10000-20000%7Csqft:1500-"
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
                   help="Bypass the delta cache and run Pass 2 on all listings. "
                        "Use once after Pass 2 was broken to backfill fees/taxes/agent/history.")
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
        resp = self.session.get(f"{self.BASE}/actor-runs/{run_id}", timeout=30)
        resp.raise_for_status()
        return resp.json()["data"]

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
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            run_status = self.get_run(run_id)
            status = run_status.get("status", "")
            print(f" {status}", end="", flush=True)
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break
            time.sleep(POLL_INTERVAL_SEC)
        else:
            raise ApifyRunError(f"Timed out after {timeout_sec}s (run {run_id} still running)")

        print()
        if status != "SUCCEEDED":
            raise ApifyRunError(f"Run {run_id} ended with status {status}")

        items = self.get_dataset_items(dataset_id)
        print(f"  Items received: {len(items)}")
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

def normalize(raw):
    """Normalize a sale listing. Returns None if price is missing."""
    price = (
        raw.get(f"{_P1}pricing_price")
        or raw.get("pricing_price")
        or raw.get("price")
        or raw.get("askingPrice")
        or raw.get("asking_price")
    )
    if not price:
        return None

    listing_id = str(
        raw.get("listingId") or raw.get(f"{_P1}id") or raw.get("id") or ""
    )
    url = (
        raw.get("originalUrl") or raw.get("url")
        or (f"https://streeteasy.com/sale/{listing_id}" if listing_id else "")
    )

    beds = _get(
        raw.get(f"{_P1}propertyDetails_bedroomCount"),
        raw.get("bedroomCount"), raw.get("bedrooms"), raw.get("beds"),
    )
    full = _get(raw.get(f"{_P1}propertyDetails_fullBathroomCount"),
                raw.get("fullBathroomCount"), raw.get("bathrooms")) or 0
    half = _get(raw.get(f"{_P1}propertyDetails_halfBathroomCount"),
                raw.get("halfBathroomCount")) or 0
    baths = (full or 0) + (half or 0) * 0.5

    btype = (
        raw.get(f"{_P2}building_building_type")
        or raw.get(f"{_P3}type")
        or raw.get("building_building_type")
        or raw.get("propertyType") or raw.get("buildingType") or ""
    ).lower()
    ptype = "coop" if any(s in btype for s in ("co-op", "coop", "co_op")) else "condo"

    street = (
        raw.get(f"{_P1}propertyDetails_address_street")
        or raw.get(f"{_P3}address_street")
        or raw.get("address_street") or raw.get("addressStreet")
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
        or raw.get("address_unit") or raw.get("addressUnit") or raw.get("unit") or ""
    )

    _bldg_obj = raw.get("building")
    building = (
        raw.get(f"{_P2}building_title") or raw.get(f"{_P3}name")
        or raw.get("building_title") or raw.get("buildingTitle") or raw.get("buildingName")
        or ((_bldg_obj or {}).get("name") if isinstance(_bldg_obj, dict) else None)
        or street or ""
    )

    neighborhood = (
        raw.get(f"{_P2}area_name") or raw.get(f"{_P3}area_name")
        or raw.get("area_name") or raw.get("neighborhood") or raw.get("neighborhoodName")
        or raw.get("areaName") or ""   # Pass 1 search results use "areaName"
    )

    sqft = (
        raw.get(f"{_P1}propertyDetails_livingAreaSize")
        or raw.get("livingAreaSize") or raw.get("sqft") or raw.get("squareFeet")
    )
    ppsqft = raw.get(f"{_P2}price_per_sqft") or raw.get("price_per_sqft") or raw.get("ppsqft")
    if not ppsqft and sqft and price:
        ppsqft = round(int(price) / sqft)

    year_built = (
        raw.get(f"{_P2}building_year_built") or raw.get(f"{_P3}yearBuilt")
        or raw.get("building_year_built") or raw.get("yearBuilt") or raw.get("builtIn")
    )
    days_on_market = _get(
        raw.get(f"{_P2}days_on_market"),
        raw.get("days_on_market"), raw.get("daysOnMarket"),
    )

    # Use _get (not or) for fees/taxes — $0 is valid (tax abatements, some condos)
    maint_fee = _get(
        raw.get(f"{_P1}pricing_maintenanceFee"),
        raw.get("pricing_monthly_fees"), raw.get("monthlyHoa"), raw.get("commonCharges"),
    )
    taxes_fee = _get(
        raw.get(f"{_P1}pricing_taxes"),
        raw.get("pricing_monthly_taxes"), raw.get("monthlyTax"), raw.get("realEstateTaxes"),
    )
    old_maint = raw.get("pricing_monthly_maintenance") or raw.get("maintenance") or raw.get("monthlyMaintenance")

    if ptype == "coop":
        maint  = maint_fee or old_maint
        fees   = None
        taxes  = None
    else:
        fees   = maint_fee
        taxes  = taxes_fee if taxes_fee else None
        maint  = None

    agent_name = agent_phone = agent_email = agent_firm = None
    contacts_raw = raw.get(f"{_P2}contacts_json")
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
    ph_raw = raw.get(f"{_P4}price_histories_json") or raw.get(f"{_P2}price_histories_json")
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

    # Extract listed_date from the most recent LISTED event in price history.
    # Stored so the JS app can compute days-on-market at render time (always
    # current) rather than relying on a stale scraped snapshot.
    listed_date = None
    for h in history:
        if h.get("event") == "LISTED" and h.get("date"):
            listed_date = h["date"]
            break   # history is reverse-chronological; first LISTED = most recent

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
    }

# ─── Field Normalization — Rentals ─────────────────────────────────
# Pass 2 rental schema verified 2026-04-21 (run KIaeh9L2v7LkUSyZo, listing 5015416).
# Actual namespace: "combineData_rental_*" — completely different from the
# sale namespace and from what was originally guessed.
#
# Key gaps vs. sale Pass 2:
#   - No direct price field — extract from price_histories_json[0].price
#   - No beds/baths/sqft/unit — not in Pass 2 at all; come from Pass 1 search
#   - run_two_pass() merges Pass 1 stub data back in after normalization
#
# Pass 1 rental search items use "node_*" prefix (__typename == OrganicRentalEdge).
_RC = "combineData_rental_"   # Pass 2 rental namespace (verified)

def normalize_rental(raw):
    """Normalize a rental listing. Returns None if rent price is missing.
    For rentals, price = monthly rent (not a purchase price).

    Two schemas handled (in priority order):
      Pass 2 detail  — combineData_rental_* prefix (verified)
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
        ph_raw = raw.get(f"{_RC}price_histories_json")
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
        raw.get("node_buildingType"),    # Pass 1 rental search
        raw.get("building_building_type"),
        raw.get("propertyType"), raw.get("buildingType"),
    ) or "").lower()
    ptype = "coop" if any(s in btype for s in ("co-op", "coop", "co_op")) else "rental"

    # For Pass 2, building_title is the street address ("549 East 86th Street")
    building = _get(
        raw.get(f"{_RC}building_title"),
        raw.get("building_title"), raw.get("buildingTitle"), raw.get("buildingName"),
        raw.get("node_street"),          # Pass 1 rental search
        raw.get("street"),
    ) or ""

    street = _get(
        raw.get("node_street"),          # Pass 1 rental search
        raw.get("address_street"), raw.get("addressStreet"), raw.get("street"),
        raw.get(f"{_RC}building_title"), # Pass 2 fallback: building_title is the address
    ) or ""

    neighborhood = _get(
        raw.get(f"{_RC}area_name"),
        raw.get("node_areaName"),        # Pass 1 rental search
        raw.get("area_name"), raw.get("neighborhood"),
        raw.get("neighborhoodName"), raw.get("areaName"),
    ) or ""

    year_built = _get(
        raw.get(f"{_RC}building_year_built"),
        raw.get("building_year_built"), raw.get("yearBuilt"), raw.get("builtIn"),
    )
    days_on_market = _get(
        raw.get(f"{_RC}days_on_market"),
        raw.get("days_on_market"), raw.get("daysOnMarket"),
    )

    agent_name = agent_phone = agent_email = agent_firm = None
    contacts_raw = raw.get(f"{_RC}contacts_json") or raw.get("contacts_json")
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
    ph_raw = raw.get(f"{_RC}price_histories_json")
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
    listed_at_raw = raw.get(f"{_RC}listed_at")
    if listed_at_raw:
        listed_date = listed_at_raw[:10]   # "2026-04-16" from "2026-04-16T13:33:58-04:00"
    else:
        for h in history:
            if h.get("event") == "LISTED" and h.get("date"):
                listed_date = h["date"]
                break

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
    }

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

    print("StreetHard — Apify Pull")
    print(f"  Actor:      {ACTOR_ID}")
    print(f"  Mode:       {args.mode}")
    print(f"  Max items:  {args.max_items} per type")
    print(f"  Pass 1 only:  {args.pass1_only}")
    print(f"  Force Pass 2: {args.force_pass2}")
    print(f"  Dry run:      {args.dry_run}")

    client = ApifyClient(token)

    all_listings  = []
    total_events  = 0
    completed_types = []

    data_dir     = Path(__file__).parent.parent / "data"
    partial_path = data_dir / "partial.json"

    def _save_partial(listings, events, done_types):
        """Checkpoint completed listing type(s) to data/partial.json.

        Called after each type finishes so that if a later type fails
        mid-run (or the guard clause triggers), data already collected
        is not lost. The partial flag lets the app show a warning banner.
        """
        if args.dry_run:
            return
        data_dir.mkdir(exist_ok=True)
        today_str = datetime.date.today().isoformat()
        sales_so_far   = [l for l in listings if l["listing_type"] != "rent"]
        rentals_so_far = [l for l in listings if l["listing_type"] == "rent"]
        partial_payload = {
            "generated_at":  today_str,
            "partial":       True,
            "partial_types": done_types,
            "listing_count": len(listings),
            "sale_count":    len(sales_so_far),
            "rental_count":  len(rentals_so_far),
            "run_cost_usd":  estimate_cost(events),
            "mode":          args.mode,
            "listings":      listings,
        }
        with open(partial_path, "w") as f:
            json.dump(partial_payload, f, indent=2)
        print(f"  ✓ Checkpoint saved → data/partial.json "
              f"({len(listings)} listings so far)")

    if args.mode in ("sale", "both"):
        print(f"\n{'═'*50}")
        print(f"  FOR SALE: {args.sale_url}")
        listings, events = run_two_pass(
            client, args.sale_url, args.max_items, "sale",
            pass1_only=args.pass1_only,
            force_pass2=args.force_pass2,
        )
        all_listings.extend(listings)
        total_events += events
        completed_types.append("sale")
        _save_partial(all_listings, total_events, completed_types)

    if args.mode in ("rent", "both"):
        print(f"\n{'═'*50}")
        print(f"  FOR RENT: {args.rental_url}")
        listings, events = run_two_pass(
            client, args.rental_url, args.max_items, "rent",
            pass1_only=args.pass1_only,
            force_pass2=args.force_pass2,
        )
        all_listings.extend(listings)
        total_events += events
        completed_types.append("rent")
        _save_partial(all_listings, total_events, completed_types)

    # Guard clause — partial.json already has whatever we collected;
    # abort without overwriting latest.json.
    if len(all_listings) < MIN_LISTINGS:
        print(
            f"\nABORT: Only {len(all_listings)} listings after normalization "
            f"(minimum is {MIN_LISTINGS}).\ndata/latest.json was NOT overwritten."
            + (f"\ndata/partial.json preserves {len(all_listings)} listings "
               f"from completed types: {completed_types}."
               if completed_types and not args.dry_run else ""),
            file=sys.stderr,
        )
        sys.exit(1)

    # Sort: sales by price desc, then rentals by price desc
    sales   = sorted([l for l in all_listings if l["listing_type"] != "rent"],
                     key=lambda x: x["price"], reverse=True)
    rentals = sorted([l for l in all_listings if l["listing_type"] == "rent"],
                     key=lambda x: x["price"], reverse=True)
    all_listings = sales + rentals

    # Build payload
    today   = datetime.date.today().isoformat()
    payload = {
        "generated_at":  today,
        "listing_count": len(all_listings),
        "sale_count":    len(sales),
        "rental_count":  len(rentals),
        "run_cost_usd":  estimate_cost(total_events),
        "mode":          args.mode,
        "listings":      all_listings,
    }

    sale_url_used   = args.sale_url   if args.mode in ("sale",  "both") else None
    rental_url_used = args.rental_url if args.mode in ("rent",  "both") else None
    if sale_url_used:
        payload["sale_search_url"]   = sale_url_used
    if rental_url_used:
        payload["rental_search_url"] = rental_url_used

    if args.dry_run:
        print(f"\nDRY RUN — not writing files.")
        print(f"  Would write {len(all_listings)} listings "
              f"({len(sales)} sale, {len(rentals)} rental), "
              f"est. cost ${payload['run_cost_usd']:.3f}")
        return

    data_dir.mkdir(exist_ok=True)

    latest_path = data_dir / "latest.json"
    dated_path  = data_dir / f"{today}.json"

    with open(latest_path, "w") as f:
        json.dump(payload, f, indent=2)
    with open(dated_path, "w") as f:
        json.dump(payload, f, indent=2)

    # Clean up partial checkpoint — run succeeded, partial is now stale.
    if partial_path.exists():
        partial_path.unlink()

    print(f"\n✓ Wrote {len(all_listings)} listings "
          f"({len(sales)} sale, {len(rentals)} rental)")
    print(f"  {latest_path}")
    print(f"  {dated_path}")
    print(f"  Estimated run cost: ${payload['run_cost_usd']:.3f}")
    print("Done.")

if __name__ == "__main__":
    main()
