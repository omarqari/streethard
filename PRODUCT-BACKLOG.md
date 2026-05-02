# PRODUCT-BACKLOG.md

CPO slate of product improvements for StreetHard, organized by theme. Created
Session 17 (2026-05-02) from a CPO review of CLAUDE.md, PROJECTPLAN.md,
TASKS.md, CHANGELOG.md, RETRO-SESSION9.md, SQFT-METHODOLOGY.md,
STATUS-FEATURE.md, STATUS-BACKEND-WALKTHROUGH.md, `index.html`, and
`scripts/pull.py`.

This file is for **proposed product work the user has not yet committed to.**
Once an item is selected, it moves to TASKS.md (in-flight) and the entry
here is updated with status `accepted`. Items that extend or relate to work
already in TASKS.md are flagged so the conversation about whether to accept
them is informed.

## How to read this

- **Effort:** S (~1 session), M (1–2 sessions), L (3+ sessions)
- **Status:** `proposed` (default), `accepted`, `deferred`, `superseded`,
  `extends:<task>` (sharpens an item already in TASKS.md), or
  `relates:<task>` (different mechanic, similar goal).
- Themes are ordered by user-impact, but cross-theme dependencies are called
  out per item.
- All items are calibrated for n=1 personal purchase. None requires a
  commercial API, none scrapes StreetEasy directly, all engineering effort is
  proportional to a single buy decision.

---

## Theme 1 — Decision Quality

Improves the actual buy decision, not just the listing display.

### 1. Rent-vs-Buy Breakeven Card  *(S, proposed)*

Per sale listing, compute years-to-breakeven against the median monthly cost
of comparable rentals (UES, ±20% sqft, ±1BR matching). Renders as one line in
the row expansion: *"Breakeven vs renting comparable units: 6.4 years."*

**Why for this user:** Rentals are already in `db.json` and underused. Turns
"should we buy at all" from a gut call into a per-candidate number. Most
useful for marginal cases ($3M condo with $4k fees vs. $13k/mo rental).

**Deps/risks:** Needs sale↔rental matching logic (size, beds, neighborhood
band). No new ingestion. Mortgage defaults already locked in CLAUDE.md.

### 2. Price-per-Bedroom + Monthly-per-Bedroom columns  *(S, proposed)*

Two new sortable columns: `$/BR` and `Monthly/BR`. Toggle in column-picker
or always-on.

**Why for this user:** $/sqft penalizes layout-efficient apartments; for a
*family* search where the bar is ≥2BR, "cost to house each kid" is closer to
real utility than $/sqft. Especially relevant for co-ops where sqft is
estimated and noisy.

**Deps/risks:** None. Pure client-side derivation.

### 3. Price-History Signal Score  *(S, relates:v1.5-RECONSIDER-pill)*

Per-listing icons derived from `price_history`: *2x cut · re-listed ·
peaked-then-fell · stale-3mo+ · off-market-and-back*. Add a "has price cuts"
filter in the filter bar.

**Why for this user:** Distinguishes "fairly priced from day one" from
"third try at selling, finally negotiable" — different negotiating posture
for the same listing.

**Relationship to v1.5 RECONSIDER pill** (TASKS.md):
The v1.5 RECONSIDER feature compares current price against
`price_at_watch` (the price at the moment a listing was bookmarked) and
fires only on the watched subset. This proposal is broader: derives signals
purely from `price_history` for *every* listing, with no watch dependency.
The two are complementary rather than competing — RECONSIDER answers "did
the price drop since I started watching?", this answers "what's the listing's
price-history posture overall?".

**Deps/risks:** None. Pure JS over existing field.

### 4. Comp Sheet PDF (per shortlisted candidate)  *(M, proposed)*

One-pager PDF generator: listing snapshot + mortgage breakdown + full price
history + 3 nearest ACRIS condo comps + 3 nearest active rentals + DD
checklist state. Click-to-export from the row expansion.

**Why for this user:** When seriously looking at one apartment, this is the
artifact actually needed — to email a parent, hand to the attorney, or sit
next to the offer math. Replaces the screenshot-and-paste workflow.

**Deps/risks:** Best after #6 (ACRIS overlay) lands. Probably wants the
status feature's notes/chips data on it too; depends on v1 status backend
landing first.

---

## Theme 2 — Data Quality / Completeness

### 5. PLUTO BBL Enrichment  *(M, proposed)*

One-time download of Manhattan PLUTO; fuzzy-join by address to the listings
in `db.json`; cache `bbl`, `building_class`, `total_units`, `gross_bldg_area`,
`lot_area` per listing.

**Why for this user:** Single feature with multiple downstream payoffs —
unlocks #6 (ACRIS overlay), #13 (DD quicklinks with BBL), and a future
Building Roll-up View. Free, authoritative, one-time work.

