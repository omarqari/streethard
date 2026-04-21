#!/usr/bin/env python3
"""
Bottom-up validation test: single rental listing via Apify memo23/streeteasy-ppr.

Listing: 301 East 94th Street #21C, Yorkville
StreetEasy URL: https://streeteasy.com/rental/4991146
StreetEasy listing ID: 4991146

Ground truth (from StreetEasy page + RapidAPI, captured 2026-04-19):
  rent:           $12,849/mo
  address:        301 E 94th Street #21C
  sqft:           1,450
  beds:           3
  baths:          3
  neighborhood:   Yorkville
  days_on_market: 34
  year_built:     1989
  no_fee:         True
  agent:          Rose Associates, Inc.  ← RapidAPI returned agents:[], Apify may differ
  price_history:  Listed 3/16/2026 @ $12,849 + prior 2024 history entries

Run:
  APIFY_TOKEN=your_token python scripts/test_rental_single.py

What this test validates:
  1. Actor accepts a rental URL (not just sale URLs)
  2. What field names the actor actually returns for rentals
  3. Whether price, address, sqft, beds/baths populate correctly
  4. Whether price history is present
  5. Whether agent info is present (RapidAPI had none — Apify may do better)
  6. Whether year_built and building-level fields come through
"""

import os
import sys
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv()

ACTOR_ID          = "memo23/streeteasy-ppr"
TEST_URL          = "https://streeteasy.com/rental/4991146"
POLL_INTERVAL_SEC = 5
RUN_TIMEOUT_SEC   = 300

# ─── Ground Truth ──────────────────────────────────────────────────
GROUND_TRUTH = {
    "rent":           12849,
    "address":        "301 E 94th Street #21C",
    "sqft":           1450,
    "beds":           3,
    "baths":          3,
    "neighborhood":   "yorkville",
    "days_on_market": 34,
    "year_built":     1989,
    "no_fee":         True,
    "agent_firm":     "Rose Associates",   # partial match is fine
    "price_history_count_min": 1,          # at least the 3/16/2026 listed entry
}

def run_apify(token):
    base = "https://api.apify.com/v2"
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    actor_path = ACTOR_ID.replace("/", "~")
    run_input = {
        "startUrls": [{"url": TEST_URL}],
        "maxItems": 1,
        "moreResults": False,   # must be False — True causes infinite pagination hang
        "proxy": {
            "useApifyProxy":    True,
            "apifyProxyGroups": ["RESIDENTIAL"],
        },
    }

    print(f"Starting Apify run for: {TEST_URL}")
    resp = session.post(f"{base}/acts/{actor_path}/runs", json=run_input, timeout=30)
    resp.raise_for_status()
    run = resp.json()["data"]
    run_id     = run["id"]
    dataset_id = run["defaultDatasetId"]
    print(f"  Run ID:    {run_id}")
    print(f"  Dataset:   {dataset_id}")

    print("  Waiting…", end="", flush=True)
    deadline = time.time() + RUN_TIMEOUT_SEC
    while time.time() < deadline:
        r = session.get(f"{base}/actor-runs/{run_id}", timeout=30)
        status = r.json()["data"]["status"]
        print(f" {status}", end="", flush=True)
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            break
        time.sleep(POLL_INTERVAL_SEC)
    print()

    if status != "SUCCEEDED":
        print(f"ERROR: Run ended with {status}")
        sys.exit(1)

    items_resp = session.get(
        f"{base}/datasets/{dataset_id}/items",
        params={"clean": "true", "limit": 10},
        timeout=30,
    )
    items_resp.raise_for_status()
    return items_resp.json()

