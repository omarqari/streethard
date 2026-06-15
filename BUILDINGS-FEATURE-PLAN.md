# BUILDINGS-FEATURE-PLAN.md

Feature: a family-facing **Buildings** view where Omar/Rabia mark the buildings
they consider great targets, and listings in those buildings get a special
highlight everywhere in the main app (Inbox / Shortlist / Archive).

Status: **SHIPPED (Session 44, 2026-06-15).** Live and verified on all four
highlight surfaces. See CHANGELOG 2026-06-15 for the build record.

Decisions locked (Session 44):
- Storage: **backend-shared** (Railway Postgres).
- Highlight: **subtle** — orange left border + warm `#FFF8F2` tint + "★ Target"
  pill, as mocked.
- **A. One shared family target list** (not per-person). No `targeted_by`
  column needed.
- **B. Target from the Buildings tab only.** The main-app listing highlight is
  **read-only** — no per-row star.
- **C. Highlight only.** No new-listing count badge, no freshness-banner change.
- **D. Conservative key normalization** (5 known spelling merges; never strip
  Street/Avenue/Place).
- **E. Persist zero-listing targets** (a building keeps its target even when it
  has no active listings).
- Non-goal (CPO call, confirmed): targeting does **not** auto-resurface Archived
  listings to Inbox — they stay archived, just highlighted in place.
- Binary star (no tiers).

---

## 1. Problem & intent

Omar evaluates apartments, but a huge part of the buy decision is the
*building*, not the unit: pre-war vs post-war, co-op board reputation,
land-lease risk, financial health, location on the block. He already forms
strong opinions like "530 Park is a great building." Today that judgment lives
in his head and has to be re-applied mentally every time a listing scrolls by.

The feature externalizes that judgment once, at the building level, and then
surfaces it automatically on every listing in that building — so a new Inbox
listing in a loved building visually announces itself, and a buried Archive
listing he down-ranked on unit grounds still reads "but this is a great
building."

Calibration (per CLAUDE.md): n=1 personal purchase. ~327 buildings, 121 with
multiple listings. This is a lightweight annotation layer, not a building-data
product. No PLUTO/ACRIS building enrichment in scope.

## 2. Data model — how listings become "buildings"

There is **no building ID** in the data. Every listing has a `building` string
(e.g. `"530 Park Avenue"`), populated on 514/514 listings. `building_name` and
`building_id` are always null. So the building string is the only join key, and
it has spelling drift.

### 2.1 `buildingKey()` normalizer (the crux)

A pure function mapping a `building` string → a stable canonical key. Used both
to aggregate listings into building rows and as the primary key for the
target store, so a target survives spelling variants.

**Conservative transforms only** (the validated-safe set):
- lowercase, collapse whitespace, trim
- spelled ordinals → digits: `fifth→5th`, `third→3rd`, `second→2nd`, `first→1st`
- expand/standardize: `park` alone → `park avenue` (covers `"920 Park"` =
  `"920 Park Avenue"`)
- normalize directionals: `east→e`, `west→w`
- strip punctuation

**Explicitly NOT done:** stripping the street-type suffix (`street`, `avenue`,
`place`). Stripping it risks false merges like `45 E 66th Street` ↔
`45 E 66th Place`. We keep the suffix; we only normalize its spelling.

Validation on current data: the 5 known near-dup groups collapse correctly
(`875 Fifth Avenue`=`875 5th Avenue`, `1050/1025/870 Fifth`, `920 Park`).
Distinct keys drop 327 → 322. A unit test asserts each known pair maps equal
AND asserts two deliberately-different addresses on the same block map unequal.

`display_name`: the prettiest variant seen for a key (longest/most-complete
string, e.g. prefer `"920 Park Avenue"` over `"920 Park"`). Stored alongside
the key so the UI shows a clean label.

### 2.2 Building aggregation (client-side, from `latest.json`)

