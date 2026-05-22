#!/usr/bin/env python3
"""
Targeted rental Pass 2 backfill — two-phase design.

Phase 1 (--start):  Submit actor run, print run_id, exit immediately.
Phase 2 (--finish RUN_ID): Poll run, fetch results, merge into db.json.
"""
import sys, os, json, datetime, argparse, time
from pathlib import Path

# Resolve repo root relative to this script's location
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

from pull import (
    ApifyClient, normalize_rental, merge_pass2_into_db,
    load_db, save_db, generate_latest, ACTOR_ID, PASS2_TIMEOUT_SEC,
    SALE_URL, RENTAL_URL
)


def get_pass1_rentals():
    db = load_db()
    return {
        lid: listing for lid, listing in db.items()
        if isinstance(listing, dict)
        and listing.get("listing_type") == "rent"
        and listing.get("data_quality") == "pass1"
    }, db

def build_urls(pass1_rentals):
    urls = []
    for lid, listing in pass1_rentals.items():
        url_path = listing.get("url_path") or listing.get("url")
        if url_path and url_path.startswith("/"):
            url = f"https://streeteasy.com{url_path}"
        elif url_path and url_path.startswith("http"):
            url = url_path.replace("www.streeteasy.com", "streeteasy.com")
        else:
            url = f"https://streeteasy.com/rental/{lid}"
        urls.append(url)
    return urls

def phase_start():
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        print("ERROR: APIFY_TOKEN not set"); sys.exit(1)

    pass1_rentals, _ = get_pass1_rentals()
    if not pass1_rentals:
        print("No pass1 rentals — nothing to do."); return

    print(f"Found {len(pass1_rentals)} pass1 rentals:")
    for lid, l in pass1_rentals.items():
        print(f"  {lid}: {l.get('address')} {l.get('unit')}")

    urls = build_urls(pass1_rentals)
    print(f"\nURLs to submit:")
    for u in urls:
        print(f"  {u}")

    import requests as req
    client = ApifyClient(token)
    actor_path = ACTOR_ID.replace("/", "~")
    run_input = {
        "startUrls": [{"url": u} for u in urls],
        "maxItems": len(urls) + 5,
        "moreResults": False,
        "flattenDatasetItems": True,
        "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
    }
    resp = client.session.post(
        f"{client.BASE}/acts/{actor_path}/runs",
        json=run_input, timeout=30
    )
    resp.raise_for_status()
    run_id = resp.json()["data"]["id"]
    print(f"\nRun started: {run_id}")
    print(f"Run this next:\n  python3 rental_backfill.py --finish {run_id}")

def phase_finish(run_id):
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        print("ERROR: APIFY_TOKEN not set"); sys.exit(1)

    import requests as req
    client = ApifyClient(token)

    # Poll status
    resp = client.session.get(f"{client.BASE}/actor-runs/{run_id}", timeout=30)
    resp.raise_for_status()
    data = resp.json()["data"]
    status = data["status"]
    dur = round(data.get("stats", {}).get("durationMillis", 0) / 1000)
    print(f"Run {run_id}: {status} ({dur}s)")

    if status == "RUNNING":
        print("Still running — try again in 30s."); return False

    if status != "SUCCEEDED":
        print(f"Run did not succeed ({status}) — aborting."); sys.exit(1)

    # Fetch items
    dataset_id = data["defaultDatasetId"]
    items_resp = client.session.get(
        f"{client.BASE}/datasets/{dataset_id}/items",
        params={"limit": 500, "clean": "true"}, timeout=30
    )
    items_resp.raise_for_status()
    detail_items = items_resp.json()
    print(f"Items returned: {len(detail_items)}")

    # Check sentinel
    real_items = [it for it in detail_items if it.get("id") or it.get("listingId") or it.get("node_id")]
    if not real_items:
        print("ERROR: All items are sentinel/placeholder — proxy bad day.")
        if detail_items:
            print(f"  First item: {json.dumps(detail_items[0])}")
        sys.exit(1)
    print(f"Real items: {len(real_items)}")

    # Load db and stubs
    pass1_rentals, db = get_pass1_rentals()
    pass1_stubs = pass1_rentals

    # Merge
    upgraded = merge_pass2_into_db(db, real_items, "rent", normalize_rental, pass1_stubs)
    print(f"Upgraded: {upgraded} listings to pass2")

    save_db(db, len(detail_items))
    generate_latest(db, "both", len(detail_items), sale_url=SALE_URL, rental_url=RENTAL_URL)
    print("db.json + latest.json saved.")

    remaining = sum(1 for l in db.values() if isinstance(l, dict) and l.get("listing_type") == "rent" and l.get("data_quality") == "pass1")
    print(f"Remaining pass1 rentals: {remaining}")
    return True

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--start", action="store_true")
    p.add_argument("--finish", metavar="RUN_ID")
    args = p.parse_args()

    if args.start:
        phase_start()
    elif args.finish:
        phase_finish(args.finish)
    else:
        print("Usage: rental_backfill.py --start | --finish RUN_ID")
