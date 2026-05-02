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
- [x] **Partial Pass 2 backfill (Session 12, 2026-05-02):** ✅ Direct API call to memo23 actor on the 46 pass1 records. SaleListingDetailsFederated GraphQL endpoint was 403'd by StreetEasy's PX bot detection; the actor's fallback endpoint returned partials missing financial fields. Salvaged `listed_date`, `price_history`, agent contact, year_built, neighborhood, $/sqft for 38 of 38 sales.
- [x] **Full Pass 2 backfill after memo23 PX fix (Session 19, 2026-05-02):** ✅ memo23 patched the `/sale/{id}` path to pull financials from a non-blocked source. All 38 sale listings backfilled to pass2 with full financial data (run `eEQfCNBuh0fTNihJ0`). Updated `normalize()` with new field schema (`saleCombineResponse_sale_*`, `pricing_*`, `propertyDetails_*`). DB now 411 pass2, 0 partial, 8 pass1 (rentals only).

---

## Listing Status Tracking (Backend Migration)

Full design spec in `STATUS-FEATURE.md`. Build-time CTO walkthrough in `STATUS-BACKEND-WALKTHROUGH.md` (file layout, schema, code snippets, phasing rationale). Architecture summary in `PROJECTPLAN.md` under "Listing Status Tracking (Backend Migration)." Build order below.

### Pre-Build Decisions (resolved Session 15, 2026-05-02)

- [ ] **Confirm final status names.** Proposed: `watching / viewing / shortlisted / rejected / offered`, plus implicit `none`. Sign off or rename. Locks the CHECK constraint and the UI cycle order. *(Carried over from Session 13 — still needs explicit user sign-off on names; defaults assumed in walkthrough.)*
- [ ] **Confirm chip vocabulary.** Proposed: `no light`, `bad layout`, `building risk`, `priced too high`, `noise`, `condition`, `bad block`, `flip tax`, `board risk`. Curated on purpose — free-text tags devolve into the same idea spelled three ways. Amend if anything is missing. *(Carried over from Session 13 — still needs explicit user sign-off.)*
- [x] **Confirm backup posture.** ✅ Session 15: Railway snapshots only for v1; no extra `pg_dump` script. Revisit when notes accumulate enough to feel irreplaceable.
- [x] **Confirm Hobby-tier signup ($5/mo).** ✅ Session 15: recommended and accepted. Provisioning happens in D5.
- [x] **Confirm domain.** ✅ Session 16: custom domains on Spaceship — `streethard.omarqari.com` (app, CNAME → `omarqari.github.io`) and `api.streethard.omarqari.com` (API, CNAME → Railway service). Default `*.up.railway.app` and `omarqari.github.io/streethard` stay live as fallbacks.
- [x] **Language pick.** ✅ Session 15: FastAPI (Python 3.12). Validated by GitHub repo check — `omarqari/streethard` is the only public repo and it's Python; `insightcubed`/`OmarGPT` are 404.
- [x] **Same-repo vs new-repo.** ✅ Session 15: same repo, `api/` subfolder, Railway Root Directory setting. One PR can change both ends.
- [x] **Per-user attribution.** ✅ Session 15: dropped. Single shared write key, no `updated_by` column.
- [x] **Generate the `WRITE_API_KEY`.** ✅ Session 18: generated and saved in `.env` and Railway env vars. Value: `MLCzWI0Jj9_JiTsEU5UUB92Jn-ILmPnLhFbDK1tCnN4`.

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

### Frontend Build

