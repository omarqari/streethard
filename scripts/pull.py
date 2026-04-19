#!/usr/bin/env python3
"""
StreetHard — Apify Pull Script
Two-pass strategy:
  Pass 1 — Search URL → discover all active listing IDs (stub data only)
  Pass 2 — Individual listing URLs → full data per listing

This is necessary because memo23/streeteasy-ppr returns only minimal fields
(id, price, beds, baths, sqft) from search result pages. Full fields
(address, building, fees, taxes, year built, days on market, price history,
agent contact) require scraping each individual listing page.

Usage:
  python scripts/pull.py [--url URL] [--max-items N] [--dry-run]

Environment:
  APIFY_TOKEN  — required. Set in .env locally or as GitHub Secret in CI.

Output:
  data/latest.json          — overwritten on every successful run
  data/YYYY-MM-DD.json      — immutable dated archive

Guard:
  Exits with code 1 (no files written) if listing count < MIN_LISTINGS.
"""

import os
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
MIN_LISTINGS      = 10       # Guard: abort if fewer than this many listings returned
POLL_INTERVAL_SEC = 5        # How often to poll Apify for run completion
RUN_TIMEOUT_SEC   = 600      # 10 minutes max wait per run

DEFAULT_URL = (
    "https://streeteasy.com/for-sale/upper-east-side"
    "/price:-5000000%7Csqft:1500-"
)
DEFAULT_MAX_ITEMS = 500