def validate(items):
    print("\n" + "═"*60)
    print("RAW RESPONSE")
    print("═"*60)
    print(f"Items returned: {len(items)}")

    if not items:
        print("FAIL — no items returned at all")
        return

    # Print all keys and values from each item
    for i, item in enumerate(items):
        print(f"\n── Item {i+1} ──────────────────────────────────────────")
        print(f"  Keys ({len(item)}): {sorted(item.keys())}")
        print()
        for k, v in sorted(item.items()):
            val_repr = repr(v)
            if len(val_repr) > 120:
                val_repr = val_repr[:120] + "…"
            print(f"  {k}: {val_repr}")

    print("\n" + "═"*60)
    print("FIELD VALIDATION vs GROUND TRUTH")
    print("═"*60)

    # Use first item for validation
    raw = items[0]

    def check(label, actual, expected, partial=False):
        if actual is None:
            status = "❌ MISSING"
            detail = f"(expected {expected!r})"
        elif partial:
            match = str(expected).lower() in str(actual).lower()
            status = "✅" if match else "❌ MISMATCH"
            detail = f"got {actual!r}, expected to contain {expected!r}"
        else:
            match = actual == expected
            status = "✅" if match else "⚠️  MISMATCH"
            detail = f"got {actual!r}, expected {expected!r}"
        print(f"  {status}  {label}: {detail}")

    # Find price — try every plausible field name
    price = (raw.get("rentalListingDetailsFederated_data_rentalByListingId_pricing_price")
             or raw.get("pricing_price") or raw.get("price") or raw.get("askingRent")
             or raw.get("rent") or raw.get("monthlyRent"))
    check("rent", int(price) if price else None, GROUND_TRUTH["rent"])

    # Find address
    addr = (raw.get("rentalListingDetailsFederated_data_rentalByListingId_propertyDetails_address_street")
            or raw.get("address_street") or raw.get("addressStreet"))
    unit = (raw.get("rentalListingDetailsFederated_data_rentalByListingId_propertyDetails_address_unit")
            or raw.get("address_unit") or raw.get("unit"))
    addr_full = f"{addr} #{unit}" if addr and unit else (addr or "")
    check("address", addr_full or None, GROUND_TRUTH["address"], partial=True)

    # Sqft
    sqft = (raw.get("rentalListingDetailsFederated_data_rentalByListingId_propertyDetails_livingAreaSize")
            or raw.get("livingAreaSize") or raw.get("sqft"))
    check("sqft", sqft, GROUND_TRUTH["sqft"])

    # Beds
    beds = (raw.get("rentalListingDetailsFederated_data_rentalByListingId_propertyDetails_bedroomCount")
            or raw.get("bedroomCount") or raw.get("bedrooms"))
    check("beds", beds, GROUND_TRUTH["beds"])

    # Baths
    baths = (raw.get("rentalListingDetailsFederated_data_rentalByListingId_propertyDetails_fullBathroomCount")
             or raw.get("fullBathroomCount") or raw.get("bathrooms"))
    check("baths", baths, GROUND_TRUTH["baths"])

    # Days on market
    dom = (raw.get("rentalDetailsToCombineWithFederated_data_rental_days_on_market")
           or raw.get("days_on_market") or raw.get("daysOnMarket"))
    check("days_on_market", dom, GROUND_TRUTH["days_on_market"])

    # Year built
    yb = (raw.get("rentalDetailsToCombineWithFederated_data_rental_building_year_built")
          or raw.get("building_year_built") or raw.get("yearBuilt") or raw.get("builtIn"))
    check("year_built", yb, GROUND_TRUTH["year_built"])

    # Neighborhood
    hood = (raw.get("rentalDetailsToCombineWithFederated_data_rental_area_name")
            or raw.get("area_name") or raw.get("neighborhood"))
    check("neighborhood", (hood or "").lower() or None, GROUND_TRUTH["neighborhood"])

    # Agent
    contacts_raw = (raw.get("rentalDetailsToCombineWithFederated_data_rental_contacts_json")
                    or raw.get("contacts_json"))
    agent_firm = None
    if contacts_raw:
        try:
            contacts = json.loads(contacts_raw) if isinstance(contacts_raw, str) else contacts_raw
            if contacts:
                agent_firm = (contacts[0].get("source_group") or {}).get("label")
        except Exception:
            pass
    agent_firm = agent_firm or raw.get("agent_firm") or raw.get("agentFirm") or raw.get("brokerageName")
    check("agent_firm", agent_firm, GROUND_TRUTH["agent_firm"], partial=True)

    # Price history
    ph = (raw.get("extraListingDetails_data_rental_price_histories_json")
          or raw.get("rentalDetailsToCombineWithFederated_data_rental_price_histories_json")
          or raw.get("price_history") or raw.get("priceHistory"))
    if ph:
        try:
            ph_list = json.loads(ph) if isinstance(ph, str) else ph
            count = len(ph_list)
        except Exception:
            count = 0
    else:
        count = 0
    ok = count >= GROUND_TRUTH["price_history_count_min"]
    print(f"  {'✅' if ok else '❌ MISSING'}  price_history: {count} entries "
          f"(expected ≥{GROUND_TRUTH['price_history_count_min']})")

    print("\n" + "─"*60)
    print("NOTE: Any ❌ MISSING fields — find the actual key name in the")
    print("raw output above and update normalize_rental() in pull.py.")
    print("─"*60)

if __name__ == "__main__":
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        print("ERROR: APIFY_TOKEN not set. Run as:")
        print("  APIFY_TOKEN=your_token python scripts/test_rental_single.py")
        sys.exit(1)

    items = run_apify(token)
    validate(items)
