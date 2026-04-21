# TASKS

Actionable next steps. Check things off as you go.

---

## ✅ Completed

- [x] Validate RapidAPI NYC Real Estate API — YELLOW. Good for detail lookups; no price history or agent contact; 25 req/mo free tier too tight for bulk.
- [x] Validate Apify `memo23/streeteasy-ppr` — GREEN. Full price history, agent contact, all required fields. $0.009/listing.
- [x] Lock mortgage calculator defaults: $750k down, 3.00%, 30 years.
- [x] Define output schema: Building, Street, Apt, Yr Built, Monthly Pmt, SqFt, Price/SqFt, PMT/SqFt, Days Listed, Type.
- [x] Define search criteria: UES, sqft ≥ 1,500, price $2M–$5M, active only.
- [x] Decide output format: StreetHard HTML app (not spreadsheet).
- [x] Decide architecture: GitHub Pages (static) + GitHub Actions (weekly cron) + client-side JS mortgage math.
- [x] Build `index.html` — full app shell with table/card views, sticky mortgage calculator, filters, row expansion, price history, agent info, payment breakdown.
- [x] Build `scripts/pull.py` — two-pass Apify scraper with Pass 1 fallback, guard clause (exit 1 if < 10 listings), debug output, full schema for federated GraphQL field names.
- [x] Debug and fix Pass 2 normalization — rewrote `normalize()` with actual `saleListingDetailsFederated_*` / `saleDetailsToCombineWithFederated_*` / `extraListingDetails_*` field mappings. 50/50 listings normalized on first successful run.
- [x] Set production search URL: `https://streeteasy.com/for-sale/upper-east-side/price:2000000-5000000%7Csqft:1500-`
- [x] GitHub repo live (`github.com/omarqari/streethard`), Pages enabled, `APIFY_TOKEN` secret set.
- [x] Weekly cron verified end-to-end: Actions run → JSON committed → Pages redeploys → family URL live.

---

---

## Recurring (While Searching)

- [ ] Mon + Thu: GitHub Actions auto-runs the pull. Verify output after each run.
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

## ✅ All Blockers Resolved

Pass 1 (search), Pass 2 (detail pages), and the incremental pipeline are all operational as of Session 8 (2026-04-20). Full Pass 2 backfill completed Session 9 (2026-04-21) — 373/373 listings at pass2 quality.

---

## Phase 2 Enhancements (Post-v1)

- [x] **Rental comp analysis:** Added UES rental listings ($10K–$20K/mo). Mode toggle (For Sale / For Rent / Both) added to app. Pipeline pulls both types in one run.
- [x] **Pass 1 ID extraction fix:** Fixed — `item['id']` works; `urlPath` used for Pass 2 URLs; `flattenDatasetItems: True` added.
- [x] **Pass 2 — fixed 2026-04-20:** memo23 pushed a fix. Validation test passed.
- [x] **Incremental pipeline (2026-04-20):** `data/db.json` canonical store. Pass 2 only fills what's missing, capped at 30/run. Abort+salvage on timeout. Delisting detection at 14 days. Full architecture in PROJECTPLAN.md.
- [x] **Rental normalize() validation:** `normalize_rental()` rewritten with verified `combineData_rental_*` schema.
- [x] **Text search (2026-04-20):** Free-text search bar in filter bar. Filters by building, address, unit, neighborhood, agent name/firm.
- [x] **Price history full dates (2026-04-20):** `fmtDate()` now shows "Apr 16, 2026" instead of "Apr 2026".
- [x] **Monitor pass2 fill rate:** ✅ Moot — all 373/373 listings backfilled to pass2 in Session 9 via direct API calls.
- [ ] **Days-on-market: update index.html to use listed_date.** `listed_date` field is now stored in every listing. Update JS to compute DOM live: `Math.floor((new Date() - new Date(listing.listed_date)) / 86400000)`, with fallback to `listing.days_on_market` when `listed_date` is null.
- [ ] **New/reduced badges (P1):** Add `badge` field (`"new"`, `"reduced"`, or `null`) in pull.py by diffing current prices against previous dated JSON. Render as a pill badge in index.html's Building/Unit column. Architecture documented in PROJECTPLAN.md.
- [ ] **Shortlist feature:** In-app ability to mark listings as seen/liked/rejected. **Do not start until sharing model is decided** — localStorage (device-only) vs. shared backing store (GitHub API, Sheets, etc.) are very different builds. See PROJECTPLAN.md Phase 3 for options and tradeoffs.
- [x] **Rental end-to-end validation:** ✅ All 43 rentals successfully passed through Pass 2 → normalize_rental() → stub merge in Session 9. Beds/baths/sqft backfill from Pass 1 stubs confirmed working.
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
