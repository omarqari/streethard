#!/usr/bin/env python3
"""
Stale-listing Pass 2 refresh sweep.

WHY THIS EXISTS
---------------
The UES Pass 1 search only surfaces ~207 listings per run, but db.json
accumulates many more sale listings over time (filters changed, listings
rotate through the search's default sort, etc.). Listings that fall out of
the Pass 1 result *sample* age indefinitely — their `last_pass1` grows even
though many are still ACTIVE on StreetEasy. Some pick up price cuts in that
window that we never see, because nothing re-fetches them.

Confirmed 2026-06-14: a spot-check of the 12 oldest-stale sale listings
(unseen in Pass 1 for 54 days) found all 12 still active (offMarketAt=None),
and at least two with material undetected price cuts (923 5th Ave −$500K,
44 E 67th −$180K).

WHAT IT DOES
------------
Runs every stale listing (last_pass1 > --stale-days, default 7) back through
Pass 2 in batches. For each listing:
  * Returned with price  -> refresh price/history/fees via merge_pass2_into_db
                            (data_quality=pass2, last_pass2=today, status=active,
                            clears any pass2_confirmed_off_market flag).
  * Not returned (W7)    -> mark pass2_confirmed_off_market=True (reversible;
                            cleared automatically next time it's seen). We do
                            NOT flip status to delisted — absence from a single
                            Pass 2 run is treated as a soft off-market signal.

It deliberately does NOT touch `last_pass1` — that field means "last seen in
the Pass 1 SEARCH", and these listings genuinely aren't in the search sample.
The W3 stale pill therefore stays, which is correct; what changes is that the
price the family sees is now current.

This is "backfill mode" (CLAUDE.md): solve the data problem directly now,
rather than waiting weeks for the capped cron Pass 2 to drift through them.

Usage:
  python3 scripts/stale_refresh.py --run                 # sweep both types
  python3 scripts/stale_refresh.py --run --type sale     # sale only
  python3 scripts/stale_refresh.py --run --batch 40      # tune batch size
  python3 scripts/stale_refresh.py --dry-run             # list, don't fetch
"""
import sys, os, json, datetime, argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

from pull import (
    ApifyClient, normalize, normalize_rental, merge_pass2_into_db,
    load_db, save_db, generate_latest, PASS2_TIMEOUT_SEC,
    SALE_URL, RENTAL_URL,
)

STALE_DAYS_DEFAULT = 7
TODAY = datetime.date.today()


def _age_days(s):
    try:
        return (TODAY - datetime.date.fromisoformat(str(s)[:10])).days
    except Exception:
        return None


def stale_ids(db, listing_type, stale_days):
    out = []
    for lid, v in db.items():
        if not isinstance(v, dict):
            continue
        if v.get("listing_type") != listing_type:
            continue
        if v.get("status") == "delisted":
            continue
        age = _age_days(v.get("last_pass1"))
        if age is not None and age > stale_days:
            out.append(lid)
    return out


def build_url(lid, listing_type, listing):
    path = listing.get("url_path") or listing.get("url") or ""
    if path.startswith("/"):
        return f"https://streeteasy.com{path}"
    if path.startswith("http"):
        return path.replace("www.streeteasy.com", "streeteasy.com")
    seg = "rental" if listing_type == "rent" else "sale"
    return f"https://streeteasy.com/{seg}/{lid}"


