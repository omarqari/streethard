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
