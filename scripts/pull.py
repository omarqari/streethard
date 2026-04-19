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
    "/price:2500000-4000000%7Csqft:1500-"
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
def normalize(raw):
    """
    Map Apify memo23/streeteasy-ppr individual listing page fields
    to StreetHard's clean schema.
    Returns None if the record is missing a price.
    """
    price = (
        raw.get("pricing_price")
        or raw.get("price")
        or raw.get("askingPrice")
    )
    if not price:
        return None

    # Beds / baths
    beds = raw.get("bedroomCount") or raw.get("bedrooms") or raw.get("beds")
    full = raw.get("fullBathroomCount") or raw.get("bathrooms") or 0
    half = raw.get("halfBathroomCount") or 0
    baths = (full or 0) + (half or 0) * 0.5

    # Property type
    btype = (
        raw.get("building_building_type")
        or raw.get("propertyType")
        or raw.get("buildingType")
        or ""
    ).lower()
    ptype = "coop" if ("co-op" in btype or "coop" in btype) else "condo"

    # Address — individual listing pages return these fields
    addr_raw = raw.get("address") or {}
    if isinstance(addr_raw, dict):
        street = addr_raw.get("street") or addr_raw.get("streetAddress") or ""
    else:
        street = str(addr_raw)
    street = street or raw.get("address_street") or raw.get("addressStreet") or ""

    unit = (
        raw.get("address_unit")
        or raw.get("addressUnit")
        or raw.get("unit")
        or (addr_raw.get("unit") if isinstance(addr_raw, dict) else "")
        or ""
    )

    # Building name
    building = (
        raw.get("building_title")
        or raw.get("buildingTitle")
        or raw.get("buildingName")
        or (raw.get("building", {}) or {}).get("name")
        or (raw.get("building", {}) or {}).get("title")
        or street
        or ""
    )

    # Neighborhood
    neighborhood = (
        raw.get("area_name")
        or raw.get("neighborhood")
        or raw.get("neighborhoodName")
        or (raw.get("location", {}) or {}).get("neighborhood")
        or ""
    )

    # Monthly costs
    fees  = raw.get("pricing_monthly_fees")  or raw.get("monthlyHoa")       or raw.get("commonCharges")
    taxes = raw.get("pricing_monthly_taxes") or raw.get("monthlyTax")       or raw.get("realEstateTaxes")
    maint = raw.get("pricing_monthly_maintenance") or raw.get("maintenance") or raw.get("monthlyMaintenance")
    if ptype == "coop":
        maint = maint or fees  # co-op maintenance often labelled as fees
        fees  = None
        taxes = None

    # Price history
    history_raw = (
        raw.get("priceHistory")
        or raw.get("price_history")
        or raw.get("listingHistory")
        or []
    )
    history = []
    for h in (history_raw or []):
        date   = h.get("date") or h.get("eventDate") or h.get("listed_at")
        hprice = h.get("price") or h.get("askingPrice")
        event  = (h.get("event") or h.get("eventType") or h.get("type") or "").upper().replace(" ", "_")
        broker = h.get("broker") or h.get("brokerageName") or h.get("agentFirm")
        if date or hprice:
            history.append({
                "date":   date,
                "price":  int(hprice) if hprice else None,
                "event":  event,
                "broker": broker,
            })

    # Agent
    agent_name  = raw.get("agent_name")  or raw.get("agentName")
    agent_phone = raw.get("agent_phone") or raw.get("agentPhone")
    agent_email = raw.get("agent_email") or raw.get("agentEmail")
    agent_firm  = raw.get("agent_firm")  or raw.get("agentFirm") or raw.get("brokerageName")

    listing_id = str(raw.get("id") or raw.get("listingId") or raw.get("streeteasyId") or "")
    url = (
        raw.get("url")
        or raw.get("listingUrl")
        or (f"https://streeteasy.com/sale/{listing_id}" if listing_id else "")
    )

    sqft = raw.get("livingAreaSize") or raw.get("sqft") or raw.get("squareFeet")
    ppsqft = raw.get("price_per_sqft") or raw.get("ppsqft")
    if not ppsqft and sqft and price:
        ppsqft = round(int(price) / sqft)

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
        "year_built":     raw.get("building_year_built") or raw.get("yearBuilt") or raw.get("builtIn"),
        "days_on_market": raw.get("days_on_market") or raw.get("daysOnMarket"),
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

    # ── Normalize
    listings = []
    skipped  = 0
    for item in detail_items:
        normalized = normalize(item)
        if normalized:
            listings.append(normalized)
        else:
            skipped += 1

    print(f"\n  Normalized:         {len(listings)}")
    print(f"  Skipped (no price): {skipped}")

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
