# CLAUDE.md

Context for Claude (and future Claude instances) working on this project. Read this first.

## What This Project Is

This is a **personal** project to help the user purchase **one residential apartment in Manhattan, NYC** for their family. It is explicitly:

- n=1, single purchase over the next 6–12 months
- Personal, not commercial
- Not a startup, SaaS, brokerage tool, or research project
- Not an attempt to build a production data pipeline

Calibrate all recommendations accordingly. Engineering effort should be proportional to the decision — substantial, but not extravagant.

## User Profile

- Technically proficient: comfortable with Python, APIs, command-line tools
- Running **Claude in Cowork mode** — Claude can call APIs directly via HTTP, run bash, read/write files; no external MCP setup needed
- Prefers honest tradeoff analysis over hedged, safety-padded recommendations
- Will push back when advice is overly cautious; respects directness
- Values time: will build tooling, but not busywork

## Core Data Priorities

Fields the user cares about for each property:

- Current listing/asking price
- Historical prices (list-price changes, sold prices)
- Square footage
- Full address
- Year building constructed
- Other building-level characteristics (units, building class, amenities)

## Do NOT Recommend

- Commercial real estate APIs (ATTOM, RentCast, CoreLogic, HouseCanary) — overkill for n=1, expensive
- REBNY RLS access — broker-gated, expensive, not accessible for individuals
- Zillow Bridge API — gated to approved commercial customers
- Scraping StreetEasy directly — ToS violation, aggressive bot detection
- Heavy infrastructure: production databases, real-time pipelines, BBL-joined data lake, etc.
- Padded responses with generic “consult a professional” filler

## Preferred Approach (Current Plan)

**Primary ingestion**: Apify `memo23/streeteasy-ppr` (Pay-Per-Event, $3/1,000 results). Returns full detail including price history, agent name/phone/email, beds/baths/sqft, HOA, taxes, amenities. Validated GREEN.

**Secondary ingestion**: RapidAPI's NYC Real Estate API (`realestator` provider). Fast cached lookups, no price history or agent contact. Validated YELLOW. Use for quick sanity checks; 25 free requests/month remaining (~19 left).

**Supplemental free data** (NYC Open Data):

- **PLUTO** (NYC Dept of City Planning) — authoritative building data: year built, building class, units, lot area, gross bldg area
- **ACRIS** (NYC Dept of Finance) — historical deeded sales, queryable via Socrata API
- Join key across datasets: **BBL** (Borough-Block-Lot)

**Official per-property lookups** (free, manual, 15 min per candidate):

- ZoLa (`zola.planning.nyc.gov`) — BBL and zoning
- HPD Online — open building violations
- DOB NOW — permits, complaints, pending Local Law 11 façade work

## NYC-Specific Gotchas (Do Not Forget)

These are the non-obvious pitfalls that matter for Manhattan real estate data:

**Co-ops don’t appear in ACRIS at the unit level.** Co-op shares aren’t deeded real property. Only the underlying building transfers show up. If the user is looking at co-ops, unit-level sale history effectively exists only in StreetEasy / RLS.

**PLUTO aggregates condos to the building level.** One record per condo complex, not per unit. So PLUTO tells you about the building; listings/ACRIS tell you about the unit.

**StreetEasy already does ~90% of browsing.** Price history, comps, $/sqft, days-on-market are all on every listing page. Any tool built is a supplement for custom queries StreetEasy’s UI can’t answer — not a replacement.

**Building-level financial risk is invisible in public data.** Reserve funds, pending assessments, underlying mortgage, litigation — all from the offering plan package and financial statements from the broker. No dataset has this.

## Mortgage Calculator Defaults

Use these assumptions for all monthly payment estimates unless the user specifies otherwise:

- **Down payment:** $750,000 exactly (fixed dollar amount always, regardless of purchase price)
- **Interest rate:** 5.00% annual
- **Loan term:** 30 years

Formula: `M = P × [r(1+r)^n] / [(1+r)^n − 1]`  
Total monthly = mortgage payment + common charges/HOA + taxes

## Output Format — StreetHard HTML App

The app is called **StreetHard**. It is a static web app hosted on **GitHub Pages**, auto-refreshed weekly via **GitHub Actions**. The whole family can access it at a shared URL.

### Architecture
- `index.html` — static app shell; family-facing; all UI and mortgage math in client-side JavaScript
- `diagnostics.html` — separate operator page; reads `data/db.json` + `data/pipeline_health.json` + `data/latest.json`; shows Pass 1 coverage sparkline, W5 cliff guard last-7-days table, pass1/pass2 quality split, search URLs, and a "Newest listing" freshness kv (D-G2, Session 35) that reads `max(listed_date)` from `latest.json` and turns amber at >3d / red at >5d — catches the silent-normalize-drop failure class that hid 5 days of new listings before Session 34. Reachable via a tiny gray `diagnostics` link in the main app's footer (Session 32). The main app deliberately does *not* expose operator diagnostics.
- `data/db.json` — **canonical store**; persistent dict of all listings keyed by ID; each has `data_quality` ("pass1" or "pass2"); never overwritten destructively. Top-level `stats` block (`total`, `pass1_only`, `partial`, `pass2_complete`, `sale`, `rent`, `delisted`) is what `diagnostics.html` reads.
- `data/latest.json` — generated from db.json each run; wrapped object `{listings: [...], generated_at: "YYYY-MM-DDTHH:MM:SSZ"}` for the app to fetch on load. **Not a bare array** — the app reads `data.listings` and `data.generated_at`. Includes ALL listings with `status`, `last_pass1`, `last_pass2`, and `pass2_confirmed_off_market` fields per listing. Frontend renders W3 stale pill (gray "not seen Nd" if last_pass1 >7d) and W7 verified off-market badge. *Note:* `data_quality` is NOT carried into latest.json — that field lives only on db.json.
- `data/pipeline_health.json` — W4 observability log; last 60 days of `{date, pass1_sale, pass1_rent, active, delisted, status}`. Drives the diagnostics.html Pass 1 coverage sparkline AND the W5 cliff guard's rolling-7-day median baseline.
- `data/YYYY-MM-DD.json` — immutable dated archive of every past run
- `scripts/pull.py` — **incremental** Apify pull script; Pass 1 discovers listings, Pass 2 only fills in what's missing (capped at 100/run); saves db.json after every step
- `.github/workflows/refresh.yml` — cron every 6h (00:00/06:00/12:00/18:00 UTC, 4×/day as of Session 43); calls Apify (Pass 1/2 + capped stale-refresh), commits data/, Pages auto-deploys
- Apify token in `.env` locally; `APIFY_TOKEN` GitHub Secret in CI