`buildBuildingIndex(listings)` groups active listings by `buildingKey()` and
computes per building:
- `display_name`, `neighborhood` (most common non-empty), `year_built`
  (most common), `type` (most common: coop/condo/house)
- `count`, `count_sale`, `count_rent`
- `price_min`, `price_max` (sale listings)
- `psf_median` (sale listings with real sqft; estimated-sqft listings flagged)
- `listing_ids[]` and their current buckets (for the expand panel)
- `targeted` (from the target store)

Buildings with **zero current listings** but an existing target row are still
shown on the Buildings tab (state: "no active listings right now") so a target
is never silently lost when a building's last listing delists. [DECISION E]

## 3. Backend — `building_targets`

Reuses the live FastAPI + asyncpg + Railway Postgres service. No auth; CORS
restricted to `streethard.omarqari.com`, identical to existing endpoints.

### 3.1 Table (added to `api/schema.sql`)

```sql
CREATE TABLE IF NOT EXISTS building_targets (
    building_key  TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL DEFAULT '',
    note          TEXT NOT NULL DEFAULT '',
    targeted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_building_targets_updated
    ON building_targets (updated_at DESC);
```

One shared list [A] → no `targeted_by` column. Must survive the cold-start
migration splitter in `api/main.py`, which splits on `;` while toggling in/out
of `$$` blocks. Plain `CREATE TABLE` / `CREATE INDEX` statements ending in `;`
are safe; no `DO $$` block needed.

### 3.2 Endpoints (added to `api/main.py`)

- `GET /building-targets` → `{ "items": [ {building_key, display_name,
  targeted_by, note, targeted_at} ... ] }`. `Cache-Control: no-store`, mirrors
  `GET /status`.
- `PUT /building-targets/{building_key}` — upsert/toggle. Body:
  `{ targeted: bool, display_name?, note?, targeted_by? }`. When
  `targeted:false`, **DELETE the row** (target list stays small and clean;
  consistent with how a star is a binary). Returns the row (or `{deleted:true}`).
- (optional) `POST /building-targets/batch` — only if we later want bulk ops.
  Not needed for v1; a star is one click = one PUT.

No trigger / audit table for targets (unlike `listing_status`); targeting is
low-stakes and reversible, an audit log is over-engineering here.

## 4. Frontend — `index.html`

### 4.1 Third fetch on load

`loadData()` currently does `Promise.all([fetch(latest.json), loadStatus()])`.
Add `loadBuildingTargets()` → populates `targetSet` (a `Set` of building_key)
and `targetMeta` (key → {display_name, note}). Tolerates failure exactly like
`loadStatus()` (app still works if the API is down; nothing highlighted).

### 4.2 The Buildings tab

A 4th top-level tab, but **right-aligned and set off by a thin divider** from
the three listing buckets (a building icon on it too), so Inbox/Shortlist/Archive
read as one left-to-right triage flow and Buildings reads as a separate view —
reinforcing that it is not a fourth bucket. Implementation: a `flex:1` spacer +
a 1px divider before `#tab-buildings` in the tab row. Because it renders
*buildings* not *listings*, it is NOT a `currentBucket` value routed through
`renderTable/renderCards`. Instead:

- introduce `currentTab` ∈ {`inbox`,`shortlist`,`archive`,`buildings`}; the
  three listing tabs keep driving `currentBucket` and the existing render path;
  `buildings` swaps in a separate `#buildings-view` container and calls
  `renderBuildings()`.
- hash routing extended: `#buildings` allowed (currently only the 3 buckets).
- the existing filter bar (beds/type/price/monthly) is listing-specific; on the
  Buildings tab it is replaced by a building-appropriate bar: text search +
  "Only targets" toggle + a sale/rent/both nicety is unnecessary (buildings
  span both).

`renderBuildings()` draws the table from `buildBuildingIndex()`:
columns ★ | Building (+ neighborhood subline) | Built | Type | Listings
(sale·rent) | Price range | $/ft² (median). Default sort: targeted first, then
`count` desc. Click a row → expand to the building's units (address/unit,
price, current bucket chip, link to StreetEasy and/or jump to the listing).