# ─── Argument Parsing ──────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="Pull StreetEasy listings via Apify")
    p.add_argument("--url",       default=DEFAULT_URL,       help="StreetEasy search URL")
    p.add_argument("--max-items", default=DEFAULT_MAX_ITEMS, type=int, help="Max listings to fetch")
    p.add_argument("--dry-run",   action="store_true",       help="Fetch data but don't write files")
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
        """Start a run, poll until complete, return raw dataset items."""
        print(f"\n{'─'*50}")
        print(f"  {label}")
        print(f"  URLs:      {len(start_urls)}")
        print(f"  Max items: {max_items}")

        run_input = {
            "startUrls": [{"url": u} for u in start_urls],
            "maxItems":  max_items,
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

# ─── Field Normalization ───────────────────────────────────────────
# Apify memo23/streeteasy-ppr flattens StreetEasy's federated GraphQL
# response into top-level keys with these prefixes for Pass 2 (individual
# listing pages). Pass 1 (search results) uses simple field names.
_P1 = "saleListingDetailsFederated_data_saleByListingId_"
_P2 = "saleDetailsToCombineWithFederated_data_sale_"
_P3 = "saleListingDetailsFederated_data_buildingBySaleListingId_"
_P4 = "extraListingDetails_data_sale_"

def normalize(raw):
    """Map Apify memo23/streeteasy-ppr fields to StreetHard's clean schema.
    Returns None if the record is missing a price."""
    # ── Price
    price = (
        raw.get(f"{_P1}pricing_price")     # Pass 2
        or raw.get("pricing_price")
        or raw.get("price")                # Pass 1
        or raw.get("askingPrice")
        or raw.get("asking_price")
    )
    if not price:
        return None

    # ── Listing ID / URL
    listing_id = str(
        raw.get("listingId")
        or raw.get(f"{_P1}id")
        or raw.get("id")
        or ""
    )
    url = (
        raw.get("originalUrl")
        or raw.get("url")
        or (f"https://streeteasy.com/sale/{listing_id}" if listing_id else "")
    )

    # ── Beds / baths
    beds = (
        raw.get(f"{_P1}propertyDetails_bedroomCount")
        or raw.get("bedroomCount")
        or raw.get("bedrooms")
        or raw.get("beds")
    )
    full = raw.get(f"{_P1}propertyDetails_fullBathroomCount") or raw.get("fullBathroomCount") or raw.get("bathrooms") or 0
    half = raw.get(f"{_P1}propertyDetails_halfBathroomCount") or raw.get("halfBathroomCount") or 0
    baths = (full or 0) + (half or 0) * 0.5

    # ── Property type
    btype = (
        raw.get(f"{_P2}building_building_type")    # "coop" / "condo"
        or raw.get(f"{_P3}type")                   # "CO_OP" / "CONDO"
        or raw.get("building_building_type")
        or raw.get("propertyType")
        or raw.get("buildingType")
        or ""
    ).lower()
    ptype = "coop" if any(s in btype for s in ("co-op", "coop", "co_op")) else "condo"

    # ── Address
    street = (
        raw.get(f"{_P1}propertyDetails_address_street")
        or raw.get(f"{_P3}address_street")
        or raw.get("address_street")
        or raw.get("addressStreet")
        or ""
    )
    if not street:
        addr_raw = raw.get("address") or {}
        if isinstance(addr_raw, dict):
            street = addr_raw.get("street") or addr_raw.get("streetAddress") or ""
        elif isinstance(addr_raw, str):
            street = addr_raw

    unit = (
        raw.get(f"{_P1}propertyDetails_address_unit")
        or raw.get("address_unit")
        or raw.get("addressUnit")
        or raw.get("unit")
        or ""
    )

    # ── Building name
    _bldg_obj = raw.get("building")
    building = (
        raw.get(f"{_P2}building_title")
        or raw.get(f"{_P3}name")
        or raw.get("building_title")
        or raw.get("buildingTitle")
        or raw.get("buildingName")
        or ((_bldg_obj or {}).get("name") if isinstance(_bldg_obj, dict) else None)
        or street
        or ""
    )

    # ── Neighborhood
    neighborhood = (
        raw.get(f"{_P2}area_name")
        or raw.get(f"{_P3}area_name")
        or raw.get("area_name")
        or raw.get("neighborhood")
        or raw.get("neighborhoodName")
        or ""
    )

    # ── Sqft / price-per-sqft
    sqft = (
        raw.get(f"{_P1}propertyDetails_livingAreaSize")
        or raw.get("livingAreaSize")
        or raw.get("sqft")
        or raw.get("squareFeet")
    )
    ppsqft = raw.get(f"{_P2}price_per_sqft") or raw.get("price_per_sqft") or raw.get("ppsqft")
    if not ppsqft and sqft and price:
        ppsqft = round(int(price) / sqft)

    # ── Year built / days on market
    year_built = (
        raw.get(f"{_P2}building_year_built")
        or raw.get(f"{_P3}yearBuilt")
        or raw.get("building_year_built")
        or raw.get("yearBuilt")
        or raw.get("builtIn")
    )
    days_on_market = (
        raw.get(f"{_P2}days_on_market")
        or raw.get("days_on_market")
        or raw.get("daysOnMarket")
    )

    # ── Monthly costs
    # Pass 2: pricing_maintenanceFee = HOA for condos, full maintenance for co-ops
    #         pricing_taxes = separate tax for condos, 0 for co-ops (included in maintenance)
    maint_fee = raw.get(f"{_P1}pricing_maintenanceFee")
    taxes_fee  = raw.get(f"{_P1}pricing_taxes")
    # Pass 1 fallbacks
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

    # ── Agent (Pass 2: JSON string; Pass 1: flat fields)
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

    # ── Price history (Pass 2: JSON string; Pass 1: list or empty)
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

    print("StreetHard — Apify Pull (two-pass)")
    print(f"  Actor:     {ACTOR_ID}")
    print(f"  Search:    {args.url}")
    print(f"  Max items: {args.max_items}")
    print(f"  Dry run:   {args.dry_run}")

    client = ApifyClient(token)

    # ── Pass 1: Search → discover listing IDs
    search_items = client.run_and_wait(
        start_urls=[args.url],
        max_items=args.max_items,
        label="Pass 1 of 2 — Search (discovering listing IDs)",
    )

    # Extract IDs and build individual listing URLs
    listing_urls = []
    seen_ids = set()
    for item in search_items:
        lid = str(item.get("id") or item.get("listingId") or "")
        url = item.get("url") or (f"https://streeteasy.com/sale/{lid}" if lid else "")
        if url and lid and lid not in seen_ids:
            listing_urls.append(url)
            seen_ids.add(lid)

    print(f"\n  Discovered {len(listing_urls)} unique listing IDs")

    if len(listing_urls) < MIN_LISTINGS:
        print(
            f"\nABORT: Only {len(listing_urls)} listings found in search (minimum is {MIN_LISTINGS}).",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Pass 2: Individual pages → full data
    detail_items = client.run_and_wait(
        start_urls=listing_urls,
        max_items=len(listing_urls),
        label="Pass 2 of 2 — Individual listing pages (full data)",
    )

    # ── Normalize Pass 2
    listings = []
    skipped  = 0
    skipped_samples = []
    for item in detail_items:
        normalized = normalize(item)
        if normalized:
            listings.append(normalized)
        else:
            skipped += 1
            if len(skipped_samples) < 3:
                skipped_samples.append(item)

    print(f"\n  Normalized:         {len(listings)}")
    print(f"  Skipped (no price): {skipped}")

    # ── Debug: dump raw field names when items fail normalization
    if skipped_samples and len(listings) == 0:
        print("\nDEBUG — all Pass 2 items failed normalization.", file=sys.stderr)
        for i, sample in enumerate(skipped_samples):
            print(f"\n  Item {i+1} keys: {sorted(sample.keys())}", file=sys.stderr)
            price_candidates = {k: v for k, v in sample.items()
                                if any(t in k.lower() for t in
                                       ["price", "ask", "cost", "fee", "tax", "list", "sale", "amount"])}
            print(f"  Price-related fields: {price_candidates}", file=sys.stderr)
            print(f"  First 15 fields:", file=sys.stderr)
            for k, v in list(sample.items())[:15]:
                print(f"    {k}: {repr(v)[:100]}", file=sys.stderr)

    # ── Fallback: if Pass 2 yields nothing, use Pass 1 (search result) data
    data_source = "pass2"
    if len(listings) < MIN_LISTINGS and search_items:
        print(f"\nPass 2 yielded {len(listings)} listings — falling back to Pass 1 search data.",
              file=sys.stderr)
        p1_listings = []
        for item in search_items:
            normalized = normalize(item)
            if normalized:
                p1_listings.append(normalized)
        print(f"  Pass 1 normalized: {len(p1_listings)}", file=sys.stderr)
        if len(p1_listings) >= MIN_LISTINGS:
            listings = p1_listings
            data_source = "pass1_fallback"
            print(f"  Using Pass 1 fallback ({len(listings)} listings — sparse data, no agent/history).",
                  file=sys.stderr)

    # ── Guard clause
    if len(listings) < MIN_LISTINGS:
        print(
            f"\nABORT: Only {len(listings)} listings after normalization (minimum is {MIN_LISTINGS}).\n"
            f"data/latest.json was NOT overwritten.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Sort by price descending (consistent ordering)
    listings.sort(key=lambda x: x["price"], reverse=True)

    # ── Build output payload
    today        = datetime.date.today().isoformat()
    total_events = len(search_items) + len(detail_items)
    payload = {
        "generated_at":  today,
        "listing_count": len(listings),
        "run_cost_usd":  estimate_cost(total_events),
        "search_url":    args.url,
        "data_source":   data_source,
        "listings":      listings,
    }

    if args.dry_run:
        print(f"\nDRY RUN — not writing files.")
        print(f"  Would write {len(listings)} listings, est. cost ${payload['run_cost_usd']:.3f}")
        return

    # ── Write files
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)

    latest_path = data_dir / "latest.json"
    dated_path  = data_dir / f"{today}.json"

    with open(latest_path, "w") as f:
        json.dump(payload, f, indent=2)
    with open(dated_path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"\n✓ Wrote {len(listings)} listings")
    print(f"  {latest_path}")
    print(f"  {dated_path}")
    print(f"  Estimated run cost: ${payload['run_cost_usd']:.3f}")
    print("Done.")

if __name__ == "__main__":
    main()
