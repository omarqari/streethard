# Pipeline Resilience Plan

Authored 2026-05-09 in response to the 246-listing false-flag delisting
incident. Sequenced for execution; each work item has explicit acceptance
criteria so completion is unambiguous.

---

## Background

On 2026-05-09 the user noticed Shortlist count had silently dropped from
14 to 6. Forensics showed:

- The app filters `latest.json` to active listings only; 246 listings were
  marked `status: "delisted"` in `db.json` and therefore hidden everywhere
  in the app — including listings the user had personally walked through
  on 2026-05-01 and 2026-05-02.
- Diagnostic signature: 100% of "delisted" listings shared
  `last_pass1=2026-04-21`. 0% of currently-active listings have null sqft.
  57% of false-flagged listings had null sqft.
- Root cause: StreetEasy's `sqft:1500-` URL-filter behavior changed around
  2026-04-22 to exclude listings with no published sqft. NYC co-ops
  systematically don't publish sqft. Pass 1 stopped seeing them, the
  14-day `mark_delisted()` timer expired on 2026-05-05, and all 246 were
  flagged in a single batch.
- Detection lag: the user discovered this 8 days after the cliff started,
  via a UI anomaly. There was no signal in the pipeline itself.

The deeper problem is not "delist logic was wrong." It is "the pipeline
silently degrades and we find out when something looks weird in the UI."
This plan addresses the failure class, not just this incident.

## Goals

- Eliminate the failure class that produced the 2026-05-05 incident.
- Make pipeline-coverage anomalies visible within one cron cycle.
- Protect user triage investment (Shortlist / Archive) from automated state
  changes that can be wrong.
- Keep Inbox curated — no flood of irrelevant listings.

## Non-goals

- **Recommendation D from the CPO review (broader pull + app-side filter)**:
  rejected. A neighborhood-scoped pull on UES sales returns ~1,000–1,500
  listings; the resulting Inbox flood (600+ studios / 1BRs / sub-$2M /
  super-$5M) would force manual archiving of irrelevant listings and
  make the Inbox count badge meaningless. Revisit only if the
  bedroom-based filter (W1) proves too restrictive.
- The 14 items in `PRODUCT-BACKLOG.md`.
- Multi-user, auth, billing — not applicable to an n=1 personal project.

---

## Phase 1 — Stabilize (this session, ~30 min)

### W1: Replace `sqft:1500-` URL filter with `beds:3-`

**Why:** sqft is unreliable upstream — co-ops don't publish it, so a sqft
filter has a built-in failure mode for half the inventory. Bedrooms are
universally published. `beds:3-` is a more honest expression of "family-
sized" and structurally robust to the kind of filter-behavior change that
caused the incident.

**Files**
- `scripts/pull.py` — `SALE_URL` and `RENTAL_URL` constants

**Change**
```python
SALE_URL   = "https://streeteasy.com/for-sale/upper-east-side/price:2000000-5000000%7Cbeds%3A3-"
RENTAL_URL = "https://streeteasy.com/for-rent/upper-east-side/price:10000-20000%7Cbeds%3A3-"
```

**Acceptance**
- Trigger one Pass 1 run after the change (manual workflow dispatch).
- Pass 1 result count ≥ 350 (vs current ~190).
- Spot-check: at least 4 of the 8 previously-hidden shortlist co-ops
  (1806171, 1809797, 1802031, 1811788, 1813477, 1811766, 1805766, 1811321)
  reappear in Pass 1 results.
- Inbox count after the run is within ±15% of pre-cliff baseline (~370).

**Risk**
- 2-bed-plus-den listings (sometimes listed as `beds:2`) get excluded.
  Mitigation: spot-check 5 known active 2BR+den listings on StreetEasy
  before declaring done. If material, fall back to `beds:2-` and use
  app-side filtering for triage.

**Effort:** 5 minutes + verification.

---

### W2: Kill auto-delisting

**Why:** For an n=1 family-apartment search, the user value of an
automatically-flagged "delisted" status is near zero, and the failure
cost is high (hidden Shortlist listings, lost triage work). Pure
absence-from-Pass-1 is too noisy a signal regardless of how the timer
is tuned. Removing the auto-delist mechanism makes this entire failure
class structurally impossible.