**Deps/risks:** Address normalization is the hard part — PLUTO uses
`123 EAST 75 STREET`, listings use `123 East 75th Street`. Co-op buildings
collapse cleanly; condo buildings get one BBL per complex per CLAUDE.md.
Geocoding miss rate is the unknown to budget for.

### 6. ACRIS Condo Comp Overlay  *(M, proposed)*

For each condo listing, query Socrata ACRIS for last-24-months sales in that
BBL. Show as "Recent sales in this building" mini-table in the row expansion:
date, unit (where parsable), sale price, $/sqft.

**Why for this user:** This is the negotiation data set. *"Asking
$1,650/sqft, but 3 closings in this building in the last year were
$1,420–$1,510"* is the exact leverage that StreetEasy's UI doesn't surface
cleanly. Free API, no commercial license.

**Deps/risks:** Depends on #5 (BBL). Co-ops invisible by design (per
CLAUDE.md NYC gotchas) — feature is condo-only and the UI must handle that
gracefully.

### 7. Floor Plan Surfacing in App  *(S–M, proposed)*

Move the floor plans from gitignored `/floorplans/` into the app: row
expansion shows the plan inline for any listing flagged
`sqft_estimated: true`, with a tooltip pointing at the calibration room.

**Why for this user:** 15 co-ops have already been measured (Sessions
10–11). That work is currently invisible to family members browsing the app.
Surfacing the plan + calibration story makes the gray $/sqft numbers
trustworthy without anyone needing to read SQFT-METHODOLOGY.md.

**Deps/risks:** Need to commit floor plan images (currently gitignored).
Page weight grows; lazy-load on row expand. Verify image licensing before
publishing — most StreetEasy plans are listing-broker artifacts; usage in a
private family tool is fine but should be confirmed before any external
share.

---

## Theme 3 — UX & Scannability

### 8. Compare Pane (pin 2–4 listings)  *(S, proposed)*

Pin a row → pin another → side-by-side comparison strip at the bottom of the
page. Stats stacked: monthly, $/sqft, fees, taxes, days listed, last cut,
status pill.

**Why for this user:** This is the actual decision moment — *"are we leaning
Saratoga or 530 Park?"* The Status Feature handles persistent state
(watching/shortlisted/etc.); Compare handles the *comparison conversation*.
Doesn't need any backend; pure client-side.

**Deps/risks:** None. Plays nicely alongside the status backend.

### 9. Saved Views via URL state  *(S, relates:v1.5-Saved-filter-tabs)*

Encode all filter state in the querystring. *"3BR+ condo under $4M sorted by
$/sqft"* becomes a copy-paste link. Family members open the link and land on
the same filtered view.

**Why for this user:** Replaces "go to the app, then click these 4 things"
instructions to family. Zero backend, zero auth.

**Relationship to v1.5 Saved-filter tabs** (TASKS.md):
v1.5 plans `All / Active / Toured / Watching / Offered` tabs above the
table — fixed, status-driven, top-level navigation. URL-encoded state is
orthogonal: a *shareable snapshot* of any filter combo. The two coexist
naturally; tabs cover routine views, URL-state covers ad-hoc sharing.

**Deps/risks:** None. Purely client-side.

### 10. Map View Toggle  *(M, proposed)*

Leaflet pins per listing, color-coded by $/sqft (or by Monthly Pmt). Click
pin → row expands inline.

**Why for this user:** Park Ave vs. east of 1st Ave is a $300–500/sqft
difference for the same beds. Map exposes it instantly; the table buries
it. Especially useful for "we don't actually want anything east of 2nd"
constraints surfaced by a family conversation.

**Deps/risks:** Needs lat/lng — verify Apify gives it on every record before
committing. Adds ~30KB JS (Leaflet). OpenStreetMap tiles are free; Mapbox
adds a key.

---

## Theme 4 — Signal & Noise

### 11. Activity Digest (weekly markdown commit)  *(S, proposed)*

Each cron run also writes `data/digest-YYYY-MM-DD.md`: new listings, price
cuts, delistings, top movers. Committed alongside the JSON. Read on GitHub
mobile before Monday morning.

**Why for this user:** Right now there's no nudge — you have to actively
open the app to know if anything changed. A digest committed to the repo
turns the pipeline from pull to push (GitHub mobile notifications, free).
Best done alongside the in-flight new/reduced badge work — they share the
diff logic.

**Deps/risks:** Best built alongside the new/reduced badge work in TASKS.md
to avoid duplicating the diff implementation.

### 12. In-App Pipeline Health Strip  *(S, extends:Pipeline-health-assertion)*

Small status strip at the top of `index.html`:
*"Last refresh: 3d ago • 419 listings (373 complete · 46 partial) • Oldest
listed_date: 12d behind today."* Goes red if stale.

**Why for this user:** This is the silent-failure mode that hit on Apr 23,
27, 30 (cron green, data frozen — see CHANGELOG Session 12). Putting the
assertion in the family-facing UI means anyone in the family sees "data is
stale" before they trust the prices. The TASKS.md item ("Add a pipeline
health assertion") covers the CI side (fail the run when max(listed_date)
is too far behind); this proposal adds the user-visible side.

