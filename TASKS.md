# TASKS

Actionable next steps. Check things off as you go.

---

## ✅ Completed

- [x] Validate RapidAPI NYC Real Estate API — YELLOW. Good for detail lookups; no price history or agent contact; 25 req/mo free tier too tight for bulk.
- [x] Validate Apify `memo23/streeteasy-ppr` — GREEN. Full price history, agent contact, all required fields. $0.009/listing.
- [x] Lock mortgage calculator defaults: $750k down, 3.00%, 30 years.
- [x] Define output schema: Building, Street, Apt, Yr Built, Monthly Pmt, SqFt, Price/SqFt, PMT/SqFt, Days Listed, Type.
- [x] Define search criteria: UES, sqft ≥ 1,500, price ≤ $6,000,000, active only.
- [x] Decide output format: StreetHard HTML app (not spreadsheet).
- [x] Decide architecture: GitHub Pages (static) + GitHub Actions (weekly cron) + client-side JS mortgage math.

---

## Next Up — Phase 2, Step 1: Build `index.html`

Build the StreetHard app shell. No real data yet — use hardcoded sample JSON (2–3 listings) to build and validate the UI.

- [ ] Create `index.html` — full app shell:
  - Dark navy header, "StreetHard" wordmark, UES context tag, last-updated date
  - **Sticky mortgage calculator bar** directly below header (always visible while scrolling): Down Payment · Rate · Term — defaults: $750k / 3.00% / 30yr. Any change recalculates all rows instantly.
  - **v1 is desktop-only. Mobile responsiveness is deferred to v2.**
  - Summary bar: median ask, median monthly, condo/co-op count, new-this-week count
  - Filter bar: Beds (All/2+/3+/4+), Type (All/Condo/Co-op), Max Price, Max Monthly Pmt
  - Table view (default): sortable columns, default sort Monthly Pmt descending
  - Card view toggle
  - Row expansion (click to open inline): price history table, "never sold" warning badge, agent contact block, payment breakdown (mortgage + charges + taxes)
  - Days Listed color coding: NEW/blue (<7d), green (7–44d), yellow (45–120d), red (121d+)
  - Footer: data source credit + generation date + run cost
- [ ] On load: `fetch('data/latest.json')` → render; show graceful loading state
- [ ] Mortgage inputs: any change instantly recalculates and re-sorts all rows in-place
- [ ] Null field handling: show "—" for missing values; show "data incomplete" badge if multiple key fields are null

---

## Next Up — Phase 2, Step 2: Build `scripts/pull.py`

- [ ] Write `scripts/pull.py`:
  - Reads Apify token from environment variable `APIFY_TOKEN`
  - Calls Apify `memo23/streeteasy-ppr` with the configured start URL and `maxItems`
  - Polls for run completion
  - Downloads results as JSON
  - Saves to `data/latest.json` (overwrite) and `data/YYYY-MM-DD.json` (new file)
  - Prints summary: listing count, run cost estimate, any nulls on key fields

---

## Next Up — Phase 2, Step 3: First Real Pull (v1 Test)

**Test search URL** (UES, price $2.5M–$4M, sqft ≥ 1,500):
```
https://streeteasy.com/for-sale/upper-east-side/price:2500000-4000000%7Csqft:1500-
```

- [ ] Run `pull.py` with the test URL. `maxItems: 500`.
- [ ] Confirm price and sqft filters are respected in results; apply post-processing filter as backup.
- [ ] Validate pagination: did we get all listings, or just page 1?
- [ ] Validate field coverage: do bulk search results include maintenance fee, taxes, price history, agent contact — or only individual listing page scrapes?
- [ ] Open `index.html` locally, confirm it renders all listings correctly with calculated monthly payments.

---

## Next Up — Phase 2, Step 4: GitHub Setup

- [ ] Create GitHub repo `streethard` (public or private — data is all public, no sensitive info)
- [ ] Push `index.html`, `scripts/pull.py`, `data/latest.json`, `data/YYYY-MM-DD.json`
- [ ] Enable GitHub Pages (source: root of `main` branch)
- [ ] Add Apify token as GitHub Secret: `APIFY_TOKEN`
- [ ] Create `.github/workflows/refresh.yml`:
  - Trigger: weekly cron (Sunday) + manual `workflow_dispatch`
  - Steps: checkout → set up Python → run `pull.py` → commit + push updated `data/` files
  - **Guard**: `pull.py` exits with code 1 if listing count < 10; workflow fails without overwriting `data/latest.json`
- [ ] Confirm end-to-end: Actions run → JSON committed → Pages redeploys → family URL live
- [ ] Share URL with family

---

## Recurring (While Searching)

- [ ] Weekly: GitHub Actions auto-runs the pull. Verify output after each run.
- [ ] Per serious candidate: run the 15-minute due diligence checklist.
- [ ] Monthly: cross-check StreetEasy and CitySnap saved searches for anything the API missed.

---

## Housekeeping

- [ ] Rotate the RapidAPI key — shared in earlier Chat session snippets. Regenerate on RapidAPI dashboard.
- [ ] Add `.env` to `.gitignore` — never commit API keys.
- [ ] Bookmark manual due diligence tools:
  - ZoLa: `zola.planning.nyc.gov`
  - HPD Online: `hpdonline.hpdnyc.org`
  - DOB NOW: `a810-dobnow.nyc.gov`

---

## Phase 2 Enhancements (Post-v1)

- [ ] **New/reduced badges:** Compare current pull against previous `data/YYYY-MM-DD.json` to surface new listings and price cuts with visual badges in the app.
- [ ] **Rental comp analysis:** Add UES rental data alongside PMT/SqFt column for buy-vs-rent comparison.
- [ ] **Co-op sqft gap:** Evaluate supplemental pull for co-ops without sqft filter; flag those listings separately.

---

## Before Making an Offer

- [ ] Engage a real estate attorney (non-optional in NY).
- [ ] Request full offering plan from broker.
- [ ] Request last 2 years of building financial statements.
- [ ] Review: reserve fund level, outstanding loans, pending assessments, major capital projects.
- [ ] For co-ops: confirm flip tax, sublet policy, pet policy, board package requirements.
- [ ] Schedule inspector (especially pre-war, recent renovations, or lower floors).
- [ ] Run ACRIS one more time for unusual transfers or liens (condos only).

---

## Open Questions

- [ ] Co-ops, condos, or both? Changes due diligence stack significantly.
- [ ] School-zone constraint?
- [ ] Financing pre-approval in place, or still to do?