### Design Language
Dark navy header (`#0E1730`), white card layout, blue links (`#3461D9`), orange accent (`#FF6000`).

- **Default view**: Sortable table on desktop (dense, comparison-optimized); auto-switches to card view on mobile (`window.innerWidth <= 768`) at page-init time.
- **Toggle**: Card view button always visible on both desktop and mobile.
- **Mobile table view (Session 33)**: `.table-wrap` is constrained to `max-width: 100vw` with `overflow-x: auto`; the table itself keeps `min-width: 900px` so cells stay legible and the user swipes horizontally to reach the rightmost columns. Body still has `overflow-x: hidden` so horizontal scroll is contained inside `.table-wrap`, not the page.
- **Default sort**: Per tab — Inbox: Monthly Payment desc, Shortlist: OQ# asc, Archive: bucket_changed_at desc
- **Text search**: Free-text search bar filters by building, address, unit, neighborhood, agent name/firm. Always visible in the filter bar — used constantly.
- **Filters button + popover/sheet (Session 32)**: All other filter controls (Beds, Type, Price ≤, Monthly ≤, ✂ Price Cuts, 👁 Seen, Clear all) live behind a single **Filters** button. A blue count badge appears on the button when any filter is set. Filters apply live as the user changes them — no Apply button. **Desktop:** anchored popover that opens below the button, dismisses on outside-click or Escape. **Mobile (≤768px):** transforms into a **bottom sheet** — `position: fixed` at the viewport bottom, 58vh tall, drag handle, "Filters" + ✕ header, labeled rows (BEDS / TYPE / MAX PRICE / MAX MONTHLY), larger 14px controls, sticky footer with Clear all + a dark navy **Show N** primary button whose N updates live. Full-screen backdrop dims everything else; tap-to-close. Body scroll locked while open. Mode toggle (For Sale / Rent / Both) stays inline to the left of the Filters button on the same row.
- **Price filter glyph**: Price and Monthly dropdowns use `≤` prefix on options (`≤ $3M`) instead of the older "Max Price" wording. Beds is an equality match, no glyph.
- **Mortgage calculator** in header: Down Payment · Rate · Term — interactive, recalculates all rows instantly
- **Row expansion**: Price History, Agent info, Payment Breakdown
- **Days Listed**: NEW/blue <7d, green 7–44d, yellow 45–120d, red 121d+
- **Fees/Mo + % Fees columns (Session 37)**: Two sortable columns immediately right of Monthly Pmt. `Fees/Mo` = non-P&I carry costs (co-op: maintenance; condo/house: common charges + taxes). `% Fees` = round(fees/total_monthly×100). Both show `—` for rentals and pass1-only listings with no fee data. `calcFees()` and `calcFeesPct()` helpers in `index.html`. Card v4 shows a muted sub-line under the all-in total: `Fees/mo $X,XXX · N%`.
- **Price-history signal icons**: Per-listing icons next to days badge — ✂ price cuts (red), ↻ re-listed (orange), ⏸ off-market-and-back (blue), ⏳ stale 90d+ (yellow). Cached per listing ID.
- **Stale pill interpretation**: A listing with a stale pill (not seen in Pass 1 for >7d) that still appears active on StreetEasy is typically **in-contract** — StreetEasy removes in-contract listings from search results, which naturally stops them appearing in Pass 1. The pill is working correctly in this case; the listing is no longer available.
- **Stale & off-market signals (W3 + W7 + W9)**: Listings unseen in Pass 1 for >7 days render a gray "not seen Nd" pill (amber if >21d). Listings *definitively* verified off-market render a red "off-market" badge (separate, stronger signal). The Shortlist tab shows a yellow alert strip when shortlisted listings get verified off-market in the last 14 days.
  - **W9 (2026-06-15) — off-market detection is now Inbox-wide and keyed on `offMarketAt`.** The reliable off-market signal is the detail page's `offMarketAt` date (StreetEasy serves full data even for rented/sold listings, with this field set), NOT "Pass 2 returned no data" (validated noisy: a single empty response is a transient backup-path drop 30/30 times). `normalize()`/`normalize_rental()` emit `off_market_date`; `merge_pass2_into_db()` sets `pass2_confirmed_off_market` + `off_market_date` when it's non-null and clears them when null — so **every** Pass 2 (all buckets, not just Shortlist) auto-detects off-market. The 4×/day capped stale sweep keeps the whole Inbox current. W7 `verify_stale_shortlists()` uses the same `offMarketAt` signal; a blank response is now *inconclusive* (never flagged). Off-market listings keep `status='active'` (badge only — not auto-archived). 106 listings flagged in the initial W9 sweep (40 sale, 66 rent).
