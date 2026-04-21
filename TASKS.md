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

## 🟡 One Remaining Issue: Pass 2 Field Coverage (not a blocker)

Block 1 (403s) and Block 2 (Pass 1 ID extraction) are both resolved as of 2026-04-19 Session 5.

### What was fixed

**Block 1 — Apify 403s:** ✅ Resolved by memo23 (iOS API key rotation fix, 2026-04-19).

**Block 2 — Pass 1 ID extraction:** ✅ Fixed in `pull.py` (commit `1e5cd99`):
- Search results return `"id": "1822856"` as a top-level field — `item.get("id")` works correctly
- `urlPath` field (e.g. `/building/evans-tower-condominium/25bc`) is now used for Pass 2 URLs instead of constructing `/sale/{id}` URLs (which return "No results found" in the new actor version)
- `listing_ids[]` list tracks IDs in parallel with `listing_urls[]` so the delta loop doesn't need to regex-extract IDs from URLs
- `flattenDatasetItems: True` added to `run_input` (required for `normalize()` to find the long field names)

### Remaining issue: Pass 2 individual listing pages

The new actor version returns "No results found" for individual `/sale/{id}` URLs (pre-existing issue per larry-lobster, 22 days ago). The fix above switches to building URL format (`/building/slug/unit`) for Pass 2 — this has NOT been tested yet.

**Most likely outcomes on next CI run:**
1. **Building URLs work** → full data (fees, taxes, agent info, price history) ✅
2. **Building URLs also fail** → script falls back to Pass 1 data (price, beds, baths, sqft, type, address) — app works but monthly payment shows mortgage-only, no fees/taxes

**Next action:** Trigger a CI run and check the output. If Pass 2 normalization fails (all "No results found"), the debug dump will fire and we'll see what the actor actually returns.

1. **Trigger CI run:** GitHub → Actions → "Refresh listings" → Run workflow → Mode: `sale`, Max items: `20` (small test run first)
2. **Check output:** Does `data/latest.json` have `monthly_fees` and `monthly_taxes` populated? If yes, Pass 2 works.
3. **If Pass 2 fails:** Paste the DEBUG lines from the "Run pull script" step to Claude for further diagnosis.

---

## Phase 2 Enhancements (Post-v1)

- [x] **Rental comp analysis:** Added UES rental listings ($10K–$20K/mo). Mode toggle (For Sale / For Rent / Both) added to app. Pipeline pulls both types in one run.
- [x] **Pass 1 ID extraction fix:** Fixed — `item['id']` works; `urlPath` used for Pass 2 URLs; `flattenDatasetItems: True` added.
- [x] **Pass 2 — fixed 2026-04-20:** memo23 pushed a fix. Validation test passed (Run ID: Lz5JkP1Ky592CZU8h) — price history (17 entries), agent contact, fees, taxes, sqft all confirmed. Ready for full production pull.
- [ ] **Run full production pull:** Push all current code changes, then trigger CI run with mode=both, max_items=500, pass1_only=false, force_pass2=true (to backfill fees/taxes/agent/history for all listings).
- [x] **Rental normalize() validation:** `normalize_rental()` fully rewritten with verified `combineData_rental_*` schema (2026-04-21). `/rental/{id}` URL format confirmed. End-to-end production run still pending — debug dump fires automatically if field names change.
- [x] **Text search (2026-04-20):** Free-text search bar in filter bar. Filters by building, address, unit, neighborhood, agent name/firm. Case-insensitive substring match, real-time on keystroke.
- [ ] **Days-on-market: update index.html to use listed_date.** `listed_date` field is now stored in every listing. Update JS to compute DOM live: `Math.floor((new Date() - new Date(listing.listed_date)) / 86400000)`, with fallback to `listing.days_on_market` when `listed_date` is null.
- [ ] **New/reduced badges (P1):** Add `badge` field (`"new"`, `"reduced"`, or `null`) in pull.py by diffing current prices against previous dated JSON. Render as a pill badge in index.html's Building/Unit column. Architecture documented in PROJECTPLAN.md.
- [ ] **Shortlist feature:** In-app ability to mark listings as seen/liked/rejected. **Do not start until sharing model is decided** — localStorage (device-only) vs. shared backing store (GitHub API, Sheets, etc.) are very different builds. See PROJECTPLAN.md Phase 3 for options and tradeoffs.
- [ ] **Rental end-to-end validation:** Test a standard apartment rental (not townhouse) through the full Pass 1 → Pass 2 → normalize_rental() → stub merge pipeline. Confirm beds/baths/sqft backfill works correctly.
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