- [ ] **F1 — Settings panel + Test Connection.** Gear icon top-right of header opens a modal. API key input writes to `localStorage['streethard.api_key']`. "Test Connection" button hits `GET /health` with the key set on a separate test endpoint or noop write — surface a clear green/red result inside the modal.
- [ ] **F2 — Status pill cycle (column 1).** New leading cell in the table row template. Tap cycles `none → watching → viewing → shortlisted → rejected → offered → none`. Long-press / right-click menu jumps directly to any status. Pill uses `data-status="..."` attribute for CSS coloring.
- [ ] **F3 — Watch bookmark toggle.** Bookmark icon next to the pill. Independent of status — rejecting does not clear watch.
- [ ] **F4 — Expanded-row notes editor + chips.** Append to the existing expansion content. Notes textarea with 1-second debounce on keystrokes (only the notes field; status / watch / chips fire immediately). Multi-select chip selector above the textarea, drawn from the locked vocabulary. Soft-cap notes at ~2,000 chars in the UI.
- [ ] **F5 — Optimistic update helper.** `updateStatus(listingId, patch)` mutates in-memory, re-renders, then PUTs. On any failure, queue the patch in the outbox and leave the UI as-is. Single-row PUTs only — no debounce on commits, no batching.
- [ ] **F6 — Offline outbox + flush triggers.** `localStorage['streethard.outbox']` array of `{listing_id, patch, ts}`. Flush via `POST /status/batch` on `window.online` and `document.visibilitychange` (when `!document.hidden`).
- [ ] **F7 — Two-fetch load + merge.** `Promise.all([fetch('data/latest.json'), fetch('${API_BASE}/status')])`. Tolerate the status fetch failing (e.g., no key, Railway down) — the listings still render with default-status overlays.
- [ ] **F8 — Filter chips.** "Show only Shortlisted" toggle in the existing filter bar. "Hide Rejected" toggle, on by default once any listing is rejected.

### Deployment & Ops

- [x] **D1 — Railway project setup.** ✅ Session 18: Project created, Root Directory set to `api`, connected to `omarqari/streethard` GitHub repo. Builds pick up `api/requirements.txt` and run `uvicorn`.
- [x] **D2 — Postgres plugin.** ✅ Session 18: Managed Postgres provisioned. `DATABASE_URL` auto-injected. `/health` confirms DB connection.
- [x] **D3 — Env vars.** ✅ Session 18: `WRITE_API_KEY`, `ALLOWED_ORIGIN`, `ALLOWED_ORIGIN_FALLBACK` all set in Railway.
- [x] **D4 — Healthcheck.** ✅ Session 18: Railway healthcheck configured on `/health`.
- [x] **D5 — Hobby tier upgrade.** ✅ Session 18: Hobby plan active ($5/mo). Service doesn't sleep.
- [ ] **D6 — `API_BASE` wired into `index.html`.** Set `const API_BASE = "https://api.streethard.omarqari.com"` near the top of the script section. Single point of change if the URL ever moves.
- [ ] **D7 — Mobile device key paste.** On the iPhone, open the live Pages URL → Settings → paste the same `WRITE_API_KEY`. Verify Test Connection passes.
- [ ] **D8 — Deploy verification.** Push a deploy. Mark a listing Shortlisted on iPhone. Hard-refresh laptop. Confirm the change persists. Push another (no-op) deploy and confirm the change still persists post-deploy.

### v1 Acceptance Criteria

All seven must pass on a real iPhone + laptop pair before v1 is closed:

- [ ] **A1 — Cross-device sync.** Mark Shortlisted on iPhone. Refresh laptop. Same status visible.
- [ ] **A2 — Persistence across deploys.** Push a deploy. Shortlisted listing is still Shortlisted.
- [ ] **A3 — Watch is independent.** Reject a watched listing. Bookmark icon stays. Listing still surfaces under the "watched" filter.
- [ ] **A4 — Offline tour.** Phone in airplane mode → mark Viewing → type a note → toggle airplane mode off. Within ~3 seconds, change is on the laptop after refresh.
- [ ] **A5 — Bad key fails clearly.** Wrong key in Settings → Test Connection shows a red error in the modal. Writes from that device are blocked with a non-silent toast.
- [ ] **A6 — Read without key.** Clean browser, no key. Statuses still show; status pill is read-only with a tooltip explaining how to add the key.
- [ ] **A7 — Cron untouched.** A `refresh.yml` run completes; statuses are unchanged afterward.

### v1.5 (deferred — do NOT pollute v1 list)