def apply_batch(db, items, batch_ids, listing_type, before):
    """Merge one batch's Pass 2 items into db. Returns
    (refreshed, off_market, price_changes)."""
    norm = normalize_rental if listing_type == "rent" else normalize
    real = [it for it in items
            if it.get("id") or it.get("listingId") or it.get("node_id")]
    returned_ids = {str(it.get("id") or it.get("listingId")
                        or it.get("node_id")) for it in real}
    refreshed = merge_pass2_into_db(db, real, listing_type, norm, db)
    misses = 0
    price_changes = []
    for lid in batch_ids:
        if str(lid) in returned_ids:
            ent = db.get(lid, {})
            # A successful re-fetch is strong evidence of presence — clear any
            # prior off-market flag (re-listed / was a false positive).
            ent.pop("pass2_confirmed_off_market", None)
            ent.pop("pass2_confirmed_at", None)
            aft, bef = ent.get("price"), before.get(lid)
            if bef and aft and bef != aft:
                price_changes.append((lid, bef, aft, ent.get("address", "?")))
        else:
            # NO off-market flag from a single bulk-sweep miss. Validated
            # 2026-06-14: of 30 listings the sweep missed once, a re-verify
            # run returned data for ALL 30 — i.e. single misses are transient
            # backup-path drops, not real off-market. Definitive off-market
            # detection stays with W7 (verify_stale_shortlists), which targets
            # the high-value shortlist and tolerates the same transient noise
            # because it re-checks every cron run. Here we just count misses.
            misses += 1
    return refreshed, misses, price_changes


def sweep_type(client, db, listing_type, stale_days, batch_size, dry_run):
    """End-to-end blocking sweep (works where background processes persist;
    in sandboxed Cowork use the --submit/--collect phases instead)."""
    ids = stale_ids(db, listing_type, stale_days)
    print(f"\n{'='*60}\n{listing_type.upper()}: {len(ids)} stale listings "
          f"(last_pass1 > {stale_days}d)\n{'='*60}", flush=True)
    if dry_run:
        for lid in ids[:20]:
            v = db[lid]
            print(f"  {lid} | {_age_days(v.get('last_pass1'))}d | "
                  f"${v.get('price')} | {str(v.get('address'))[:34]}")
        if len(ids) > 20:
            print(f"  ... and {len(ids)-20} more")
        return {"stale": len(ids), "refreshed": 0, "price_changes": [],
                "off_market": 0, "failed_batches": 0}

    refreshed = off_market = failed_batches = 0
    price_changes = []
    for bnum, start in enumerate(range(0, len(ids), batch_size), 1):
        batch = ids[start:start + batch_size]
        urls = [build_url(lid, listing_type, db[lid]) for lid in batch]
        before = {lid: db[lid].get("price") for lid in batch}
        try:
            items = client.run_and_wait(
                start_urls=urls, max_items=len(urls) + 5,
                label=f"StaleRefresh {listing_type} batch {bnum}",
                timeout_sec=PASS2_TIMEOUT_SEC, paginate=False)
        except Exception as e:
            print(f"  BATCH {bnum} FAILED: {e}", flush=True)
            failed_batches += 1
            continue
        r, o, pc = apply_batch(db, items, batch, listing_type, before)
        refreshed += r; off_market += o; price_changes += pc
        save_db(db, 0)
    return {"stale": len(ids), "refreshed": refreshed,
            "price_changes": price_changes, "off_market": off_market,
            "failed_batches": failed_batches}


