#!/usr/bin/env python3
"""One-off backfill: populate `building_name` on existing db.json listings from
the actor's `slug` field. Phased for the Cowork sandbox (no detached processes,
45s shell ceiling):

  python3 scripts/backfill_names.py --submit [N]   # submit a run for next N unprocessed
  python3 scripts/backfill_names.py --collect       # poll; on SUCCEEDED, merge slugs→building_name
  python3 scripts/backfill_names.py --status        # show progress

State persists in /tmp so it survives across independent shell calls within a
session. building_name uses pull.deslugify_building_name(); ids that have been
fetched (name or not) are marked processed so we don't re-fetch.
"""
import os, sys, json, time, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv("/sessions/compassionate-cool-wozniak/mnt/NYC Real Estate Advisor/.env")
import pull

STATE = "/tmp/bf_run.json"
PROCESSED = "/tmp/bf_processed.json"
BATCH_DEFAULT = 100

def load_json(p, d):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return d

def save_json(p, o):
    with open(p, "w") as f: json.dump(o, f)

def db_path():
    return str(pull.DB_PATH)

def all_target_ids(db):
    # listings with a URL we can fetch; both sale + rent
    out = []
    for lid, v in db.items():
        if v.get("url"):
            out.append((lid, v.get("listing_type", "sale")))
    return out

def client():
    return pull.ApifyClient(os.environ["APIFY_TOKEN"])

def cmd_status():
    db = pull.load_db()
    processed = set(load_json(PROCESSED, []))
    named = sum(1 for v in db.values() if v.get("building_name"))
    total = len(all_target_ids(db))
    print(f"listings: {len(db)} | with building_name: {named} | processed (fetched): {len(processed)}/{total}")
    st = load_json(STATE, None)
    if st: print(f"pending run: {st.get('run_id')} ({len(st.get('ids',[]))} ids)")

def cmd_submit(n):
    db = pull.load_db()
    processed = set(load_json(PROCESSED, []))
    if load_json(STATE, None):
        print("A run is already pending — run --collect first."); return
    todo = [(lid, lt) for lid, lt in all_target_ids(db) if lid not in processed]
    batch = todo[:n]
    if not batch:
        print("Nothing left to process. Backfill complete."); return
    urls = [{"url": v.get("url") or f"https://streeteasy.com/{'rental' if lt=='rent' else 'sale'}/{lid}"}
            for lid, lt in batch for v in [db[lid]]]
    run = client().start_run(pull.ACTOR_ID, {
        "startUrls": urls, "maxItems": len(urls), "moreResults": False,
        "flattenDatasetItems": True,
        "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]}})
    save_json(STATE, {"run_id": run["id"], "dataset_id": run["defaultDatasetId"],
                      "ids": [lid for lid, _ in batch], "submitted": time.time()})
    print(f"submitted run {run['id']} for {len(batch)} listings ({len(todo)-len(batch)} will remain)")

def cmd_collect(maxwait=36):
    st = load_json(STATE, None)
    if not st:
        print("No pending run. Use --submit."); return
    c = client()
    deadline = time.time() + maxwait
    status = c.get_run(st["run_id"]).get("status")
    while status not in ("SUCCEEDED","FAILED","ABORTED","TIMED-OUT") and time.time() < deadline:
        time.sleep(6); status = c.get_run(st["run_id"]).get("status")
    print("run status:", status)
    if status != "SUCCEEDED":
        print("not done yet — call --collect again."); return
    items = c.get_dataset_items(st["dataset_id"])
    # map listing id -> slug from response (id may be in several fields)
    db = pull.load_db()
    today = datetime.date.today().isoformat()
    by_id = {}
    for raw in items:
        lid = str(pull._get(raw.get("id"), raw.get("listingId"), raw.get("node_id"),
                            raw.get("listing_id")) or "")
        if lid:
            by_id[lid] = raw.get("slug")
    set_count = 0; none_count = 0; missing = 0
    for lid in st["ids"]:
        if lid not in by_id:
            missing += 1; continue
        name = pull.deslugify_building_name(by_id[lid])
        if lid in db:
            if name:
                db[lid]["building_name"] = name; set_count += 1
            else:
                none_count += 1
    pull.save_db(db)
    processed = set(load_json(PROCESSED, []))
    processed.update([lid for lid in st["ids"] if lid in by_id])  # only mark ids the actor returned
    save_json(PROCESSED, sorted(processed))
    os.remove(STATE)
    remaining = len([1 for lid, _ in all_target_ids(db) if lid not in processed])
    print(f"merged: {set_count} names set, {none_count} address-only (no name), {missing} not returned. remaining: {remaining}")

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: cmd_status()
    elif a[0] == "--status": cmd_status()
    elif a[0] == "--submit": cmd_submit(int(a[1]) if len(a) > 1 else BATCH_DEFAULT)
    elif a[0] == "--collect": cmd_collect()
    else: print("usage: --submit [N] | --collect | --status")
