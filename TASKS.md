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

- [ ] Daily: GitHub Actions auto-runs the pull at 09:00 UTC. Verify output after each run.
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
- [x] **Shortlist feature:** ✅ Redesigned in Session 21 as three-bucket triage system (Inbox/Shortlist/Archive). Backend on Railway (shared Postgres). See "Three-Bucket Triage System" section below for build tasks.
- [x] **Rental end-to-end validation:** ✅ All 43 rentals successfully passed through Pass 2 → normalize_rental() → stub merge in Session 9. Beds/baths/sqft backfill from Pass 1 stubs confirmed working.
- [x] **Co-op sqft gap (Sessions 10–11, 2026-05-02):** ✅ Pixel-polygon estimation method developed, validated to ~2–5% accuracy against 8 plans with known official sqft. 15 co-op listings now have estimates flagged `sqft_estimated: true` with gray styling and tooltips in StreetHard. Full methodology in `SQFT-METHODOLOGY.md`.
- [x] **Cron silent-failure diagnosis + resilience patches (Session 12, 2026-05-02):** ✅ Pass 1 sentinel guard, `get_run` 5xx retry, Pass 2 `RequestException` catch, `refresh.yml` `if: success() || failure()` on the commit step. Workflow run #24 brought in 46 new listings (first fresh data in 12 days). Memo23 issue thread updated with run-ID evidence.
- [x] **Partial Pass 2 backfill (Session 12, 2026-05-02):** ✅ Direct API call to memo23 actor on the 46 pass1 records. SaleListingDetailsFederated GraphQL endpoint was 403'd by StreetEasy's PX bot detection; the actor's fallback endpoint returned partials missing financial fields. Salvaged `listed_date`, `price_history`, agent contact, year_built, neighborhood, $/sqft for 38 of 38 sales.
- [x] **Full Pass 2 backfill after memo23 PX fix (Session 19, 2026-05-02):** ✅ memo23 patched the `/sale/{id}` path to pull financials from a non-blocked source. All 38 sale listings backfilled to pass2 with full financial data (run `eEQfCNBuh0fTNihJ0`). Updated `normalize()` with new field schema (`saleCombineResponse_sale_*`, `pricing_*`, `propertyDetails_*`). DB now 411 pass2, 0 partial, 8 pass1 (rentals only).
- [x] **Pipeline health strip (Session 24, 2026-05-03):** ✅ Green/yellow/red staleness indicator between summary bar and tabs. Shows last refresh date, age, data quality counts. Yellow at 3+ days, red at 5+ days stale.
- [x] **Price-history signal icons (Session 24, 2026-05-03):** ✅ Per-listing icons in DAYS LISTED column: ✂ price cuts (red), ↻ re-listed (orange), ⏸ off-market-and-back (blue), ⏳ stale 90d+ (yellow). Cached per listing ID. 202/368 sale listings have cuts.
- [x] **Price Cuts filter (Session 24, 2026-05-03):** ✅ Checkbox in filter bar. Filters to only listings with PRICE_DECREASE events.
- [x] **Daily cron (Session 24, 2026-05-03):** ✅ Changed from Mon+Thu to daily 09:00 UTC. PAT updated with Workflows permission; pushed successfully.
- [x] **DNS cutover cleanup (Session 24, 2026-05-03):** ✅ Removed `ALLOWED_ORIGIN_FALLBACK` from Railway. Enabled "Enforce HTTPS" on GitHub Pages.

---

## Three-Bucket Triage System (Inbox / Shortlist / Archive)

Supersedes the old "status pill cycling" (F2) and "watch toggle" (F3) design from Sessions 13–19. The new model is simpler and maps to the user's Gmail-like mental model: new listings land in the Inbox, get triaged to Shortlist (actively pursuing) or Archive (rejected), and archived listings auto-resurrect on price drops.

Full design spec in `STATUS-FEATURE.md`. Backend walkthrough in `STATUS-BACKEND-WALKTHROUGH.md`. Architecture summary in `PROJECTPLAN.md`.

### Design Decisions (Session 21, 2026-05-02)

- [x] **Three buckets replace status + watch.** `inbox` (default), `shortlist`, `archive`. Replaces six-status enum and orthogonal watch boolean. ✅ Session 21.
- [x] **OQ/RQ rankings are Shortlist-exclusive.** Moving out of Shortlist clears rankings (server-side enforced). ✅ Session 21.
- [x] **Auto-resurrection on price drop.** Archived listings auto-promote to Inbox when current price < `price_at_archive`. Client-side logic on load, batch PUT to persist. ✅ Session 21.
- [x] **URL hash for tab state.** `#inbox`, `#shortlist`, `#archive` for bookmarkability (family-shared app). ✅ Session 21.
- [ ] **Confirm chip vocabulary.** Proposed: `no light`, `bad layout`, `building risk`, `priced too high`, `noise`, `condition`, `bad block`, `flip tax`, `board risk`. Deferred to after the bucket system ships — chips work on Shortlist items during due diligence.

