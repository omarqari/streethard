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

# ─── Config ────────────────────────────────────────────────────────
ACTOR_ID          = "memo23/streeteasy-ppr"
MIN_LISTINGS      = 10
POLL_INTERVAL_SEC = 5
RUN_TIMEOUT_SEC   = 600

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

    def run_and_wait(self, start_urls, max_items, label=""):
        print(f"\n{'─'*50}")
        print(f"  {label}")
        print(f"  URLs:      {len(start_urls)}")
        print(f"  Max items: {max_items}")

        # Only paginate beyond page 1 when fetching a full set of results.
        # For small test runs (max_items <= 20) stay on page 1 — moreResults
        # causes the actor to paginate aggressively before respecting maxItems,
        # making small test runs extremely slow.
        paginate = max_items > 20

        run_input = {
            "startUrls":   [{"url": u} for u in start_urls],
            "maxItems":    max_items,
            "moreResults": paginate,
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
            print(f"ERROR: Failed to start Apify run: {e}", file=sys.stderr)
            sys.exit(1)

        run_id     = run["id"]
        dataset_id = run["defaultDatasetId"]
        print(f"  Run ID:    {run_id}")
        print(f"  Dataset:   {dataset_id}")

        print("  Waiting for completion…", end="", flush=True)
        deadline = time.time() + RUN_TIMEOUT_SEC
        while time.time() < deadline:
            run_status = self.get_run(run_id)
            status = run_status.get("status", "")
            print(f" {status}", end="", flush=True)
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break
            time.sleep(POLL_INTERVAL_SEC)
        else:
            print("\nERROR: Timed out.", file=sys.stderr)
            sys.exit(1)

        print()
        if status != "SUCCEEDED":
            print(f"ERROR: Apify run ended with status {status}.", file=sys.stderr)
            sys.exit(1)

        items = self.get_dataset_items(dataset_id)
        print(f"  Items received: {len(items)}")
        return items

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

    beds = (
        raw.get(f"{_P1}propertyDetails_bedroomCount")
        or raw.get("bedroomCount") or raw.get("bedrooms") or raw.get("beds")
    )
    full = raw.get(f"{_P1}propertyDetails_fullBathroomCount") or raw.get("fullBathroomCount") or raw.get("bathrooms") or 0
    half = raw.get(f"{_P1}propertyDetails_halfBathroomCount") or raw.get("halfBathroomCount") or 0
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
        or raw.get("address_street") or raw.get("addressStreet") or ""
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
        or raw.get("area_name") or raw.get("neighborhood") or raw.get("neighborhoodName") or ""
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
    days_on_market = (
        raw.get(f"{_P2}days_on_market")
        or raw.get("days_on_market") or raw.get("daysOnMarket")
    )

    maint_fee = raw.get(f"{_P1}pricing_maintenanceFee")
    taxes_fee  = raw.get(f"{_P1}pricing_taxes")
    if maint_fee is None:
        maint_fee = raw.get("pricing_monthly_fees") or raw.get("monthlyHoa") or raw.get("commonCharges")
    if taxes_fee is None:
        taxes_fee = raw.get("pricing_monthly_taxes") or raw.get("monthlyTax") or raw.get("realEstateTaxes")
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
        agent_firm  = raw.get("agent_firm")  or raw.get("agentFirm") or raw.get("brokerageName")

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
# Rental GraphQL namespaces mirror sales with "rental" swapped for "sale".
# If normalization fails on first CI run, the debug dump will reveal
# actual field names so this function can be updated.
_R1 = "rentalListingDetailsFederated_data_rentalByListingId_"
_R2 = "rentalDetailsToCombineWithFederated_data_rental_"
_R3 = "rentalListingDetailsFederated_data_buildingByRentalListingId_"
_R4 = "extraListingDetails_data_rental_"

def normalize_rental(raw):
    """Normalize a rental listing. Returns None if rent price is missing.
    For rentals, price = monthly rent (not a purchase price).
    Field names mirror the sales schema with rental namespaces."""
    price = (
        raw.get(f"{_R1}pricing_price")
        or raw.get(f"{_R1}pricing_netEffectiveRent")
        or raw.get(f"{_R1}pricing_grossRent")
        or raw.get("pricing_price")
        or raw.get("price")
        or raw.get("askingRent") or raw.get("asking_rent")
        or raw.get("monthlyRent") or raw.get("monthly_rent")
        or raw.get("rent")
    )
    if not price:
        return None

    listing_id = str(
        raw.get("listingId") or raw.get(f"{_R1}id") or raw.get("id") or ""
    )
    url = (
        raw.get("originalUrl") or raw.get("url")
        or (f"https://streeteasy.com/rental/{listing_id}" if listing_id else "")
    )

    beds = (
        raw.get(f"{_R1}propertyDetails_bedroomCount")
        or raw.get("bedroomCount") or raw.get("bedrooms") or raw.get("beds")
    )
    full = raw.get(f"{_R1}propertyDetails_fullBathroomCount") or raw.get("fullBathroomCount") or raw.get("bathrooms") or 0
    half = raw.get(f"{_R1}propertyDetails_halfBathroomCount") or raw.get("halfBathroomCount") or 0
    baths = (full or 0) + (half or 0) * 0.5

    btype = (
        raw.get(f"{_R2}building_building_type")
        or raw.get(f"{_R3}type")
        or raw.get("building_building_type")
        or raw.get("propertyType") or raw.get("buildingType") or ""
    ).lower()
    ptype = "coop" if any(s in btype for s in ("co-op", "coop", "co_op")) else "condo"

    street = (
        raw.get(f"{_R1}propertyDetails_address_street")
        or raw.get(f"{_R3}address_street")
        or raw.get("address_street") or raw.get("addressStreet") or ""
    )
    if not street:
        addr_raw = raw.get("address") or {}
        if isinstance(addr_raw, dict):
            street = addr_raw.get("street") or addr_raw.get("streetAddress") or ""
        elif isinstance(addr_raw, str):
            street = addr_raw

    unit = (
        raw.get(f"{_R1}propertyDetails_address_unit")
        or raw.get("address_unit") or raw.get("addressUnit") or raw.get("unit") or ""
    )

    _bldg_obj = raw.get("building")
    building = (
        raw.get(f"{_R2}building_title") or raw.get(f"{_R3}name")
        or raw.get("building_title") or raw.get("buildingTitle") or raw.get("buildingName")
        or ((_bldg_obj or {}).get("name") if isinstance(_bldg_obj, dict) else None)
        or street or ""
    )

    neighborhood = (
        raw.get(f"{_R2}area_name") or raw.get(f"{_R3}area_name")
        or raw.get("area_name") or raw.get("neighborhood") or raw.get("neighborhoodName") or ""
    )

    sqft = (
        raw.get(f"{_R1}propertyDetails_livingAreaSize")
        or raw.get("livingAreaSize") or raw.get("sqft") or raw.get("squareFeet")
    )

    year_built = (
        raw.get(f"{_R2}building_year_built") or raw.get(f"{_R3}yearBuilt")
        or raw.get("building_year_built") or raw.get("yearBuilt") or raw.get("builtIn")
    )
    days_on_market = (
        raw.get(f"{_R2}days_on_market")
        or raw.get("days_on_market") or raw.get("daysOnMarket")
    )

    agent_name = agent_phone = agent_email = agent_firm = None
    contacts_raw = raw.get(f"{_R2}contacts_json") or raw.get("contacts_json")
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
        agent_firm  = raw.get("agent_firm")  or raw.get("agentFirm") or raw.get("brokerageName")

    history = []
    ph_raw = raw.get(f"{_R4}price_histories_json") or raw.get(f"{_R2}price_histories_json")
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
def run_two_pass(client, search_url, max_items, listing_type):
    """Run Pass 1 + Pass 2 for one listing type. Returns (listings, total_events).

    Delta strategy: Pass 1 discovers all active listing IDs + current prices.
    We compare against the previous run's data/latest.json. Listings whose price
    is unchanged are reused from cache — no Pass 2 scrape needed. Only new
    listings and price-changed listings go through Pass 2. This cuts Apify
    costs and scrape volume by ~80–90% on stable weeks.
    """
    is_rental    = listing_type == "rent"
    normalize_fn = normalize_rental if is_rental else normalize
    label_tag    = "rental" if is_rental else "sale"

    # ── Pass 1: Search → discover listing IDs + current prices ───────
    search_items = client.run_and_wait(
        start_urls=[search_url],
        max_items=max_items,
        label=f"Pass 1/2 — Search ({label_tag})",
    )

    listing_urls = []
    pass1_prices = {}   # {id: price} — used for delta comparison
    seen_ids     = set()
    for item in search_items:
        lid = str(item.get("id") or item.get("listingId") or "")
        url = (
            item.get("url") or item.get("originalUrl")
            or (f"https://streeteasy.com/{'rental' if is_rental else 'sale'}/{lid}" if lid else "")
        )
        if not lid and url:
            m = re.search(r'/(?:sale|rental)/(\d+)', url)
            if m:
                lid = m.group(1)
        if url and lid and lid not in seen_ids:
            listing_urls.append(url)
            seen_ids.add(lid)
            raw_price = (item.get("price") or item.get("pricing_price")
                         or item.get("askingPrice") or item.get("asking_price"))
            if raw_price:
                try:
                    pass1_prices[lid] = int(raw_price)
                except (ValueError, TypeError):
                    pass

    print(f"\n  Discovered {len(listing_urls)} unique {label_tag} listing IDs")

    # Debug dump when 0 IDs extracted — reveals what Pass 1 items actually look like
    if len(listing_urls) == 0 and search_items:
        print(f"\nDEBUG — 0 IDs extracted from {len(search_items)} Pass 1 {label_tag} items.",
              file=sys.stderr)
        sample = search_items[0]
        print(f"  Keys: {sorted(sample.keys())}", file=sys.stderr)
        id_url_fields = {k: v for k, v in sample.items()
                         if any(t in k.lower() for t in ["id", "url", "href", "link", "listing"])}
        print(f"  ID/URL-related fields: {id_url_fields}", file=sys.stderr)

    if len(listing_urls) < MIN_LISTINGS:
        print(f"\nWARN: Only {len(listing_urls)} {label_tag} listings in search — skipping Pass 2.",
              file=sys.stderr)
        return [], len(search_items)

    # ── Delta: load previous run, split into scrape vs. reuse ────────
    prev_by_id  = {}
    prev_date   = None
    data_dir    = Path(__file__).parent.parent / "data"
    latest_path = data_dir / "latest.json"
    if latest_path.exists():
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

    for url in listing_urls:
        m   = re.search(r'/(?:sale|rental)/(\d+)', url)
        lid = m.group(1) if m else None
        if not lid:
            to_scrape_urls.append(url)
            new_count += 1
            continue

        prev = prev_by_id.get(lid)
        if prev is None:
            # New listing — always scrape for full detail
            to_scrape_urls.append(url)
            new_count += 1
        else:
            curr_price = pass1_prices.get(lid)
            prev_price = prev.get("price")
            if curr_price and prev_price and curr_price != prev_price:
                # Price changed — re-scrape to get fresh data + updated history
                to_scrape_urls.append(url)
                changed_count += 1
            else:
                # Price unchanged — reuse cached detail, just advance days_on_market
                cached = dict(prev)
                if cached.get("days_on_market") is not None and days_elapsed > 0:
                    cached["days_on_market"] = cached["days_on_market"] + days_elapsed
                to_reuse.append(cached)
                reused_count += 1

    print(f"  Delta — new: {new_count}  price-changed: {changed_count}  "
          f"unchanged (cached): {reused_count}")
    print(f"  Scraping {len(to_scrape_urls)} listings via Pass 2  "
          f"(skipping {reused_count} unchanged)")

    # ── Pass 2: Scrape only new + changed listings ────────────────────
    detail_items = []
    if to_scrape_urls:
        detail_items = client.run_and_wait(
            start_urls=to_scrape_urls,
            max_items=len(to_scrape_urls),
            label=f"Pass 2/2 — Detail pages ({label_tag}, {len(to_scrape_urls)} of {len(listing_urls)})",
        )
    else:
        print(f"\n  Pass 2 skipped — all {reused_count} {label_tag} listings unchanged.")

    listings        = list(to_reuse)
    skipped         = 0
    skipped_samples = []
    for item in detail_items:
        result = normalize_fn(item)
        if result:
            listings.append(result)
        else:
            skipped += 1
            if len(skipped_samples) < 3:
                skipped_samples.append(item)

    print(f"\n  Total: {len(listings)} {label_tag} listings  (skipped/no-price: {skipped})")

    # Debug dump + Pass 1 fallback if all Pass 2 items fail normalization
    if skipped_samples and len([l for l in listings if l not in to_reuse]) == 0:
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
    print(f"  Actor:     {ACTOR_ID}")
    print(f"  Mode:      {args.mode}")
    print(f"  Max items: {args.max_items} per type")
    print(f"  Dry run:   {args.dry_run}")

    client = ApifyClient(token)

    all_listings  = []
    total_events  = 0

    if args.mode in ("sale", "both"):
        print(f"\n{'═'*50}")
        print(f"  FOR SALE: {args.sale_url}")
        listings, events = run_two_pass(client, args.sale_url, args.max_items, "sale")
        all_listings.extend(listings)
        total_events += events

    if args.mode in ("rent", "both"):
        print(f"\n{'═'*50}")
        print(f"  FOR RENT: {args.rental_url}")
        listings, events = run_two_pass(client, args.rental_url, args.max_items, "rent")
        all_listings.extend(listings)
        total_events += events

    # Guard clause
    if len(all_listings) < MIN_LISTINGS:
        print(
            f"\nABORT: Only {len(all_listings)} listings after normalization "
            f"(minimum is {MIN_LISTINGS}).\ndata/latest.json was NOT overwritten.",
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

    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)

    latest_path = data_dir / "latest.json"
    dated_path  = data_dir / f"{today}.json"

    with open(latest_path, "w") as f:
        json.dump(payload, f, indent=2)
    with open(dated_path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"\n✓ Wrote {len(all_listings)} listings "
          f"({len(sales)} sale, {len(rentals)} rental)")
    print(f"  {latest_path}")
    print(f"  {dated_path}")
    print(f"  Estimated run cost: ${payload['run_cost_usd']:.3f}")
    print("Done.")

if __name__ == "__main__":
    main()