- **Freshness banner (Session 32)**: User-facing data-staleness indicator. Hidden when the data is ≤1 day old (cron's normal cadence). Amber 2–3 days, red 4+ days, with plain-English copy: "Listings last updated 2 days ago." or "Listings haven't refreshed in 4 days — Omar may need to check." Replaces the older `#health-strip` and `#coverage-strip` operator-facing elements (both removed from the main app). The operator-facing Pass 1 coverage sparkline + W5 cliff-guard view moved to `diagnostics.html`.
- Single `index.html` for the main app + a separate `diagnostics.html` for operator-only views. No server, opens in any browser.

### Card View v4 (Session 33) — `.listing-card.v4`

Mobile-first, compact. The legacy 16px padding is zeroed out; each section owns its spacing. Five full-bleed sections, top to bottom:

1. **Header** (`.v4-header`) — building name + neighborhood inline (font-weight 800 + muted), address with `String(listing.unit).replace(/^#+/, '')` so units already-prefixed with `#` don't double up, badge row: type pill, `✂ −$XK` price-cut amount badge, days-badge, "Built YYYY" chip, plus the W3 stale pill and W7 off-market badge.
2. **Price + stats** (`.v4-price-stats`) — `$X.XXM` (font-size 22, weight 800) with "↓ from $Y.YYM" trend (red) inline, monthly all-in below, then a muted sub-line `Fees/mo $X,XXX · N%` (`.v4-fees-sub`, 11px, #888; omitted for rentals and pass1-only). Right column: bed/bath, sqft/$psf, `±N% $/ft² vs shortlist` delta (green when cheaper than the shortlist median, red when more expensive). Pass1-only listings render `—/mo all-in` with a "pending Pass 2 data" tooltip; no math is changed in `calcMonthlyTotal`.
3. **OQ block** (`.v4-oq`) — `#F5F8FD` blue tint. OQ label + numeric-only rank input + `Saved ✓` flag in a row, always-visible auto-growing notes textarea below.
4. **RQ block** (`.v4-rq`) — `#FDF6F3` coral tint. Same structure.
5. **Utility row** (`.v4-utility`) — labeled `[👁 Seen]` button on the left (32px-tall bordered, blue tint when `.is-seen`), `View on StreetEasy ↗` on the right.

**Cut from the previous card:** Inbox/Shortlist/Archive button cluster (swipe at `initCardSwipe` line 2316 replaces it), built-year cell in stats row (promoted to a badge), per-card mortgage rate/term display (already global in the header), agent contact action buttons (never used from cards), footer "Yorkville" duplicate (already in header).

**Helpers** (defined near the other render helpers, all pure):
- `priceCutAmount(listing)` — returns `{absolute, percent, priorPrice}` from peak ask in `price_history` vs current `price`, or null when no cut.
- `psfDeltaVsShortlist(listing)` — returns an integer percent vs `shortlistPsfMedian()`. The median is memoized on a key built from shortlist member IDs + their $/ft² sum, so filter changes invalidate correctly. Returns null on empty shortlist or rentals; call site omits the line.
- `seenIconSvg()` — inline 16×16 outline eye SVG with `stroke="currentColor"`. Consumed by both `renderCards()` and `renderTable()`.
- `autoGrowTextarea(el)` — sets `style.height = 'auto'; style.height = scrollHeight + 'px'`. Wired after `container.innerHTML` and on each textarea's `input` event. CSS `min-height` floors the empty state (52px desktop, 56px mobile).

**Numeric-only rank inputs:** OQ/RQ use `type="text" inputmode="numeric" pattern="[0-9]*" maxlength="3"` plus `oninput="this.value = this.value.replace(/\D/g, '')"`. Mobile keypad shows digits only; paste of non-numeric becomes empty; saveCardRank validation still enforces `val >= 1` server-side.

**What's untouched by v4:** `initCardSwipe`, `debounceNote`, `saveCardRank`, `putStatus`, `toggleSeen`, `transitionBucket`, `getStatus`, `_phCache`, `calcMonthlyTotal`, `stalePillHtml`, `offMarketBadgeHtml`. The swipe gesture handler at line 2152 already bails on touchstart inside `input, textarea, a, button, .seen-toggle, .rank-val` — the new textareas inherit that protection for free.

## Status Feature Architecture (Sessions 13–21)

**Backend deployed, frontend partially built. Major design pivot in Session 21:**
replaced the six-status pill cycling + watch toggle with a **three-bucket triage
system** (Inbox / Shortlist / Archive). Read `STATUS-FEATURE.md` for the full
spec and `STATUS-BACKEND-WALKTHROUGH.md` for the build guide.

- **Backend (MIGRATED, LIVE):** FastAPI on Python 3.12 + asyncpg + Railway
  managed Postgres. `api/` directory. Two tables: `listing_status` (current
  state) and `listing_status_history` (append-only audit log, populated by
  `listing_status_audit_trg` trigger on bucket change). No auth (CORS-restricted
  to `streethard.omarqari.com`). **Columns on listing_status:** `bucket`
  (inbox/shortlist/archive), `bucket_changed_at`, `price_at_archive`,
  `oq_rank`, `rq_rank`, `oq_notes`, `rq_notes`, `chips`, `seen` (boolean,
  visited in person), `updated_at`. Old `status` and `watch` columns dropped.
  Two SQL paths: `UPSERT_SQL` (normal) and `UPSERT_WITH_RANK_CLEAR_SQL`
  (clears ranks on shortlist exit). **Audit log endpoint:** `GET /history`
  with optional `?listing_id=` and `?limit=` (default 500, max 5000).
- **Frontend (MVP COMPLETE):** Two-fetch merge ✅. OQ#/RQ# rankings
  (click-to-edit, nulls-last) ✅. OQ/RQ Notes (debounced) ✅. Tab navigation
  with badge counts (T1) ✅. Transition buttons (T2) ✅. Auto-resurrection on
  price drop (T4) ✅. URL hash routing ✅. Sort defaults per tab (T6) ✅.
  Settings panel removed (Session 26) — no API key needed. Seen toggle
  (Session 28) ✅ — eye icon per row + filter checkbox.
  **Not yet built:** Offline outbox (T8), chips (T10). T9 card view: complete (Session 33).
- **Three-Bucket Model:** Inbox = untriaged (cron drops here). Shortlist =
  actively pursuing (has OQ/RQ). Archive = rejected (auto-resurrects on price
  drop). OQ/RQ cleared server-side on exit from Shortlist. URL hash for tab state.
- **Domains (Session 18):** `streethard.omarqari.com` (app), `api.streethard.omarqari.com` (API). Spaceship registrar.
- **Cron unaffected.** New listings have no status row → implicitly in Inbox.
- **Auth:** None. Write auth removed in Session 26. All endpoints are
  public; CORS restricts browser writes to `streethard.omarqari.com` origin.
- **Cost:** $5/mo Hobby tier on Railway.

Next session: **T10 chips**, **product backlog selection** from PRODUCT-BACKLOG.md.
See TASKS.md for acceptance criteria A1–A10.

## Buildings Targeting Feature (Session 44, LIVE)

Mark "great buildings" once; every listing in them gets highlighted across all
buckets. Full spec + 3-hat review in `BUILDINGS-FEATURE-PLAN.md`.

- **`buildingKey(s)` in `index.html`** is the canonical building identity and the
  **DB primary key** for targets. Conservative normalizer (ordinals,
  directionals, suffix-spelling — never strips Street/Ave/Place; `NNN Park` ===
  `NNN Park Avenue`). **FROZEN behind a unit test** (327→322 distinct, only the 5
  known spelling groups merge). Changing it orphans existing target rows — any
  change needs a one-time re-key migration. Same function does aggregation
  (`buildBuildingIndex`) and highlight (`isTargetBuilding`).
- **Backend:** `building_targets` table (building_key PK, display_name, note,
  timestamps) on the same Railway Postgres. `GET /building-targets`,
  `PUT /building-targets/{key}` with `{targeted, display_name?, note?}` —
  `targeted:false` DELETEs the row. No auth/audit. One **shared** family list
  (not per-person). Table SQL is plain statements (survives main.py's `$$`
  cold-start splitter).
- **Frontend:** Buildings is a 4th tab, **right-aligned past a divider** — NOT a
  `currentBucket` value. `currentTab` ∈ {inbox,shortlist,archive,buildings};
  buildings mode is a `body.mode-buildings` CSS class that swaps listing chrome
  for `#buildings-view`. Targeting is **Buildings-tab-only**; the main-app
  highlight (`tr.target-bldg` / `.listing-card.v4.target-bldg` + `★ Target` pill)
  is read-only. `loadBuildingTargets()` is the 3rd fetch in `loadData` and
  tolerates API failure (nothing highlighted, app still works). Hash `#buildings`
  routes to the tab.

### Building proper-names (`building_name`, Session 44)
- Many buildings have a name ("The Seville" = 300 E 77th). The dedicated
  actor field `building_name` is always null; the name lives in the actor's
  **`slug`** field. `deslugify_building_name(slug)` in `pull.py` derives it.
  **Rule:** a real name slug starts with a **letter** (`the-seville`,
  `bristol-plaza`); an address slug starts with the **street number**
  (`135-east-74th-street`, `530-park-avenue-new_york`) → suppressed (None), since
  the address already shows. (The trailing `-new_york`/`-nyc`/`-manhattan` rule
  alone was NOT enough — addresses take many slug forms.) Both normalizers emit
  `building_name`; merge persists it; `generate_latest` carries it through.
- **173 listings / 87 buildings** are named (backfilled 2026-06-15 via
  `scripts/backfill_names.py`, phased `--submit`/`--collect`). The frontend shows
  `building_name || building` as the primary label (Buildings tab, table rows,
  cards) with the address on the subline; search matches `building_name` too.
- New listings get names automatically going forward (slug captured in
  Pass 2). To re-backfill after a normalizer change: `rm /tmp/bf_processed.json`
  then `--submit 600` / `--collect`.

## Current Infrastructure State

- Running Claude in Cowork mode — Claude calls APIs directly, no config files to edit
- **Status API: LIVE on Railway** — `https://api.streethard.omarqari.com`. FastAPI + asyncpg + managed Postgres. Hobby tier ($5/mo). All endpoints operational: `/health`, `GET /status`, `PUT /status/{id}`, `POST /status/batch`. No auth — CORS-restricted to `streethard.omarqari.com`. **Recovered from Railway US East outage 2026-05-21** — Postgres crash-loop resolved by using Redeploy (not Restart) via the three-dot menu on the Deployments tab; streethard then redeployed and health endpoint confirmed `{"ok":true,"db":"connected"}`. See CHANGELOG for full recovery sequence. **Recovery lesson: if Postgres crash-loops and Restart doesn't hold, use Redeploy** — it re-provisions on fresh infrastructure rather than restarting on a broken host.
- **DNS: migrated to Spaceship, PROPAGATED** (Session 18, 2026-05-02; confirmed Session 23). Nameservers switched from Namecheap to Spaceship (`launch1.spaceship.net`, `launch2.spaceship.net`). Custom records: `streethard` CNAME, `api.streethard` CNAME, `_railway-verify` TXT, `www` CNAME (LinkedIn redirect). Both custom domains verified working with HTTPS (Session 23). DNS cutover cleanup completed (Session 24): `ALLOWED_ORIGIN_FALLBACK` removed from Railway, "Enforce HTTPS" enabled on GitHub Pages.
- **www.omarqari.com redirect:** GitHub Pages repo `omarqari/www-redirect` serves a meta-refresh redirect to `https://www.linkedin.com/in/oqari/`. Will go live when DNS propagates.
- **Primary data source: Apify `memo23/streeteasy-ppr`** — Pass 1 WORKING as of Session 43 (2026-06-14). The earlier "intermittent" behavior was never proxy IP rotation; it was StreetEasy's PerimeterX layer soft-throttling the shared session (fake-200s with shrunken/empty result sets). memo23 fixed it with a managed-unblocker/Scrape.do backup path + explicit `SEARCH_HEALTH_WARNING` signal; see the Session 43 db.json-state line above and CHANGELOG Session 42/43. Pass 2 for sales is fully fixed (Session 19): memo23 patched `/sale/{id}` to pull financials from non-PX-blocked source. Pass 2 for rentals went through three iterations: memo23 added the `rentalCombineResponse_rental_*` bypass on 2026-05-10, then on 2026-05-12 flipped the whole response to flat top-level keys (no namespace prefix). Session 34 (2026-05-14) updated both `normalize()` and `normalize_rental()` to read the flat schema: `on_market_at` / `onMarketAt` for listed_date, `propertyDetails_address_street` / `propertyDetails_address_displayUnit` / `propertyDetails_bedroomCount` / `propertyDetails_fullBathroomCount` / `propertyDetails_halfBathroomCount` / `propertyDetails_livingAreaSize` for rental address/unit/beds/baths/sqft, `pricing_price` for rent, and `propertyHistory_json[0].rentalEventsOfInterest` (with status→event mapping) for price history. Normalizers retain all prior-schema fallback chains so older listings keep deserializing. Known new-schema gaps not fixable on our side: rentals no longer return per-agent contact (only firm via `sourceGroupLabel`) and no `neighborhood` field. **Rental Pass 2 FIXED (Session 39, 2026-05-21):** memo23 patched two stacked issues — PerimeterX had expanded to block `/rental/{id}` HTML pages from the residential IP pool, and the actor's curl wasn't following 308 redirects (`/rental/{id}` → `/building/...`). Both resolved. All 76 rentals now at pass2; new rentals will upgrade normally via cron.
- **Pass 1 URL filter: `beds:3-` (W1, 2026-05-09)** — replaced `sqft:1500-` after a StreetEasy filter-behavior change around 2026-04-22 caused null-sqft co-ops to drop out of Pass 1 results. `beds` is universally published; this filter is robust to that failure class.
- **Auto-delisting: DISABLED (W2, 2026-05-09)** — `detect_delistings()` retired. Pure absence-from-Pass-1 is too noisy to flip a status flag from. Replaced by W3 (per-listing stale pill) + W7 (definitive Pass 2 verification for shortlists).
- **Pass 1 cliff guard (W5)** — `pull.py` aborts the merge if today's Pass 1 count drops to <50% of the 7-day median; warns at <75%. `--force-merge` bypass available for legit market shifts. Records `status: 'abort'` in `pipeline_health.json` so the cliff is visible in the in-app strip.
- **Pipeline: Incremental ("Puzzle" model) with resilience guards** — `data/db.json` is the canonical store. Each cron run discovers new listings via Pass 1 and fills in detail via Pass 2 (capped at 100/run). See PROJECTPLAN.md for full architecture.
- **db.json state (Session 43, 2026-06-14):** 513 active listings (382 sale, 131 rental, 0 delisted). **511 at pass2 quality, 2 pass1, 0 partial.** A remaining pass1 is the known 243 East 77th Street #PHA duplicate. Cron running cleanly 4×/day (every 6h, since Session 43). **Session 42→43: the June Pass-1 outage (PerimeterX soft-throttle) was fixed by memo23 ~2026-06-14; actor is working via a managed-unblocker/Scrape.do backup path. Jun 13/14 cron both pulled the full 207 sale set.** Session 43 swept all stale listings (last_pass1 >7d) through Pass 2 via `scripts/stale_refresh.py` — 241 refreshed, 13 sale price cuts surfaced. **W8 hardening:** `check_pass1_coverage` now seeds its baseline only from `status=='ok'` days (June throttle days had polluted it), Jun 10/11/12 relabeled `degraded` in pipeline_health.json, and `detect_search_health_warning()` aborts the merge on memo23's explicit `SEARCH_HEALTH_WARNING` signal. **Single-vendor dependency on memo23 is an accepted decision, NOT an open follow-up — do not propose evaluating a backup actor (Omar, Session 43: "it's this one or the project is dead").** 24 misclassified listings manually patched across Sessions 36–37 (see normalize() misclassification note below).
- **normalize() misclassification (SELF-HEALING as of Session 37):** The actor sometimes returns `"condo"` for listings that are actually co-ops, condops, or houses. **Session 36 fix:** the condo path in `normalize()` now falls back to `old_maint` when `maint_fee` is None, preserving maintenance fees for misclassified co-ops/condops. **15 listings patched in Session 36.** **Session 37 gap discovered:** the Session 36 fix preserved the `maintenance` field but did NOT correct the `type` field — `calcMonthlyTotal` still used the condo path (zeroing fees). **Session 37 final fix (commit `bad6cb7cda`):** the condo path now also sets `ptype = "coop"` when the fingerprint matches (`old_maint > 0`, `fees is None`). Future misclassified co-ops self-heal on re-ingestion without manual intervention. **24 listings manually patched across Sessions 36–37.** **Sweep query to catch any remaining regressions:** `[v for v in listings.values() if v.get('type')=='condo' and v.get('maintenance') and not v.get('monthly_fees')]`. Houses have no common charges — `calcMonthlyTotal`'s condo path handles them correctly (`monthly_fees||0 + monthly_taxes||0`). Townhouse taxes are not returned by the actor at all; must be patched manually.
- **Secondary: RapidAPI NYC Real Estate API** — validated YELLOW, 25 req/mo free tier, good for fast single-listing lookups; no price history or agent contact
- RapidAPI key in `.env`; Apify account on paid plan
- No PLUTO, ACRIS, or other supplemental data downloaded yet

### Resilience Guards in `pull.py` and `refresh.yml` (added 2026-05-02)

- **Pass 1 sentinel guard** in `pull.py` — when the actor returns only placeholder rows shaped like `{message: "No results found", urls_json, timestamp}` (no `id`/`listingId`/`node_id` on any item), the script `sys.exit(1)` before merge or save. Without this, the silent failure mode produced cron commits reading "373 listings, $0.06" while actually capturing zero new data — masked a 12-day gap on the Apr 23/27/30 cron runs. **(D-G1, Session 35)** Before exiting, the guard now logs `{date, pass1_*, active, status: 'abort'}` to `pipeline_health.json` so sentinel-aborted days appear as red rows on the diagnostics W5 table instead of being invisible.
- **`get_run` retry on transient 5xx** — Apify's API occasionally returns 502/503/504 during status polling. The client now retries with exponential backoff (1s, 2s, 4s, 8s) before raising. A single transient blip during a long Pass 2 run no longer kills the whole pipeline.
- **Pass 2 batch loop catches `requests.RequestException`** alongside `ApifyRunError`. Affected listings remain at `data_quality=pass1` and re-queue automatically on the next run.
- **`refresh.yml` commit step uses `if: success() || failure()`** so Pass 1 progress that was already saved survives a Pass 2 crash. The existing `git diff --cached --quiet` check still no-ops on truly empty runs.
- **`refresh.yml` commit message uses `.get()` fallbacks** for `listing_count` and `run_cost_usd` from `latest.json` — guards against KeyError when pull.py aborts before regenerating that file (sentinel abort case).
- **`refresh.yml` uses `git pull --rebase origin main` before `git push`** — prevents push rejection when a manual commit lands on main during a run (e.g. docs pushes from a Cowork session running concurrently with the cron).

## Git Operations from Claude Code (Mobile and Web)

**DO NOT use `git push/commit/pull/stash` from the sandbox.** Claude Code (mobile and web) routes all git write operations through a local proxy (`127.0.0.1:42269`) which returns 403 — it is not authenticated for pushes. This is a fundamental sandbox constraint, not a config issue. Additionally, git write commands create `.lock` files owned by the sandbox process; when the session exits, those locks persist and block future sessions. Validated across Sessions 24–25.

### Push method priority (use in order)

**1. GitHub MCP server (preferred — works in every Claude Code session, no credentials needed)**

The `mcp__github__push_files` tool is pre-wired in Claude Code sessions and bypasses all local git issues. Use it for all file pushes:

```
mcp__github__push_files(
  owner="omarqari", repo="streethard",
  branch="<current branch>",
  message="commit message",
  files=[{"path": "index.html", "content": "<full file content>"}]
)
```

Always detect the current branch first via `git rev-parse --abbrev-ref HEAD` (read-only — safe in sandbox). Push to that branch, not blindly to `main`.

**2. `scripts/git_push.py` (fallback — requires `.env` with GITHUB_TOKEN)**

When `.env` is present (typically desktop sessions), this script pushes via the GitHub REST API:

```bash
python3 scripts/git_push.py "commit message" [file1] [file2] ...
# Omit files to auto-detect changed files via git status
# Uses current branch automatically (no --branch flag needed for most cases)
# Override: python3 scripts/git_push.py "msg" --branch main file1
```

The script auto-detects the current branch from `git rev-parse --abbrev-ref HEAD`. It reads `GITHUB_TOKEN` from `.env`.

### Reading remote state

Use `curl` against the GitHub API or read files directly from the mount. Reads are safe — only write operations break.

```bash
# Read a remote file without git pull:
curl -s -H "Authorization: token $TOKEN" \
  "https://api.github.com/repos/omarqari/streethard/contents/path/to/file" \
  | python3 -c "import sys,json,base64; print(base64.b64decode(json.load(sys.stdin)['content']).decode())"
```

For pulling remote changes: ask the user to run `git pull` from their Terminal (not from the sandbox).

### Bringing local up to date at session close

Because all pushes go via the GitHub API (bypassing local git entirely), the local working tree accumulates unstaged changes that block a normal `git pull`. **Never tell the user to run `git pull` alone** — it will always fail with "Please commit your changes or stash them before you merge."

The correct command to give the user at session close is always:

```bash
git fetch origin && git reset --hard origin/main
```

This discards local state and syncs to exactly what's on remote. It is always safe because every file change was already pushed via `git_push.py` or `mcp__github__push_files` before this step.

### Token rules
- Never print, log, or echo the token value
- Never write the token to any file other than `.env`
- Never store the token in memory files, CLAUDE.md, or chat
- The token is scoped to the `streethard` repo only (Contents read/write). **Does NOT have `actions:write`** — cannot trigger `workflow_dispatch` programmatically. To enable that, Omar must add `actions:write` to the token at GitHub → Settings → Developer settings → Fine-grained tokens. Until then, manual runs must be triggered via the GitHub Actions UI.
- Token expires every 90 days; if auth fails, ask the user to rotate it at GitHub → Settings → Developer settings → Fine-grained tokens
- **Never run `git commit`, `git push`, `git pull`, `git stash`, or any write-mode git command against the mounted .git directory**

## Days-on-Market — Field Reliability

`days_on_market` from the actor is **systematically unreliable** (validated 2026-05-02 across all 367 listings: 90.5% undercount, 9.5% overcount, worst case off by 123 days, 0% match). Do NOT compute "days listed" or NEW badges from this field.

**Use `listed_date` instead.** It matches the most recent `LISTED` event in `price_history` for 99.7% of listings. The app computes days client-side via `daysListed(listing)` in `index.html` (drops fallback to `days_on_market` — returns null instead, which renders as "—").

When backfilling pass1 listings, always populate `listed_date` from the price-history JSON's most recent `LISTED` event so badges work correctly.

## How to Contact memo23 (Apify Actor Author)

When the Apify actor breaks or needs a feature, the fastest path is the Apify console issues thread:

1. Open `https://console.apify.com/actors/ptsXZUXADV3OKZ5kd/issues/a2fptiipUUxfjnh9X` in browser (Omar's Apify account is logged in on his browser)
2. Find the textarea with `id="text"` and `placeholder="Leave a comment"`
3. Fill it and click the `button[type="submit"]` labelled "Add comment"
4. Claude can do this via `mcp__Claude_in_Chrome__javascript_tool` — set value via `HTMLTextAreaElement.prototype` native setter + `dispatchEvent(new Event('input', {bubbles:true}))`, then click submit

**Backup:** email `muhamed.didovic@gmail.com` (actor README). Average issues response: 3.6 hours.

**Do NOT use the public-facing `apify.com` issues page** — the "Add comment" link there redirects to the console, and the public page has no textarea when not logged in.

## Files in This Project

- `CLAUDE.md` — this file; orientation for Claude
- `CHANGELOG.md` — chronological record of project events
- `PROJECTPLAN.md` — strategy, architecture, phases
- `TASKS.md` — concrete next steps
- `RETRO-SESSION9.md` — CTO/Architect/CPO retrospective on the backfill lesson
- `SQFT-METHODOLOGY.md` — co-op sqft estimation method, validation, failure modes (Sessions 10–11)
- `STATUS-FEATURE.md` — design spec for in-app listing-status tracking (Session 13, refined Session 14, custom-domain update Session 16)
- `STATUS-BACKEND-WALKTHROUGH.md` — CTO build guide for the FastAPI+Postgres status backend on Railway (Session 15, custom-domain update Session 16)
- `PRODUCT-BACKLOG.md` — CPO slate of 14 proposed product improvements, themed by Decision Quality / Data Quality / UX / Signal & Noise / DD Integration / Automation, plus open decisions awaiting user selection (Session 17, 2026-05-02)
- `PIPELINE-RESILIENCE-PLAN.md` — 7-workstream plan written 2026-05-09 in response to the false-flag delisting incident. Phase 1 (W1+W2) stops the bleeding; Phase 2 (W3–W5) makes the pipeline observable; Phase 3 (W6–W7) protects user triage investment. Rec D (broader pull) explicitly excluded.
- `CARD-REDESIGN-PLAN.md` — build plan for the Card View v4 redesign (Session 33). Records the intent (architect/CTO-reviewed plan v2) plus a "What actually shipped" addendum capturing every divergence from plan to ship.
- `data/db.json` — canonical listing store (the source of truth; never overwritten destructively)
- `data/latest.json` — generated from db.json for the app to consume
- `data/YYYY-MM-DD.json` — dated snapshots for badge diffing
- `scripts/pull.py` — incremental Apify pull script
- `scripts/git_push.py` — push to GitHub via REST API (avoids sandbox git lock issues)
- `scripts/rental_backfill.py` — targeted rental Pass 2 backfill (two-phase: `--start` submits run, `--finish RUN_ID` polls + merges); use when rentals accumulate at pass1 after an actor outage
- `scripts/stale_refresh.py` — stale-listing Pass 2 refresh sweep (Session 43). Re-prices listings that aged out of the Pass 1 search sample and runs W9 off-market detection. Phased `--submit`/`--collect` for the sandbox (Cowork kills detached processes); `--run [--cap N]` end-to-end elsewhere. The cron calls `--run --cap 60` after each pull (4×/day) to keep prices + off-market flags current across the whole Inbox.
- `index.html` — StreetHard app shell (family-facing)
- `diagnostics.html` — operator-only ops page (Pass 1 coverage, W5 cliff guard, pass1/pass2 split, search URLs); reachable via tiny gray footer link in the main app
- `api/main.py` — FastAPI status backend (all endpoints)
- `api/db.py` — asyncpg connection pool
- `api/schema.sql` — listing_status table DDL
- `api/requirements.txt` — Python dependencies for the API
- `api/railway.toml` — Railway deployment config
- `.env` — local env vars (RAPIDAPI_KEY, APIFY_TOKEN, GITHUB_TOKEN, STATUS_API_URL)
- `floorplans/` — gitignored scratch directory; user drops floor plan images here for sqft estimation
- `floorplans/processed.json` — tracks which floor plan images have been estimated vs. new; keyed by filename
- `skills/floorplan-estimator/SKILL.md` — skill for processing floor plans: scan, estimate, validate, update db.json, push
- `skills/floorplan-estimator/scripts/estimate_sqft.py` — pixel-polygon computation script (bundled with skill)

## Co-op SqFt Estimation

NYC co-ops don't publish official sqft. We estimate from floor plans using
the **pixel-polygon method**: detect the apartment polygon (largest
connected non-white blob, with morphological closing), calibrate the
pixel-to-feet scale from one labeled rectangular room, divide. Validated
to ~2% accuracy on well-behaved plans, ~5% on noisier ones. Full
methodology, accuracy bench, and failure modes in `SQFT-METHODOLOGY.md`.

### Data fields for estimated sqft

When sqft is not officially published, set on the listing in db.json:

- `sqft_estimated: true` — flag that triggers gray rendering in the app
- `sqft_estimate_method` — `"pixel_polygon"` or `"floorplan_sum"` (for the
  earlier eyeball-based Method 1 estimate)
- `sqft_estimate_note` — human-readable string shown in tooltip; should
  document the calibration room and any sanity-check overrides
- `price_per_sqft` — recompute as `round(price / sqft)` whenever sqft
  changes

### App rendering

CSS class `.estimated` (gray `#9aa0a6`, dotted underline, cursor: help)
is applied to SqFt, Price/SqFt, and Pmt/SqFt cells whenever
`sqft_estimated: true`. The behavior is data-driven; new estimates
inherit it automatically with no app code changes.

### When to override the algorithm manually

Compute the implied $/sqft after estimating. UES residential trades in
roughly $900–$1,800/sqft. If the algorithm produces $/sqft outside
that band, something is wrong — usually multi-floor plan misdetection
or a calibration-room pixel-read off by ~25%. Fall back to a labeled-room
sum + walls estimate and document the override in `sqft_estimate_note`.

### Floor Plan Skill

The full estimation workflow is captured in `skills/floorplan-estimator/`.
When the user mentions floor plans, sqft estimation, or drops images into
`floorplans/`, read the skill's SKILL.md and follow it. The skill handles:
scanning for new images, matching to listings, running the pixel-polygon
script, validating $/sqft, updating db.json, tracking processed files in
`floorplans/processed.json`, and pushing to GitHub. The bundled script at
`skills/floorplan-estimator/scripts/estimate_sqft.py` does the computation;
Claude provides the calibration room measurements visually.

## Post-Schema-Fix Audit Rule — READ THIS AFTER ANY normalize() PATCH

**Any time `normalize()` or `normalize_rental()` is patched for a schema change, run a data quality audit before closing out.** Listings that were upgraded to pass2 under the broken normalizer will have empty strings (not None) for fields like `address`, `unit`, `neighborhood`. They won't be re-fetched by the normal pipeline because they're already marked pass2.

**Audit query to run after every normalize patch:**

```python
# Blank-address pass2 rentals (schema bug fingerprint)
[lid for lid, v in listings.items()
 if v.get('listing_type') == 'rent'
 and v.get('data_quality') == 'pass2'
 and not v.get('address')]

# Blank-address pass2 sales
[lid for lid, v in listings.items()
 if v.get('listing_type') == 'sale'
 and v.get('data_quality') == 'pass2'
 and not v.get('address')]
```

If either returns results, force a pass2 re-fetch on those IDs before pushing. This pattern burned us in Session 39: 12 rentals upgraded on 2026-05-10 under a broken normalizer had empty addresses for weeks until noticed in the UI.

## Bottom-Up Validation Rule — READ THIS BEFORE BUILDING ANYTHING

**Always validate from the smallest unit up before wiring components together.** This rule exists because we wasted significant time building and debugging a rental pipeline top-down, only to discover fundamental assumptions about how the Apify actor handles search URLs were wrong.

The pattern that worked (Sales, first time):
1. Pick one known listing. Get its ID from StreetEasy.
2. Hit the API/actor with that single URL. Dump the raw response.
3. Verify every required field is populated against ground truth (the actual StreetEasy page).
4. Only after that passes: test with a small batch (5–10 listings).
5. Only after that passes: wire into the full pipeline.

The pattern that failed (Rentals):
- Assumed "same actor, different URL" and skipped straight to full pipeline.
- Built normalization functions with guessed field names.
- Deployed untested code to GitHub Actions and iterated on live runs.
- Each failure was a 6-minute CI cycle with no visibility into the actual data.

**Concrete rules:**

Before building any new data source or pipeline step, Claude must:
1. **Test one item first.** Call the API/actor with a single known URL. Print the raw response in full. Don't write normalization code until the raw response is confirmed.
2. **Check field names from reality, not assumptions.** Never guess field names from a pattern (e.g., swapping `sale` for `rental` in a namespace). Field names must be read from an actual API response.
3. **Isolate before integrating.** Test Pass 1 independently. Test Pass 2 independently. Only combine them after both work in isolation.
4. **Never test architecture in CI.** GitHub Actions is for running validated code. It is not a debugging environment. If something is unvalidated, test it locally or via direct API call first.
5. **Don't add layers while one is broken.** If Pass 1 isn't returning IDs, don't add delta caching on top of it. Fix the broken layer first.

## Solve the Problem First, Then Automate — READ THIS BEFORE BUILDING PIPELINES

**Distinguish between "initial load" and "steady-state maintenance."** They are different problems requiring different solutions. Session 9 retrospective (RETRO-SESSION9.md) documents this lesson in full.

**The backfill lesson:** We spent sessions 2–8 building an incremental cron pipeline that fills ~30 listings per run. The initial database had 373 listings needing Pass 2. At 30/run, twice weekly, that's 6+ weeks to full data. In Session 9, we called the API directly in batches of 50–100 and completed the entire backfill in 15 minutes.

**Concrete rules:**

1. **Data completeness is a launch blocker, not a backlog item.** If the app's primary value (accurate monthly payments) requires Pass 2 data, then Pass 2 completion is P0. Don't ship with 97% of listings showing incomplete data and call it "v1."
2. **When the user can see the answer in 15 minutes, don't build a 6-week pipeline.** Always ask: "What's the fastest path to the user having what they need?" If the answer is "call the API directly," do that first, then build automation for maintenance.
3. **Don't confuse building the system with solving the problem.** A pipeline is infrastructure. The user's need is data. Solve the need directly, then automate the maintenance.
4. **Revisit defensive limits after outages are resolved.** Batch sizes and caps set during an actor regression should be re-evaluated once the actor is fixed. Don't let crisis-mode guardrails become permanent bottlenecks.
5. **Features on incomplete data are vanity work.** Text search, rental comps, and date formatting are nice — but not while 97% of sale listings lack fees, taxes, and agent contact.

**Operational modes:**
- **Backfill mode:** Call Apify directly from Cowork. No Pass 1. Read db.json for pass1-quality IDs, send through Pass 2 in batches of 50–100, merge results. For supervised use when bulk data population is needed.
- **Maintenance mode:** Cron pipeline (pull.py via GitHub Actions). Pass 1 discovers new listings, Pass 2 fills in details for new/changed listings. For unattended steady-state operation.

## Tone Guidance for Responses

Be direct. When the user asks "what's the best way to do X," give a ranked opinion with reasoning. When they push back, take it seriously and reassess rather than dig in. Admit mistakes cleanly. Skip the reflexive disclaimers.