### ✅ DNS + Custom Domains (Session 18, 2026-05-02)

All infrastructure tasks completed by Claude in Cowork mode (browser automation on Spaceship, GitHub, Railway).

- [x] **U1 — Add CNAME records on Spaceship.** ✅ Session 18: Migrated nameservers from Namecheap to Spaceship. Added 4 custom DNS records: `streethard` CNAME → `omarqari.github.io`, `api.streethard` CNAME → `bu5x85os.up.railway.app`, `_railway-verify` TXT record, `www` CNAME → `omarqari.github.io` (LinkedIn redirect).
- [x] **U2 — GitHub Pages custom domain.** ✅ Session 18: Custom domain `streethard.omarqari.com` configured. DNS check passed. Enforce HTTPS pending DNS propagation from nameserver migration.
- [x] **U3 — Railway custom domain.** ✅ Session 18: `api.streethard.omarqari.com` added as custom domain. TXT verification record added on Spaceship. Awaiting DNS propagation for auto-SSL.
- [x] **U4 — Verify both domains end-to-end.** Awaiting DNS propagation (nameserver switch Namecheap → Spaceship, up to 48h). Once propagated: verify `https://streethard.omarqari.com` loads, `curl https://api.streethard.omarqari.com/health` returns 200, enable "Enforce HTTPS" on GitHub Pages, then remove `ALLOWED_ORIGIN_FALLBACK` from Railway env vars.

### ✅ Backend Build (completed Session 18, 2026-05-02)

- [x] **B1 — Skeleton + `/health`.** ✅ `api/main.py`, `api/db.py`, `api/requirements.txt`, `api/railway.toml`. FastAPI + asyncpg pool. `/health` returns `{"ok": true, "db": "connected"}`.
- [x] **B2 — Schema + startup migration.** ✅ `api/schema.sql` with `listing_status` table, CHECK constraint, two indexes. Idempotent `CREATE … IF NOT EXISTS` via FastAPI startup hook.
- [x] **B3 — `GET /status`.** ✅ Public read, `Cache-Control: no-store`, returns `{items: [...]}`.
- [x] **B4 — `PUT /status/{listing_id}` + auth.** ✅ `INSERT … ON CONFLICT DO UPDATE` with `COALESCE`. `X-API-Key` via `hmac.compare_digest`. Verified: missing key → 401, wrong key → 401, correct key → 200.
- [x] **B5 — `POST /status/batch`.** ✅ Idempotent batch upsert. 200 on full success; 207 with per-item status on partial failure.
- [x] **B6 — CORS + final hardening.** ✅ `ALLOWED_ORIGIN=https://streethard.omarqari.com`, `ALLOWED_ORIGIN_FALLBACK=https://omarqari.github.io`. Methods `GET, PUT, POST, OPTIONS`. Headers `Content-Type, X-API-Key`.

### Frontend Build — Three-Bucket Triage

Replaces old F2 (status pill cycling) and F3 (watch toggle). Existing work retained: F1 (Settings panel ✅), F7 (two-fetch load + merge ✅), OQ/RQ rankings ✅, OQ/RQ notes ✅.

