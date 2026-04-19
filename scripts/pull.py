#!/usr/bin/env python3
"""
StreetHard — Apify Pull Script
Calls Apify memo23/streeteasy-ppr, normalizes output, saves to data/.

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
ACTOR_ID     = "memo23/streeteasy-ppr"
MIN_LISTINGS = 10       # Guard: abort if fewer than this many listings returned
POLL_INTERVAL_SEC = 5   # How often to poll Apify for run completion
RUN_TIMEOUT_SEC   = 600 # 10 minutes max wait

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

# ─── Field Normalization ───────────────────────────────────────────
def normalize(raw):
    """
    Map Apify memo23/streeteasy-ppr fields to StreetHard's clean schema.
    Returns None if the record is missing critical fields (price).
    """
    price = (
        raw.get("pricing_price")
        or raw.get("price")
        or raw.get("askingPrice")
    )
    if not price:
        return None

    # Beds / baths
    beds  = raw.get("bedroomCount") or raw.get("bedrooms") or raw.get("beds")
    full  = raw.get("fullBathroomCount") or raw.get("bathrooms") or 0
    half  = raw.get("halfBathroomCount") or 0
    baths = (full or 0) + (half or 0) * 0.5

    # Property type
    btype = (
        raw.get("building_building_type")
        or raw.get("propertyType")
        or raw.get("buildingType")
        or ""
    ).lower()
    if "co-op" in btype or "coop" in btype:
        ptype = "coop"
    else:
        ptype = "condo"

    # Address
    street = (
        raw.get("address_street")
        or raw.get("addressStreet")
        or raw.get("address", {}).get("street", "") if isinstance(raw.get("address"), dict) else raw.get("address", "")
    )
    unit = (
        raw.get("address_unit")
        or raw.get("addressUnit")
        or raw.get("unit")
        or ""
    )

    # Building
    building = (
        raw.get("building_title")
        or raw.get("buildingTitle")
        or raw.get("buildingName")
        or street
    )

    # Fees
    fees  = raw.get("pricing_monthly_fees") or raw.get("monthlyHoa") or raw.get("commonCharges")
    taxes = raw.get("pricing_monthly_taxes") or raw.get("monthlyTax") or raw.get("realEstateTaxes")
    maint = raw.get("pricing_monthly_maintenance") or raw.get("maintenance")
    # Co-ops use maintenance; condos use fees + taxes
    if ptype == "coop":
        maint = maint or fees  # some actors label maintenance as fees for co-ops
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
        event  = (h.get("event") or h.get("eventType") or h.get("type") or "").upper()
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

    listing_id = str(
        raw.get("id") or raw.get("listingId") or raw.get("streeteasyId") or ""
    )
    url = (
        raw.get("url")
        or raw.get("listingUrl")
        or (f"https://streeteasy.com/sale/{listing_id}" if listing_id else "")
    )

    return {
        "id":            listing_id,
        "url":           url,
        "building":      building,
        "address":       street,
        "unit":          unit,
        "neighborhood":  (
            raw.get("area_name") or raw.get("neighborhood")
            or raw.get("neighborhoodName") or ""
        ),
        "price":         int(price),
        "sqft":          raw.get("livingAreaSize") or raw.get("sqft") or raw.get("squareFeet"),
        "beds":          beds,
        "baths":         baths if baths > 0 else None,
        "price_per_sqft": raw.get("price_per_sqft") or raw.get("ppsqft"),
        "type":          ptype,
        "year_built":    (
            raw.get("building_year_built") or raw.get("yearBuilt")
            or raw.get("builtIn")
        ),
        "days_on_market": (
            raw.get("days_on_market") or raw.get("daysOnMarket")
        ),
        "monthly_fees":  int(fees)  if fees  else None,
        "monthly_taxes": int(taxes) if taxes else None,
        "maintenance":   int(maint) if maint else None,
        "agent_name":    agent_name,
        "agent_phone":   agent_phone,
        "agent_email":   agent_email,
        "agent_firm":    agent_firm,
        "price_history": history,
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
        print("ERROR: APIFY_TOKEN not set. Add it to .env or export it as an env variable.", file=sys.stderr)
        sys.exit(1)

    print(f"StreetHard — Apify Pull")
    print(f"  Actor:     {ACTOR_ID}")
    print(f"  URL:       {args.url}")
    print(f"  Max items: {args.max_items}")
    print(f"  Dry run:   {args.dry_run}")
    print()

    client = ApifyClient(token)

    # ── Start run
    print("Starting Apify run…")
    run_input = {
        "startUrls": [{"url": args.url}],
        "maxItems":  args.max_items,
    }
    try:
        run = client.start_run(ACTOR_ID, run_input)
    except requests.HTTPError as e:
        print(f"ERROR: Failed to start Apify run: {e}", file=sys.stderr)
        sys.exit(1)

    run_id     = run["id"]
    dataset_id = run["defaultDatasetId"]
    print(f"  Run ID:    {run_id}")
    print(f"  Dataset:   {dataset_id}")
    print()

    # ── Poll for completion
    print("Waiting for run to complete…")
    deadline = time.time() + RUN_TIMEOUT_SEC
    while time.time() < deadline:
        run_status = client.get_run(run_id)
        status = run_status.get("status", "")
        print(f"  Status: {status}")
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            break
        time.sleep(POLL_INTERVAL_SEC)
    else:
        print("ERROR: Timed out waiting for Apify run.", file=sys.stderr)
        sys.exit(1)

    if status != "SUCCEEDED":
        print(f"ERROR: Apify run ended with status {status}.", file=sys.stderr)
        sys.exit(1)

    # ── Download results
    print("\nDownloading results…")
    raw_items = client.get_dataset_items(dataset_id)
    print(f"  Raw items received: {len(raw_items)}")

    # ── Normalize
    listings = []
    skipped  = 0
    for item in raw_items:
        normalized = normalize(item)
        if normalized:
            listings.append(normalized)
        else:
            skipped += 1

    print(f"  Normalized:         {len(listings)}")
    print(f"  Skipped (no price): {skipped}")

    # ── Guard clause
    if len(listings) < MIN_LISTINGS:
        print(
            f"\nABORT: Only {len(listings)} listings returned (minimum is {MIN_LISTINGS}).\n"
            f"data/latest.json was NOT overwritten. Investigate before re-running.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Build output payload
    today = datetime.date.today().isoformat()
    payload = {
        "generated_at":   today,
        "listing_count":  len(listings),
        "run_cost_usd":   estimate_cost(len(raw_items)),
        "search_url":     args.url,
        "listings":       listings,
    }

    # ── Write files
    if args.dry_run:
        print(f"\nDRY RUN — not writing files. Would have written {len(listings)} listings.")
        return

    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)

    latest_path = data_dir / "latest.json"
    dated_path  = data_dir / f"{today}.json"

    with open(latest_path, "w") as f:
        json.dump(payload, f, indent=2)
    with open(dated_path, "w") as f:
        json.dump(payload, f, indent=2)

    cost = payload["run_cost_usd"]
    print(f"\n✓ Wrote {len(listings)} listings to:")
    print(f"  {latest_path}")
    print(f"  {dated_path}")
    print(f"\nEstimated run cost: ${cost:.3f}")
    print("Done.")

if __name__ == "__main__":
    main()