**Files**
- `scripts/pull.py`

**Change**
- Remove the call to `mark_delisted(db)` from `run_two_pass()` (the call
  sites in the main pipeline).
- Keep the function definition for now, with a comment pointing to this
  plan; will be removed in a later cleanup commit once W7 lands.
- Deprecate the `DELIST_DAYS` constant; replace with a comment noting
  staleness is now expressed via `last_pass1` (W3) and verified via
  Pass 2 sniffing (W7), never by absence-timer alone.
- One-time migration: any listing currently flagged `status: "delisted"`
  with no recent (`<30d`) DELIST event in `price_history` is reset to
  `status: "active"`. (Already done as part of the 2026-05-09 hotfix —
  this is just a defensive re-run on the off-chance any survived.)

**Acceptance**
- Run `pull.py` end-to-end. No listings change to `status: "delisted"`
  during the run.
- `latest.json`'s `delisted_count` is 0.
- The frontend's DELISTED badge does not render anywhere in the app.

**Risk**
- Truly-delisted listings sit in `db.json` indefinitely. Mitigation: the
  W3 stale pill makes this visible per-listing, and W7 actively confirms
  shortlisted off-market listings via Pass 2.

**Effort:** 15 minutes.

---

## Phase 2 — Observability (next session, ~2 hours)

### W3: "Last seen" data freshness pill

**Why:** Replaces the binary delisted-vs-active flag with a continuous
freshness signal. Makes pipeline staleness visible per-listing without
making claims about market state we can't verify from absence.

**Files**
- `scripts/pull.py` — `generate_latest()` strips `last_pass1`; stop
  stripping it.
- `index.html` — add render logic and CSS.

**Change**
- pull.py: keep `last_pass1` and `last_pass2` in the per-listing output of
  `latest.json`.
- index.html: in `renderTable()` and `renderCards()`, compute
  `daysSinceLastPass1`. If `> 7`, render a small gray pill near the days-
  listed badge: `not seen 12d`. If `> 21`, the pill goes amber.
- Remove the existing DELISTED badge logic (deprecated by this work).

**Acceptance**
- Visit the app. A listing with `last_pass1` 10 days old shows the gray
  pill; one with `last_pass1` from this week does not.
- The DELISTED badge no longer appears for any listing.

**Risk**
- Visual noise if a large fraction of listings are stale. Mitigation:
  threshold is 7d (most of inventory should be < 7d if Pass 1 is healthy).
  If noisy, raise threshold to 10d.

**Effort:** 45 minutes.

---

### W4: Pass 1 coverage strip in app

**Why:** This is the deepest lesson from the incident. The cliff started
2026-04-22 and was not visible until 2026-05-09 — 17 days later, via a
user complaint. A 14-day sparkline in the app would have made it
unmissable on day 2.

**Files**
- `scripts/pull.py` — append a row to `data/pipeline_health.json` on every
  successful run.
- `index.html` — render a small sparkline + 7-day numeric history near the
  existing health-strip.
- `data/pipeline_health.json` — new file, array of last 30 records:
  ```json
  [
    {"date": "2026-05-09", "pass1_count": 421, "active_count": 419, "status": "ok"},
    {"date": "2026-05-08", "pass1_count": 420, "active_count": 418, "status": "ok"},
    ...
  ]
  ```

**Change**
- pull.py: at end of `run_two_pass`, append today's record. Cap file at
  last 30 entries (FIFO).
- pull.py: a record is also written when `mark_delisted` would have run
  (per W2 it doesn't run, but the placeholder is useful for future
  deprecation).
- index.html: fetch `pipeline_health.json` on load, render a 14-day mini
  bar chart (no library — pure SVG, ~30 lines). Click expands a tooltip
  with date + count per day.
- A red flash on any day where `pass1_count < 75% of 7-day rolling median`.

**Acceptance**
- Visit app. The strip shows last 14 days of Pass 1 counts at a glance.
- A synthetic stale day (pass1_count = 100) renders red.
- Replay of 2026-05-05 history (count drops 421 → 181) would have rendered
  the May 5 column red.