- [x] **T1 — Tab navigation (Inbox / Shortlist / Archive).** ✅ Session 22. Three tab pills between summary bar and filter bar. Inbox active on load. URL hash routing (`#inbox`, `#shortlist`, `#archive`). OQ#/RQ# columns hidden via CSS class `hide-ranks` outside Shortlist.
- [x] **T2 — Transition buttons per row.** ✅ Session 22. Actions column: Inbox shows ★Shortlist + ✕Archive, Shortlist shows Archive, Archive shows ↩Inbox. Optimistic UI. Fires `PUT /status/{id}` with `bucket` + `bucket_changed_at`. Archive sends `price_at_archive`.
- [x] **T3 — Server-side OQ/RQ clearing.** ✅ Session 22. `UPSERT_WITH_RANK_CLEAR_SQL` uses 7 params, hardcodes `oq_rank = NULL, rq_rank = NULL` when transitioning out of shortlist. `should_clear_ranks()` detects exit from shortlist.
- [x] **T4 — Auto-resurrection on price drop.** ✅ Session 22. `autoResurrect()` on page load: scans archived listings, batch-transitions to inbox via `/status/batch` when current price < `price_at_archive`.
- [x] **T5 — Tab badge counts.** ✅ Session 22 (built inline with T1). `updateBucketCounts()` updates badge numbers on every filter/render cycle.
- [x] **T6 — Sort defaults per tab.** ✅ Session 23. Inbox: Monthly Payment desc. Shortlist: OQ# asc (nulls last). Archive: `bucket_changed_at` desc (most recently archived first). Sort resets on tab switch; init respects URL hash. Added `archived_at` sort case to `sortListings()`.
- [ ] **T7 — Optimistic update helper.** `updateStatus(listingId, patch)` mutates in-memory, re-renders, then PUTs. On failure, queue in outbox. (Carried from old F5.)
- [ ] **T8 — Offline outbox + flush.** `localStorage['streethard.outbox']` flushed via `POST /status/batch` on `online` / `visibilitychange`. (Carried from old F6.)
- [ ] **T9 — Card view adaptation.** Cards in Shortlist show OQ/RQ notes; Inbox/Archive cards do not show ranking fields. Transition buttons visible in card view too.
- [ ] **T10 — Chips (Shortlist only).** Multi-select chip selector in expanded row for shortlisted items. Fixed vocabulary. Fires immediately on change. (Carried from old F4, scoped to Shortlist.)

### Deployment & Ops

- [x] **D1–D5 — Railway infra.** ✅ Session 18. Project, Postgres, env vars, healthcheck, Hobby tier all done.
- [x] **D6 — Schema migration for three-bucket system.** ✅ Session 22. Idempotent PL/pgSQL migration in `schema.sql`. Adds bucket/bucket_changed_at/price_at_archive, backfills from watch, drops old status+watch columns. Deployed live on Railway.
- [x] **D7 — `API_BASE` wired into `index.html`.** ✅ Already done (Session 18). `const API_BASE = "https://api.streethard.omarqari.com"`.
- [x] **D8 — Mobile device key paste.** ✅ Obsolete — auth removed in Session 26. All endpoints are public (CORS-restricted).
- [ ] **D9 — Deploy verification.** Push a deploy. Shortlist a listing on iPhone. Hard-refresh laptop. Confirm the change persists.

### v1 Acceptance Criteria

All must pass on a real iPhone + laptop pair before v1 is closed:

- [ ] **A1 — Cross-device sync.** Shortlist a listing on iPhone. Refresh laptop. Same listing appears in Shortlist tab.
- [ ] **A2 — Persistence across deploys.** Push a deploy. Shortlisted listing is still in Shortlist tab.
- [ ] **A3 — Archive removes from Inbox.** Archive a listing. It disappears from Inbox, appears in Archive tab.
- [x] **A4 — OQ/RQ cleared on exit from Shortlist.** ✅ Session 23: verified end-to-end via API test cycle (shortlist with OQ=2/RQ=5 → archive → inbox → re-shortlist, ranks null at every step).
- [ ] **A5 — Auto-resurrection.** Archive a listing at $3M. Simulate a price drop to $2.8M in db.json. Reload app. Listing appears in Inbox with "Price dropped" badge.
- [ ] **A6 — Offline tour.** Phone in airplane mode → shortlist a listing → toggle airplane mode off. Within ~3 seconds, change is on the laptop after refresh.
- [x] **A7 — Bad key fails clearly.** ✅ Obsolete — auth removed in Session 26.
- [x] **A8 — Read without key.** ✅ Obsolete — auth removed in Session 26. All endpoints public.
- [ ] **A9 — Cron untouched.** A `refresh.yml` run completes; bucket assignments unchanged afterward.
- [ ] **A10 — New listings land in Inbox.** Run cron. New listings appear in Inbox tab, not Shortlist or Archive.

### v1.1 (after bucket system ships)

- [ ] **(v1.1)** Bulk archive — checkboxes + toolbar button to archive multiple Inbox listings at once. Row markup includes checkbox hook from v1 (hidden, not wired); wire in v1.1.
- [ ] **(v1.1)** Keyboard shortcut `e` to archive highlighted row (Gmail muscle memory).
- [ ] **(v1.1)** Chips on Shortlist items (T10 above).

### v1.5 (deferred — do NOT pollute v1 list)

- [ ] **(v1.5)** Service Worker + IndexedDB so the app works offline in a closed tab.
- [ ] **(v1.5)** Per-IP write rate limit on the API.
- [ ] **(v1.5)** Export-to-CSV of shortlisted listings.
- [ ] **(v1.5)** Recently-delisted surface for tracked listings. Collapsible section under the main table: "Recently delisted that you shortlisted." Requires the merge step to keep orphan `listing_status` rows on a separate list rather than dropping them.