Star click → optimistic toggle of `targetSet` + `PUT /building-targets/{key}`,
re-render. Mirrors the optimistic pattern already used by `transitionBucket` /
`toggleSeen`.

### 4.3 The highlight (main app, all buckets)

A pure helper `isTargetBuilding(listing)` = `targetSet.has(buildingKey(listing.building))`.

- **Table** (`renderTable`, ~line 2276): when true, add class `target-bldg` to
  the `<tr>` → CSS `border-left:3px solid #FF6000; background:#FFF8F2;` and
  inject the `★ Target` pill next to the building name cell.
- **Cards** (`renderCards`, v4, ~line 2456): same `target-bldg` class on
  `.listing-card.v4` → left border + tint; pill in `.v4-header` badge row next
  to the type/days/built badges.
- Independent of bucket. No change to `calcMonthlyTotal`, sort, or bucket logic.
- **Read-only in the main app [B].** The pill is display-only; targeting is done
  on the Buildings tab. No per-row star, no listing-row write path.
- **No new-listing signal [C].** New target-building listings simply appear
  highlighted in Inbox; no count badge or banner change.

## 5. Build order (after sign-off)

Bottom-up, per the project's validation rule:
1. `buildingKey()` + unit test (known dup pairs equal; near-miss pairs unequal)
   — validate in isolation before anything depends on it.
2. Backend: add table to `schema.sql`, add 2 endpoints, deploy to Railway,
   curl-verify `GET`/`PUT`/un-target round-trips against the live DB.
3. Frontend: `loadBuildingTargets()` + `targetSet`; verify GET merges on load.
4. Buildings tab: `renderBuildings()` + tab wiring + hash route. Verify
   aggregation counts/ranges against a hand-checked building.
5. Highlight: `isTargetBuilding` + table + card treatment. Verify a single
   targeted building lights up in Inbox AND Shortlist AND Archive, table + card.
6. Push via `mcp__github__push_files` (per CLAUDE.md git rules). Pages
   auto-deploys.

## 6. Verification checklist

- `buildingKey()` unit test passes (5 known dup groups merge; control pairs stay
  distinct).
- Targeting `530 Park Avenue` highlights every 530 Park listing regardless of
  bucket, in both table and card views, on desktop and mobile width.
- Un-targeting removes the highlight and deletes the DB row.
- A target on a building with no current listings still appears on the Buildings
  tab and is not lost across a data refresh.
- Cron / `pull.py` / mortgage math untouched (diff is additive only).
- API down → app still loads, nothing highlighted, no console errors.
- Cross-device: target set fetched from backend appears on a second browser.

## 7. Risks & non-goals

- **Over/under-merge of building keys.** Mitigated by conservative normalization
  + unit test. Residual variants beyond the known 5 will simply show as separate
  building rows (under-merge) — visible and harmless, never a false merge.
- **`building_key` drift if normalizer changes later.** A future change to
  `buildingKey()` would orphan existing target rows. Mitigation: the key
  algorithm is frozen with the unit test; any change ships with a one-time
  re-key migration. Documented here so a future session doesn't silently break
  targets.
- **Scope creep into building data.** Out of scope: pulling PLUTO/ACRIS
  building facts, board-financials, land-lease flags. This feature is purely the
  family's own judgment layer.
- **Operator vs family.** This is deliberately family-facing (main app), per the
  audience-split rule — it's Omar/Rabia's judgment, not an ops diagnostic.

## 8. Decisions — RESOLVED

All resolved Session 44; see the locked list at the top. A = one shared list;
B = Buildings tab only (main-app highlight read-only); C = highlight only;
D = conservative normalization; E = persist zero-listing targets; plus binary
star and no auto-resurface from Archive. Plan is ready to build on final go.