def run_capped(client, db, types, stale_days, batch_size, cap):
    """Blocking refresh of the `cap` MOST-stale listings across `types`
    (oldest last_pass1 first). Designed for the daily cron: keeps prices from
    drifting between manual sweeps without re-fetching the whole stale set
    every day. CI runs the process to completion, so the blocking path is fine
    (the sandbox's submit/collect phases are only needed inside Cowork).
    """
    # Candidate set = listings that have aged out of the Pass 1 search sample
    # (last_pass1 > stale_days). Among them, prioritise the ones whose PRICE
    # data is least-recently refreshed — i.e. oldest last_pass2 — NOT oldest
    # last_pass1 (the sweep doesn't touch last_pass1, so sorting by it would
    # pick the same listings every day and never rotate). Refreshing a listing
    # bumps its last_pass2 to today, pushing it to the back of the queue, so
    # the cap walks through the whole stale set over ~ceil(N/cap) days.
    scored = []
    for t in types:
        for lid in stale_ids(db, t, stale_days):
            refresh_age = _age_days(db[lid].get("last_pass2")
                                    or db[lid].get("last_pass1")) or 0
            scored.append((refresh_age, lid, t))
    scored.sort(reverse=True)             # least-recently refreshed first
    chosen = scored[:cap]
    by_type = {}
    for _, lid, t in chosen:
        by_type.setdefault(t, []).append(lid)
    print(f"Capped sweep: {len(chosen)} of {len(scored)} stale listings "
          f"(oldest first, cap={cap})", flush=True)

    refreshed = missed = 0
    price_changes = []
    for t, ids in by_type.items():
        for bnum, start in enumerate(range(0, len(ids), batch_size), 1):
            batch = ids[start:start + batch_size]
            urls = [build_url(lid, t, db[lid]) for lid in batch]
            before = {lid: db[lid].get("price") for lid in batch}
            try:
                items = client.run_and_wait(
                    start_urls=urls, max_items=len(urls) + 5,
                    label=f"StaleRefresh(cron) {t} batch {bnum}",
                    timeout_sec=PASS2_TIMEOUT_SEC, paginate=False)
            except Exception as e:
                print(f"  {t} batch {bnum} FAILED: {e}", flush=True)
                continue
            r, m, pc = apply_batch(db, items, batch, t, before)
            refreshed += r; missed += m; price_changes += pc
            save_db(db, 0)               # durability after each batch
    generate_latest(db, "both", 0, sale_url=SALE_URL, rental_url=RENTAL_URL)
    print(f"\nCAPPED SWEEP DONE — refreshed={refreshed}, "
          f"missed={missed} (not flagged off-market)")
    for lid, bef, aft, addr in price_changes:
        arrow = "DOWN" if aft < bef else "UP"
        print(f"   {arrow} {str(addr)[:32]:32} ${bef:,} -> ${aft:,} ({aft-bef:+,})")
    return refreshed


# ── Phased operation for sandboxed environments (submit-all then collect) ──
STATE_PATH = Path("/tmp/stale_sweep_state.json")


def phase_submit(client, db, types, stale_days, batch_size):
    actor_path = "memo23~streeteasy-ppr"
    batches = []
    for t in types:
        ids = stale_ids(db, t, stale_days)
        print(f"{t}: {len(ids)} stale -> "
              f"{(len(ids)+batch_size-1)//batch_size} batches")
        for start in range(0, len(ids), batch_size):
            bids = ids[start:start + batch_size]
            urls = [build_url(lid, t, db[lid]) for lid in bids]
            run_input = {
                "startUrls": [{"url": u} for u in urls],
                "maxItems": len(urls) + 5, "moreResults": False,
                "flattenDatasetItems": True,
                "proxy": {"useApifyProxy": True,
                          "apifyProxyGroups": ["RESIDENTIAL"]},
            }
            resp = client.session.post(
                f"{client.BASE}/acts/{actor_path}/runs",
                json=run_input, timeout=30)
            resp.raise_for_status()
            rid = resp.json()["data"]["id"]
            before = {lid: db[lid].get("price") for lid in bids}
            batches.append({"type": t, "run_id": rid, "ids": bids,
                            "before": before, "done": False})
            print(f"  submitted {t} batch [{start}:{start+len(bids)}] "
                  f"run={rid}")
    STATE_PATH.write_text(json.dumps(
        {"submitted_at": datetime.datetime.utcnow().isoformat(),
         "batches": batches}, indent=2))
    print(f"\nState written -> {STATE_PATH}  ({len(batches)} batches)")