**Risk**
- Adds a new JSON file to `data/`; cron must keep it consistent. Mitigation:
  if file missing or corrupt, app shows "history unavailable" — fail-open,
  not fail-closed.

**Effort:** 90 minutes.

---

### W5: Pass 1 coverage cliff guard

**Why:** Defense in depth. W4 makes anomalies visible to the user; W5
prevents bad runs from contaminating `db.json` in the first place.

**Files**
- `scripts/pull.py`
- `.github/workflows/refresh.yml`

**Change**
- pull.py: before merging Pass 1 results into db, read
  `pipeline_health.json`, compute 7-day median of `pass1_count`. Today's
  count vs the median:
  - ≥ 75% of median → proceed normally
  - 50–75% → log warning, proceed with merge but skip any future delete-
    style operations (currently moot post-W2; defensive)
  - < 50% → abort with `sys.exit(1)`. No merge, no save.
- refresh.yml: failed cron runs send the user a GitHub Actions email
  (default behavior; just confirm `notifications: { failures: true }` is
  set on the user's GitHub account).

**Acceptance**
- Synthetic test: run pull.py with a stub Pass 1 returning 50 listings
  while history shows ~370 baseline. Script aborts non-zero, no save.
- Replay test: simulate 2026-04-22's first low day (~180). The guard
  would have fired *that day*, before any 14-day timer ran.

**Risk**
- Legitimate market shifts (e.g., StreetEasy briefly returning fewer
  listings due to genuine inventory drop) trip the guard. Mitigation:
  manual override flag `--force-merge` on pull.py; user can investigate
  and re-run if needed.

**Effort:** 30 minutes.

---

## Phase 3 — Shortlist protection (later, ~2 hours)

### W6: Sticky-shortlist contract + test

**Why:** Codify the rule that user-triaged listings (Shortlist / Archive)
are never modified by automation. The recent incident violated this
implicitly — listings the user had triaged got hidden by a status flag
the user didn't set. Making this an explicit invariant prevents future
violations of the same shape.

**Files**
- `STATUS-FEATURE.md` — add the contract section
- `CLAUDE.md` — link the contract
- `tests/test_sticky_shortlist.py` (new) — small smoke test

**Contract (the words to add)**
> No automated process modifies a Postgres `listing_status` row except via
> explicit user action (UI click, batch import) or auto-resurrection on
> price drop. The cron pipeline writes only to `db.json` and `latest.json`;
> it never touches `listing_status`. Frontend filtering may hide Inbox
> rows based on data flags, but never Shortlist or Archive rows.

**Test**
- Run a full cron cycle against a test DB.
- Assert: no rows in `listing_status_history` were created during the run.

**Acceptance**
- Contract written and linked from CLAUDE.md.
- Test passes locally.

**Effort:** 30 minutes.

---

### W7: Per-Shortlist Pass 2 verification

**Why:** When a shortlisted listing genuinely goes off-market, the user
needs to know — but inferring this from absence is what got us into the
incident. Pass 2's per-listing detail endpoint is authoritative: it
returns either the active listing's data or a "not found" sentinel. We
can use it surgically on Shortlist items only.

**Files**
- `scripts/pull.py` — new function `verify_stale_shortlists(db)`.
- `index.html` — render a distinct badge for confirmed-off-market.

**Change**
- pull.py: at end of each run, fetch `GET /status` from the Postgres API.
  For listings with `bucket=shortlist` AND `last_pass1` > 7d ago, run them
  through Pass 2 detail (`/sale/{id}` or `/rental/{id}`) one at a time.
  - If actor returns active data → update `last_pass2`, leave alone.
  - If actor returns the "no longer available" sentinel → set
    `pass2_confirmed_off_market: true` and `pass2_confirmed_at: <date>`
    on the listing in `db.json`.
- Cap at 20 listings per run (defensive — keeps actor cost predictable;
  Shortlist is small so usually all fit).
- index.html: a listing with `pass2_confirmed_off_market: true` renders a
  distinct badge — `verified off-market` (red, not gray). Different visual
  weight than the soft "not seen 12d" stale pill, because this is a
  confirmed observation.

**Acceptance**
- Force a shortlisted listing's `last_pass1` back 10 days. Run pull.py.
  - If it's actually still on StreetEasy: `last_pass2` updates, no flag set.
  - If it's actually gone: `pass2_confirmed_off_market: true` is set.
- The frontend renders the correct badge in each case.

**Cost**
- 20 Pass 2 calls per run × ~$0.003 = $0.06 / run. Trivial.

**Risk**
- Actor's Pass 2 endpoint has known reliability issues (memo23 patches
  ongoing per CLAUDE.md). Mitigation: failures leave the listing in
  current state; retry on next run; never auto-flag from a Pass 2 failure.

