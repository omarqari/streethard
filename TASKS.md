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
- [x] **Days-on-market: update index.html to use listed_date (Session 12, 2026-05-02).** `daysListed(listing)` helper added; reads `listed_date` exclusively (validated as canonical for 99.7% of listings; the actor's `days_on_market` field is wrong on 100% of records). Returns `null` when `listed_date` is missing — badge shows `—` rather than misleading numbers. Updated 4 read sites: table row, card view, sort comparator, NEW filter.
- [ ] **New/reduced badges (P1):** Add `badge` field (`"new"`, `"reduced"`, or `null`) in pull.py by diffing current prices against previous dated JSON. Render as a pill badge in index.html's Building/Unit column. Architecture documented in PROJECTPLAN.md.
- [ ] **Shortlist feature:** In-app ability to mark listings as seen/liked/rejected. **Do not start until sharing model is decided** — localStorage (device-only) vs. shared backing store (GitHub API, Sheets, etc.) are very different builds. See PROJECTPLAN.md Phase 3 for options and tradeoffs.
- [x] **Rental end-to-end validation:** ✅ All 43 rentals successfully passed through Pass 2 → normalize_rental() → stub merge in Session 9. Beds/baths/sqft backfill from Pass 1 stubs confirmed working.
- [x] **Co-op sqft gap (Sessions 10–11, 2026-05-02):** ✅ Pixel-polygon estimation method developed, validated to ~2–5% accuracy against 8 plans with known official sqft. 15 co-op listings now have estimates flagged `sqft_estimated: true` with gray styling and tooltips in StreetHard. Full methodology in `SQFT-METHODOLOGY.md`.
- [x] **Cron silent-failure diagnosis + resilience patches (Session 12, 2026-05-02):** ✅ Pass 1 sentinel guard, `get_run` 5xx retry, Pass 2 `RequestException` catch, `refresh.yml` `if: success() || failure()` on the commit step. Workflow run #24 brought in 46 new listings (first fresh data in 12 days). Memo23 issue thread updated with run-ID evidence.
- [x] **Partial Pass 2 backfill (Session 12, 2026-05-02):** ✅ Direct API call to memo23 actor on the 46 pass1 records. SaleListingDetailsFederated GraphQL endpoint is currently 403'd by StreetEasy's PX bot detection; the actor's fallback endpoint returns partials missing financial fields. Salvaged `listed_date`, `price_history`, agent contact, year_built, neighborhood, $/sqft for 38 of 38 sales. Records remain at `data_quality=pass1` since taxes/fees still missing. The 8 rentals in the same batch returned 0 items.

---

## Open from Session 12 (2026-05-02)

- [ ] **Watch Mon's 09:00 UTC cron (2026-05-04).** Confirms whether memo23 has acted on the proxy/PX issues. Sentinel guard will surface a clean failure if not.
- [ ] **Memo23 follow-up:** if the next cron sentinel-fails, post a follow-up on the issues thread referencing run IDs and the partial-backfill PX 403 evidence.
- [ ] **Harden `pull.py` for partial Pass 2 responses.** When the actor returns `partial: True` with `partialReason` mentioning a blocked GraphQL endpoint, extract `price_history`, `contacts_json`, building fields, and $/sqft into the existing pass1 record (don't reject the whole item). Set a `last_partial_pass2` audit field. Stay at `data_quality=pass1`. The salvage logic exists in this session's notes — needs to be folded into `merge_pass2_into_db`.
- [ ] **Investigate rental Pass 2 failure mode.** All 8 rental URLs in the partial-backfill batch returned 0 items. Different from the sale-side partial response. Test 1–2 individual rental URLs in isolation to characterize before pinging memo23.
- [ ] **Add a pipeline health assertion.** Fail the cron when `max(listed_date)` is more than N days behind today. Catches silent-failure modes that pass our existing guards (count, exit code) but still produce stale data.

---

## Before Making an Offer

- [ ] Engage a real estate attorney (non-optional in NY).
- [ ] Request full offering plan from broker.
- [ ] Request last 2 years of building financial statements.
- [ ] Review: reserve fund level, outstanding loans, pending assessments, major capital projects.
- [ ] For co-ops: confirm flip tax, sublet policy, pet policy, board package requirements.
- [ ] Schedule inspector (especially pre-war, recent renovations, or lower floors).
- [ ] Run ACRIS one more time for unusual transfers or liens (condos only).
- [ ] **For co-ops with our pixel-method sqft estimate:** Get an ANSI-Z765 measurement ($250–400 from NYC Measure or Compass partner) before offering. Our estimate is good for screening but not for negotiating $/sqft.

---

## Open Questions

- [ ] Co-ops, condos, or both? Changes due diligence stack significantly.
- [ ] School-zone constraint?
- [ ] Financing pre-approval in place, or still to do?