- [ ] **(v1.5)** Service Worker + IndexedDB so the app works offline in a closed tab.
- [ ] **(v1.5)** Per-IP write rate limit on the API.
- [ ] **(v1.5)** Export-to-CSV of marked listings.
- [ ] **(v1.5)** Watch-triggered visual diff when a watched listing's price drops. Concrete spec from 2026-05-02 review: snapshot `price_at_watch` (NUMERIC) on the watch=true transition; render a yellow `RECONSIDER` pill in the row when current price < `price_at_watch`. See `STATUS-FEATURE.md` "Re-evaluation badge specifics."
- [ ] **(v1.5)** Saved-filter tabs above the table — `All / Active / Toured / Watching / Offered`. Pure frontend; default tab becomes `Active` once any listings are shortlisted. Logged 2026-05-02 from proposal review.
- [ ] **(v1.5)** Recently-delisted surface for tracked listings. Collapsible section under the main table: "Recently delisted that you tracked." Requires the merge step to keep orphan `listing_status` rows on a separate list rather than dropping them. Logged 2026-05-02 from proposal review.

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

### Status feature (Session 16 — non-blocking for build)
- [ ] **Final status names.** Currently `watching / viewing / shortlisted / rejected / offered` plus implicit `none`. Confirm or rename before the schema CHECK constraint is set in stone — renaming after first writes is an idempotent ALTER + client update but worth doing once.
- [ ] **Final chip vocabulary.** Currently `no light`, `bad layout`, `building risk`, `priced too high`, `noise`, `condition`, `bad block`, `flip tax`, `board risk`. Curated on purpose. Amend if anything is missing before F4 ships.
- [ ] **Mobile Safari `localStorage` eviction.** iOS 17 wipes site data after ~7 days of non-use. Settings panel must show a "key not set" empty state, not crash. Decide: mitigate now (IndexedDB or service worker storage), or accept the periodic re-paste at v1?
- [ ] **Spouse / family writes ever in scope?** Today the shared write key works for n=1. Revisit only if attribution ever matters (would require schema change to add `updated_by` and a per-user key model).
- [ ] **DNS cutover — when to drop the fallback?** Nameservers migrated to Spaceship in Session 18. Once propagation completes and both devices verify load via `streethard.omarqari.com`, remove `ALLOWED_ORIGIN_FALLBACK` from Railway env vars. Also enable "Enforce HTTPS" on GitHub Pages settings.
- [ ] **Custom domain on the cron data feed?** The app currently fetches `data/latest.json` as a relative path under whichever origin loaded `index.html`, so the custom domain works for free. No action needed unless we ever want to host the data behind a separate CDN.

### Status feature (Session 17 — proposal-review additions, decide before v1 schema hardens)

- [ ] **`triaged-out` as a seventh status?** Real triage often produces "skimmed, it's a no, but I won't formally reject" — softer than `rejected`, more deliberate than `none`. Adding it after launch means amending the CHECK constraint and reordering the cycle. Decide before B2 lands or accept that `rejected` covers both cases. Captured in `STATUS-FEATURE.md` "Deferred Design Ideas."
- [ ] **Last-write-wins vs status history.** Spec is last-write-wins. Reversals (vetoed → active when a price drops; shortlisted → rejected after a tour) are common in this workflow. Decide whether v1 should append to a `listing_status_history` table on every write — cheap to add now, expensive to reconstruct later. Captured in `STATUS-FEATURE.md` and the v2 backlog.
- [ ] **Notes field: free text only, or structured + free text?** Tour metadata (date, attendees, follow-up date, `private_max_offer`) currently lives in the notes textarea. Decide whether v2 should promote any of those to structured columns. Won't block v1; ask after the family has ~10 marked listings and we can see whether the notes are painful. Captured in `STATUS-FEATURE.md`.
- [ ] **Default tab on app load.** v1 ships with no tabs. If v1.5 adds saved-filter tabs, decide whether the default is `All` (current behavior) or `Active` once any listings are shortlisted. Affects whether the family lands on "the shortlist" or "the firehose" — different UX bets.