**Effort:** 60 minutes.

---

## Sequencing & dependencies

```
Phase 1: W1 ──┐
              ├── (single commit) ── deploy ── verify
        W2 ──┘

Phase 2: W3 ── independent
         W4 ──┐
              ├── deploy together
         W5 ──┘ (W5 depends on W4's pipeline_health.json)

Phase 3: W6 ── independent
         W7 ── independent
```

W1 and W2 ship together because the verification of W2 (no DELISTED badges
appear) needs W1 in place to repopulate Pass 1 with the previously-missing
co-ops. Otherwise the Inbox stays small for unrelated reasons and the test
is uninformative.

W4 must precede W5 — the cliff guard reads from
`pipeline_health.json`, which W4 introduces.

## Rollout per phase

1. Develop locally.
2. Run `pull.py --dry-run` to validate (no writes).
3. Push via `scripts/git_push.py` (never `git push` from sandbox per
   CLAUDE.md rules).
4. Either wait for next 09:00 UTC cron OR trigger workflow manually via
   GitHub UI.
5. Verify the phase's acceptance criteria.
6. Update CLAUDE.md to reflect new state.
7. Update CHANGELOG.md.

## Rollback

- **W1**: revert the URL constants. No data change in `db.json` from URL
  alone, so revert is clean.
- **W2**: re-call `mark_delisted()`. But also: don't, until W7 is in
  place. Do nothing — leaving auto-delist disabled is the safe state.
- **W3**: revert index.html and `generate_latest()` change. No persistent
  state.
- **W4**: delete `data/pipeline_health.json`. App falls back to "history
  unavailable" (W4 builds in this fail-open).
- **W5**: comment out the guard in pull.py. No persistent state.
- **W6**: doc-only; no rollback needed.
- **W7**: revert `verify_stale_shortlists()` call. The
  `pass2_confirmed_off_market` field on individual listings can stay —
  benign if unused.

## Definition of done for the plan

After all 7 work items ship, the following must be true:

- [ ] No listings can be auto-flagged delisted (W2).
- [ ] User sees Pass-1 coverage history every time they open the app (W4).
- [ ] A Pass-1 cliff aborts the cron run on day 1, not day 14 (W5).
- [ ] Shortlisted listings retain their Postgres status regardless of
      what the cron pipeline does (W6 contract + test).
- [ ] Truly off-market shortlisted listings get a *verified* off-market
      badge from Pass 2, not an inferred one (W7).
- [ ] The 2026-04-22 incident, if replayed against the new system, is
      caught the same day, never reaches `db.json`, and produces an
      actionable signal in the app rather than silent data loss.

That last item is the real test — and it's what would have saved the user
8 days of false-flag confusion this past week.

## Out-of-scope items captured here for future sessions

- Recommendation D (broader pull + app-side filter): see Non-goals above.
- Auto-detection of relisted listings (different problem; partly handled
  by re-listing icons already in the app).
- A relisting/re-pricing alert digest (PRODUCT-BACKLOG.md item).
- Any other PRODUCT-BACKLOG.md items.

## Estimated total effort

| Phase | Items | Effort |
|---|---|---|
| 1 | W1, W2 | 30 min |
| 2 | W3, W4, W5 | 165 min (~2h45m) |
| 3 | W6, W7 | 90 min (~1h30m) |
| **Total** | | **~4h45m of focused work** |

Phase 1 is the only urgent work. Phases 2 and 3 can be paced over the
next 1–2 weeks.