**Deps/risks:** None. Reads existing fields. Implement after the CI
assertion lands so they share a definition of "stale."

---

## Theme 5 — Due Diligence Integration

### 13. Per-Listing DD Quicklinks  *(S, proposed)*

Row expansion gets a button row: *ZoLa · HPD · DOB NOW · ACRIS · Google
Street View*. Each link prefilled with the listing's BBL or address.

**Why for this user:** The 15-minute DD checklist in PROJECTPLAN is real,
recurring work. Making each lookup one click saves ~5 minutes per candidate
× however many candidates × however many family members run the same
checks. Trivial to build, compounds nicely. Pairs with the Status Feature's
notes field — DD findings get captured per-listing.

**Deps/risks:** ZoLa and ACRIS are best with BBL (so depends on #5). Falls
back to address search without BBL — still useful but less precise.

---

## Theme 6 — Automation & Reliability

### 14. Diversify the Cron Slot  *(S, relates:Memo23-follow-up)*

Split `refresh.yml` into two crons (e.g., 13:00 + 21:00 UTC), keep
first-success-wins logic. The 09:00 UTC slot has been the systematically
blocked one per Session 12 analysis.

**Why for this user:** Trusting the data; data has been silently stale for
12-day stretches. Switching off the bad time-of-day window is the cheapest
available fix while memo23 sorts the proxy issue. Maintenance pulls are
~$0.05–$0.15/run, so doubling is negligible (~$1–$2/month).

**Relationship to in-flight work:**
- *"Watch Mon's 09:00 UTC cron (2026-05-04)"* (TASKS.md) — wait for that
  signal first. If memo23 fixes the proxy at the source, this proposal
  becomes unnecessary.
- *"Memo23 follow-up"* (TASKS.md) — same. Diversifying the slot is the
  fallback if memo23 can't or won't fix it.

**Deps/risks:** Doubles Apify spend slightly. Skip if memo23 fixes the
proxy at the source. The clean way to evaluate: pick this up only after
the next scheduled cron's outcome is known.

---

## Superseded Proposals

The following proposal was put forward in the initial CPO slate but is
superseded by work already in flight. Recorded here for traceability.

### ~~15. Listing-Watch List (localStorage-only)~~ — *superseded*

**Status:** `superseded` by the Listing Status Tracking backend migration
(Sessions 13–16 in TASKS.md and STATUS-FEATURE.md / STATUS-BACKEND-
WALKTHROUGH.md).

**Why dropped:** The Status Feature delivers everything this proposal
would have (mark/reject/dismiss listings, persist across visits) and adds
cross-device sync, family-shared state, watch bookmarks independent of
status, notes, chips, and offline outbox. Building a transient localStorage
version *first* would create a migration headache later. The backend is
already designed; ship that path instead.

---

## Open Decisions (Awaiting User Selection)

The user reviewed this slate on 2026-05-02 and has not yet selected which
items to pursue. Pending decisions:

1. **Which proposals to accept into TASKS.md.** All 14 active proposals
   above (1–14) are awaiting accept/defer. CPO recommendation:
   - **Quick-wins slate (3 × S):** #1 Rent-vs-Buy, #8 Compare Pane,
     #12 Pipeline Health Strip. Each closes a real gap, no
     dependencies between them.
   - **Negotiation-data slate:** #5 PLUTO → #6 ACRIS Overlay → #13 DD
     Quicklinks → #4 Comp Sheet PDF. Each builds on the prior; end state
     is something an attorney could review with you. ~M-L total.

2. **Floor plan licensing for #7.** Are floor plan images from Compass /
   StreetEasy listings OK to commit to a public GitHub Pages repo, given
   the app is private-but-publicly-served? If not, the implementation
   has to either (a) keep plans on a private host and authenticate via
   the Status Feature API, or (b) defer #7 until that's worked out.

3. **#14 Cron diversification — wait or act?** Don't decide until the
   Mon 2026-05-04 09:00 UTC cron outcome is in. If sentinel-fail, accept
   #14 and post the memo23 follow-up. If healthy, defer #14 indefinitely.

4. **#3 Price-history signal score — does it overlap usefully or
   confusingly with the v1.5 RECONSIDER pill?** Decide whether to ship
   them together (different surfaces, different triggers — they don't
   visually compete) or pick one. CPO leans toward shipping both —
   RECONSIDER is for watched listings; signal score is universal triage
   noise.

5. **#9 Saved Views — replace or coexist with v1.5 Saved-filter tabs?**
   CPO recommends coexist (tabs for routine views, URL-state for ad-hoc
   sharing). User to confirm before either lands.

These open decisions are also tracked in TASKS.md under
*"Open Questions → Product backlog (Session 17)"* so they stay visible
day-to-day.