### v2 (deferred — only if actually needed)

- [ ] **(v2)** Per-user identity. Multi-key with per-user attribution on notes.
- [ ] **(v2)** Push notifications when a watched listing's price changes.
- [ ] **(v2)** Structured tour metadata columns on `listing_status`: `toured_at`, `tour_attendees JSONB`, `follow_up_at`, `private_max_offer NUMERIC`. Folds in only if the free-text notes field becomes painful in actual use. Logged 2026-05-02 from proposal review.
- [ ] **(v2)** Status history / audit trail. Second table `listing_status_history(listing_id, status, watch, chips, changed_at)` appended on every write. Cost ~$0/mo at n=1; pulls in only if any reversal becomes "wait, why did we say no?". Logged 2026-05-02 from proposal review.
- [x] **Custom domain.** ✅ Promoted to v1 in Session 16 — see "User Action Required — DNS + Custom Domains" above.

---

## Open from Session 12 (2026-05-02)

- [ ] **Watch Mon's 09:00 UTC cron (2026-05-04).** Confirms whether memo23 has acted on the proxy/PX issues. Sentinel guard will surface a clean failure if not.
- [ ] **Memo23 follow-up:** if the next cron sentinel-fails, post a follow-up on the issues thread referencing run IDs and the partial-backfill PX 403 evidence.
- [x] **Harden `pull.py` for partial Pass 2 responses.** ✅ Already handled — `merge_pass2_into_db` routes `partial: True` items to `data_quality=partial` with `last_partial_attempt` and `partial_reason`. `build_pass2_queue` throttles retries via `PARTIAL_RETRY_DAYS`. Moot now that memo23's fix returns full data.
- [x] **Investigate rental Pass 2 failure mode.** ✅ Session 19: tested `/rental/5022439` (run `tIhlVjuDBh9LDQwxa`) — returns "No results found" sentinel. Not a PX block; the actor doesn't support individual rental URLs at all. Flagged to memo23 on Apify issues thread (2026-05-02). Awaiting his fix.
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

### Buying-decision (long-standing)
- [ ] Co-ops, condos, or both? Changes due diligence stack significantly.
- [ ] School-zone constraint?
- [ ] Financing pre-approval in place, or still to do?

### Product backlog (Session 17 — 2026-05-02)

A CPO slate of 14 proposed product improvements is in `PRODUCT-BACKLOG.md`,
themed by Decision Quality / Data Quality / UX / Signal & Noise / DD
Integration / Automation. Five open decisions are pending user selection:

- [ ] **Which backlog items to accept into TASKS.** Whole slate is awaiting
  pick. CPO-recommended quick-wins: #1 Rent-vs-Buy Card, #8 Compare Pane,
  #12 Pipeline Health Strip (all S, no inter-dependencies). CPO-recommended
  negotiation-data arc: #5 PLUTO → #6 ACRIS Overlay → #13 DD Quicklinks →
  #4 Comp Sheet PDF.
- [ ] **Floor plan licensing for #7.** Are Compass / StreetEasy floor plan
  images OK to commit to the public GitHub Pages repo, or do they need
  a private host? Blocks #7 (Floor Plan Surfacing) until decided.
- [ ] **#14 Cron diversification — wait or act?** Defer the decision until
  the Mon 2026-05-04 09:00 UTC cron outcome is in. Sentinel-fail → accept
  #14. Healthy → defer indefinitely.
- [ ] **#3 vs v1.5 RECONSIDER pill.** Confirm whether to ship both
  (CPO recommendation: yes — different surfaces) or pick one.
- [ ] **#9 vs v1.5 Saved-filter tabs.** Confirm whether to ship both
  (CPO recommendation: coexist — tabs for routine, URL-state for ad-hoc
  sharing).

### Triage system (Session 21 — remaining open questions)
- [ ] **DNS cutover — when to drop the fallback?** Nameservers migrated to Spaceship in Session 18. Once propagation completes, remove `ALLOWED_ORIGIN_FALLBACK` from Railway env vars and enable "Enforce HTTPS" on GitHub Pages.
- [ ] **Mobile Safari `localStorage` eviction.** iOS 17 wipes site data after ~7 days of non-use. Settings panel must show a "key not set" empty state. Decide: mitigate now (IndexedDB) or accept periodic re-paste?
- [ ] **Chip vocabulary.** `no light`, `bad layout`, `building risk`, `priced too high`, `noise`, `condition`, `bad block`, `flip tax`, `board risk`. Confirm or amend before T10 ships.
- [ ] **Status history / audit trail.** Last-write-wins for v1. Consider `listing_status_history` table in v2 if "why did we change our mind on this?" becomes a real question after a few months of use.