def phase_collect(client, db):
    state = json.loads(STATE_PATH.read_text())
    batches = state["batches"]
    pending = [b for b in batches if not b.get("done")]
    print(f"{len(pending)} batch(es) pending of {len(batches)}")
    results = {}
    still_running = 0
    for b in batches:
        if b.get("done"):
            continue
        d = client.session.get(
            f"{client.BASE}/actor-runs/{b['run_id']}", timeout=30
        ).json()["data"]
        st = d["status"]
        if st == "RUNNING" or st == "READY":
            print(f"  {b['type']} run {b['run_id']}: {st} — skip"); still_running += 1
            continue
        if st != "SUCCEEDED":
            print(f"  {b['type']} run {b['run_id']}: {st} — marking failed")
            b["done"] = True; b["failed"] = True
            continue
        items = client.session.get(
            f"{client.BASE}/datasets/{d['defaultDatasetId']}/items",
            params={"limit": 500, "clean": "true"}, timeout=60).json()
        r, o, pc = apply_batch(db, items, b["ids"], b["type"], b["before"])
        b["done"] = True
        res = results.setdefault(b["type"], {"refreshed": 0, "missed": 0,
                                             "price_changes": []})
        res["refreshed"] += r; res["missed"] += o
        res["price_changes"] += pc
        print(f"  {b['type']} run {b['run_id']}: SUCCEEDED — "
              f"{len(items)} items, refreshed={r}, missed={o} (not flagged)")
    STATE_PATH.write_text(json.dumps(state, indent=2))
    # Persist after EVERY collect pass. Each --collect reloads a fresh db, so
    # if we only saved when all batches were done, partial progress from
    # earlier passes (already marked done in state) would be silently lost.
    save_db(db, 0)
    generate_latest(db, "both", 0, sale_url=SALE_URL, rental_url=RENTAL_URL)
    if still_running == 0:
        print("\nALL BATCHES DONE — db.json + latest.json saved.")
    else:
        print(f"\n{still_running} still running — db saved; re-run --collect "
              f"shortly to merge the rest.")
    print("\n" + "#" * 50 + "\nSUMMARY (this collect pass)\n" + "#" * 50)
    for t, r in results.items():
        print(f"{t.upper()}: refreshed={r['refreshed']} "
              f"missed={r['missed']} (not flagged off-market)")
        for lid, bef, aft, addr in r["price_changes"]:
            arrow = "DOWN" if aft < bef else "UP"
            print(f"   {arrow} {str(addr)[:32]:32} ${bef:,} -> ${aft:,} "
                  f"({aft-bef:+,})")
    return still_running == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--submit", action="store_true",
                    help="phase 1: submit all batch runs, write state")
    ap.add_argument("--collect", action="store_true",
                    help="phase 2: poll runs, merge finished batches")
    ap.add_argument("--type", choices=["sale", "rent", "both"], default="both")
    ap.add_argument("--stale-days", type=int, default=STALE_DAYS_DEFAULT)
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--cap", type=int, default=0,
                    help="with --run: refresh only the N most-stale listings "
                         "(oldest last_pass1 first). 0 = no cap. Used by cron.")
    args = ap.parse_args()

    token = os.environ.get("APIFY_TOKEN")
    client = ApifyClient(token) if token else None
    db = load_db()
    types = ["sale", "rent"] if args.type == "both" else [args.type]

    if args.submit:
        phase_submit(client, db, types, args.stale_days, args.batch)
    elif args.collect:
        phase_collect(client, db)
    elif args.dry_run:
        for t in types:
            sweep_type(None, db, t, args.stale_days, args.batch, True)
    elif args.run and args.cap:
        run_capped(client, db, types, args.stale_days, args.batch, args.cap)
    elif args.run:
        results = {t: sweep_type(client, db, t, args.stale_days,
                                 args.batch, False) for t in types}
        generate_latest(db, "both", 0, sale_url=SALE_URL,
                        rental_url=RENTAL_URL)
        print("db.json + latest.json saved.", results)
    else:
        ap.error("pass --submit/--collect (sandbox) or --run/--dry-run")


if __name__ == "__main__":
    main()
