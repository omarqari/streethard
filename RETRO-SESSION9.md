# Retrospective — Session 9: The Backfill Lesson

**Date:** 2026-04-21
**Participants:** CTO, Chief Architect, Chief Product Officer
**Trigger:** Manual Pass 2 backfill completed 373/373 listings in ~15 minutes. Previous approach (automated pipeline via GitHub Actions) would have taken 6+ weeks at 30 listings/run, twice per week.

---

## What Happened

The StreetHard data pipeline was designed around an incremental "puzzle model" — each cron run fills in ~30 listings via Pass 2, accumulating over weeks until the database is complete. The architecture was sound for steady-state maintenance but was deployed as the strategy for initial data population. Today, we bypassed the pipeline entirely: called the Apify API directly in escalating batches (10 → 20 → 50 → 50 → 100 → 89 → 43), normalized the results, and merged them into db.json. Every batch returned 100% success rate, zero skips.

The entire backfill — 362 listings upgraded from pass1 to pass2 — took roughly 15 minutes of Apify runtime and 30 minutes wall-clock. The pipeline approach would have required ~12 cron runs over 6 weeks, with each run subject to the actor's flakiness, CI debugging cycles, and partial failures.

---

## CTO Perspective — Process & Execution

### What went wrong

**We confused "building the system" with "solving the problem."** The user's immediate need was a fully populated database. Instead of meeting that need directly, we spent sessions 2–8 building, debugging, and hardening a production pipeline — an incremental cron system designed for a future state where the database is already full and only needs maintenance. The pipeline is the right long-term architecture, but it was the wrong tool for the initial load.

**CI was used as a debugging environment.** Multiple sessions involved pushing code to GitHub, triggering Actions runs, waiting 6+ minutes per cycle, reading CI logs to figure out what went wrong, patching, and repeating. This violated our own "never test architecture in CI" rule (documented in CLAUDE.md after the fact — meaning we'd already learned this lesson and then didn't apply it to the backfill problem).

**Overcautious batch limits were never revisited.** `PASS2_BATCH_SIZE=10` and `PASS2_PER_RUN_CAP=30` were set during sessions 5–6 when the actor was genuinely broken (the 0.0.118 regression). After memo23 fixed it, those limits stayed in place unchallenged. Today proved the actor comfortably handles 100 URLs in a single run.

### What went right

**The incremental architecture itself is correct.** db.json as canonical store, pass1/pass2 quality flags, abort-and-salvage, delisting detection — all of this is well-designed for ongoing maintenance. The mistake wasn't building it; it was relying on it for initial population.

**Bottom-up validation rule paid off.** When we did today's backfill, we started with 10, verified, then 20, verified, then scaled up. This is exactly the pattern CLAUDE.md prescribes. It worked perfectly.

### Recommendation

**Add a "backfill mode" to the operational playbook.** When the database needs bulk population (initial load, new search criteria, schema changes requiring re-scrape), bypass the cron pipeline entirely. Call the API directly, merge results manually, push. Reserve the pipeline for steady-state maintenance only.

---

## Chief Architect Perspective — System Design

### What went wrong

**No separation between "initial load" and "steady-state maintenance."** The pipeline has one mode: incremental cron. It always does Pass 1 search first (discovering listings), then queues Pass 2 with a cap. This is correct for maintenance but wasteful for backfill — we already know which listings need Pass 2 (everything at pass1 quality), and we don't need a fresh Pass 1 search to figure that out.

**The pipeline's defensive design became its bottleneck.** Every safeguard added during the actor outage — small batches, low caps, per-batch saves, timeout-and-salvage — made the pipeline resilient but slow. These safeguards are load-bearing for unattended cron runs but unnecessary for supervised manual runs where a human can react to failures in real time.

**Batch size assumptions were never load-tested.** We assumed 10 URLs per batch was the safe limit based on actor behavior during a known regression. We never tested 20, 50, or 100 after the fix. Today's data: 100 URLs completed in ~2 minutes with zero failures.

### What went right

**db.json design made the backfill trivial.** Because the canonical store uses a simple dict keyed by listing ID with a `data_quality` flag, it was easy to write a one-off script that queries "give me all pass1 listings," sends them to Apify, and merges the results. The architecture supported the backfill even though the pipeline didn't.

**Normalization functions were rock-solid.** `normalize()` and `normalize_rental()` handled all 362 items without a single failure. The investment in mapping every field namespace during sessions 2–3 paid off completely.

### Recommendations

1. **Add `--backfill` mode to pull.py.** Skip Pass 1 entirely. Read db.json, find all pass1-quality listings, send them through Pass 2 in batches of 50-100. No cap. For supervised use only (not cron).

2. **Raise default batch limits for cron.** `PASS2_BATCH_SIZE` from 10 → 50. `PASS2_PER_RUN_CAP` from 30 → 100. The actor can handle it. Keep the timeout-and-salvage safety net.

3. **Document the two operational modes** (backfill vs. maintenance) in CLAUDE.md so future sessions don't repeat this mistake.

---

## CPO Perspective — Product & User Impact

### What went wrong

**The user waited 8 sessions for complete data.** The StreetHard app has been live since session 2, but for sessions 3–8, most listings showed mortgage-only monthly payments (no fees/taxes) because Pass 2 data wasn't populated. This meant the app's primary value proposition — accurate monthly cost comparison — was broken for 97% of listings. The user's family was looking at misleading numbers.

**We optimized for engineering elegance over time-to-value.** The incremental pipeline is a beautiful piece of engineering. It's also a 6-week ramp to full data when the user needed full data now. Shipping a working product with incomplete data and calling it "v1" was a disservice.

**Feature work was prioritized over data completeness.** Sessions 3 and 8 added rentals, text search, and price history date formatting — all nice-to-haves — while 97% of sale listings still lacked fees, taxes, and agent contact. Features on top of incomplete data is vanity work.

### What went right

**The app shell was built correctly from day one.** index.html handles pass2 data gracefully — all the UI for fees, taxes, agent info, payment breakdowns was already in place. The moment the data arrived today, the app immediately became fully functional with no code changes needed.

**The user pushed back at the right time.** Today's session happened because the user looked at the gap between "pipeline running" and "data actually complete" and asked the right question. The CPO lesson: listen when the user expresses frustration about timelines.

### Recommendations

1. **Data completeness is a launch blocker, not a backlog item.** If the primary metric (monthly payment) requires Pass 2 data, then Pass 2 completion is a P0, not something that "fills in over 12 runs."

2. **When the user can see the answer in 15 minutes, don't build a 6-week pipeline.** Always ask: "What's the fastest path to the user having what they need?" If the answer is "call the API directly," do that first, then build automation.

---

## Agreed Action Items

| # | Action | Owner | Status |
|---|--------|-------|--------|
| 1 | Document "Backfill vs. Maintenance" operational modes in CLAUDE.md | Session 9 | ✅ This session |
| 2 | Raise PASS2_BATCH_SIZE to 50 and PASS2_PER_RUN_CAP to 100 in pull.py | Session 9 | ✅ This session |
| 3 | Add new rule to CLAUDE.md: "Data completeness before features" | Session 9 | ✅ This session |
| 4 | Update PROJECTPLAN.md cost estimates and pipeline description | Session 9 | ✅ This session |
| 5 | Add `--backfill` flag to pull.py (skip Pass 1, process all pass1-quality listings) | Future | Backlog |
| 6 | Update CHANGELOG.md with session 9 events | Session 9 | ✅ This session |

---

## One-Line Takeaway

> **Don't build an irrigation system to fill a bathtub.** Solve the immediate problem directly, then automate the maintenance.
