# CHANGELOG

All notable decisions and events on this project, in reverse chronological order.

---

## 2026-04-19 — Apify 403 Recurrence + Session Close (Session 4)

### Apify Actor Broken — StreetEasy iOS Key Rotated Again

Attempted to run Apify `memo23/streeteasy-ppr` for a single-listing validation test (Saratoga, ID 1818978). Both runs failed wall-to-wall with 403s — identical behavior to the issue resolved ~23 days ago.

- **Run ID: I1C7EFWK61Lfa8XW3** — free tier, all 403s
- **Run ID: aSmBOStZKpupB2Rs9** — after upgrading to Apify paid plan, still all 403s

Upgrading to paid plan ruled out proxy quota as the cause. Root cause: StreetEasy rotated their internal iOS app API key, which the actor uses for all requests. This is a recurring maintenance issue with this actor (prior occurrence: ~2026-03-27, resolved within hours by memo23).

The actor showed "Last modified: 2 hours ago" at the time of testing — memo23 may have already pushed a fix. A comment was posted to the existing GitHub issue thread alerting memo23, with both run IDs included.

### Apify Plan Upgraded

Upgraded Omar's Apify account from free to paid tier. This had no effect on the 403 issue but is required for production use (residential proxy access, higher concurrency).

### Official Validation Test Created

Created `APIFY_VALIDATION_TEST.md` — a reproducible one-listing test using 330 East 75th Street #28BC (The Saratoga, listing ID 1818978) as the canonical ground truth. Drop this into any future session to instantly verify the actor is working before running a full pull.

### Session State at Close

- Apify actor: **BROKEN** (403s, pending memo23 fix)
- GitHub Actions pipeline: **BLOCKED** (Pass 1 ID extraction bug from Session 3, plus actor broken)
- Comment posted to memo23's issue thread: ✅
- All docs updated: ✅

### Next Steps (start of next session)

1. Run the Saratoga validation test (`APIFY_VALIDATION_TEST.md`) to confirm the actor is fixed
2. Once confirmed, run the Pass 1 debug dump (trigger CI run, copy DEBUG lines, paste to Claude)
3. Fix `run_two_pass()` ID extraction logic based on debug output
4. First full UES production pull

---

## 2026-04-19 — Rentals Added (Session 3)

### Scope Expansion
Added UES rental listings ($10K–$20K/month, sqft ≥ 1,500) alongside existing sales. Primary motivation: rent-vs-buy comparison using the same neighborhood and size criteria.

### UI: Mode Toggle
Added a 3-way segmented control to the filter bar: **[ For Sale ] [ For Rent ] [ Both ]**. Behavior per mode:
- **For Sale**: existing behavior unchanged
- **For Rent**: mortgage calculator bar collapses; Ask Price column hidden; Price/SqFt blank (annualized $/sqft already covers the equivalent); Days Listed uses tighter rental thresholds
- **Both**: all listings shown with SALE/RENT badge per row; mortgage bar visible (affects sale rows only); Ask Price blank for rental rows

### Column Mapping Decisions
| Column | Rentals treatment |
|---|---|
| Monthly Pmt → "Monthly Rent" | `listing.price` = monthly rent directly |
| Ask Price | Hidden in rent-only; blank in Both |
| Price/SqFt | Blank for all rentals (annualized $/sqft is the equivalent) |
| PMT/SqFt | Direct equivalent: (annual rent) ÷ sqft |
| Days Listed | Tighter thresholds: NEW <3d, green 3–14d, yellow 14–30d, red 30d+ |
| Mortgage calculator | Collapsed in rent-only mode |
| Payment breakdown | Simplified to "Monthly Rent: $X" for rentals |

### Pipeline Changes
- `pull.py` refactored: new `run_two_pass(client, url, max_items, listing_type)` helper; new `normalize_rental()` with best-guess field names mirroring the sales schema (`rentalListingDetailsFederated_*` etc.); `--mode both|sale|rent` argument (default: both); `listing_type: "sale"|"rent"` field on every normalized record
- `refresh.yml`: replaced `--url` manual input with `--mode`; commit message now includes sale/rent counts
- `data/latest.json`: now contains both types merged; `sale_count` and `rental_count` added to payload metadata

### Rental normalize() Status
`normalize_rental()` uses best-guess field name prefixes. On first CI run, if rental normalization fails the existing debug dump will print the actual Apify field names. Update `normalize_rental()` accordingly (same process used for sales in Session 2).

### Bugs Found and Fixed (same session, post-merge CI run)

First CI run with new code (`--mode both`) revealed two bugs:

**Bug 1 — TypeError crash:** `run_two_pass()` early return (when Pass 1 finds < 10 IDs) returned `([], search_items)` where `search_items` is a list. Caller did `total_events += events`, crashing with `TypeError: int += list`. Fixed: return `len(search_items)` instead.

**Bug 2 — 0 IDs from 10 search items:** Pass 1 returned 10 items but extracted 0 unique listing IDs. Root cause unknown — items appear to lack explicit `id`/`listingId` fields AND URLs that match the regex `/(?:sale|rental)/(\d+)`. Added a debug dump (stderr) that fires when 0 IDs are extracted, printing the raw keys and all ID/URL-related fields of the first item. Next CI run will reveal the actual field structure.

---

## 2026-04-19 — Pipeline Debugging + Production Launch (Session 2)

### Problem: GitHub Actions Failing on Pass 2

- First CI run failed at "Run pull script" (1m 17s). Pass 2 returned 50 items but all were skipped with "no price" — guard clause triggered, `latest.json` not overwritten.
- Root cause: Apify `memo23/streeteasy-ppr` flattens StreetEasy's federated GraphQL API into flat top-level keys with long namespace prefixes. The actual price field is `saleListingDetailsFederated_data_saleByListingId_pricing_price`, not `price`, `pricing_price`, or `askingPrice` as the original `normalize()` assumed.
- The previous sparse `data/latest.json` (prices but no addresses/agent/history) had come from Pass 1 search results, which do use a simple `price` field — masking the mismatch.

### Fix 1: Debug Output + Pass 1 Fallback

- Added raw field key dump to stderr when all Pass 2 items fail normalization.
- Added automatic fallback to Pass 1 (search result) data if Pass 2 yields fewer than `MIN_LISTINGS`. Prevents the workflow from aborting completely while the normalize bug exists.
- Fallback triggered for two CI runs during debugging; app stayed live with sparse-but-valid data.

### Fix 2: Rewrote normalize() with Actual Field Names

- Debug output from the first fallback run revealed the full Apify schema. Three key namespaces:
  - `saleListingDetailsFederated_data_saleByListingId_*` — pricing, beds/baths, sqft, address, unit
  - `saleDetailsToCombineWithFederated_data_sale_*` — building name, neighborhood, year built, days on market, contacts JSON, price history JSON
  - `extraListingDetails_data_sale_*` — richer price history JSON (includes `source_group_label`)
- Agent info: parsed from `contacts_json` (JSON string → array → first contact's name/phone/email/firm)
- Price history: parsed from `extraListingDetails_data_sale_price_histories_json` (JSON string)
- Co-op vs. condo split: `pricing_maintenanceFee` = HOA for condos, full maintenance for co-ops; `pricing_taxes` = 0 for co-ops (included in maintenance)
- Pass 1 simple field names retained as fallbacks so normalize() works on both schemas

### Result: Full Data Coverage

After fix: 50 normalized, 0 skipped. Field fill rates:

| Field | Coverage | Notes |
|---|---|---|
| price, beds, baths, type | 50/50 | |
| address, building, unit | 50/50 | |
| year_built, days_on_market | 50/50 | |
| agent name/phone/email | 50/50 | |
| price_history | 50/50 | |
| sqft | 26/50 | Co-ops routinely omit sqft on StreetEasy — not a bug |
| monthly_fees + maintenance | 50/50 | Correctly split by type |

### Search Criteria Expanded to Production Range

- Removed test ceiling ($4M) and floor (none) — first production pull revealed sub-$1M 1-bedroom co-ops appearing because StreetEasy's `sqft:1500-` filter only excludes listings that explicitly have sqft listed below 1,500; listings with no sqft bypass it entirely.
- Set `$2M–$5M` as production range. $2M floor eliminates the noise; $5M ceiling is user preference.
- Production URL: `https://streeteasy.com/for-sale/upper-east-side/price:2000000-5000000%7Csqft:1500-`

### All Code Merged to Main

- Feature branch `claude/explore-project-V2hAM` merged to `main`. Weekly cron now runs from `main`.
- UI verified correct with rich data: price history, agent contact, payment breakdown all render properly.

---

## 2026-04-19 — Project Kickoff

### Discovery

- User posed initial question: what is the best way to ingest active NYC residential real estate listings data for homes for sale in Manhattan, with priority on price, historical list/sold prices, sqft, address, and year built.
- Claude's initial response covered the full NYC data landscape: REBNY RLS, StreetEasy, Zillow, third-party commercial APIs (ATTOM, RentCast, CoreLogic, HouseCanary), NYC Open Data (PLUTO, ACRIS, Rolling Sales), and the open-source `nyc-db` project.
- Architecture recommendation at this stage was overbuilt for the actual use case.

### Scope Correction

- User clarified: this is not a commercial project. Goal is to purchase one apartment in Manhattan for their family.
- Claude reassessed and repositioned the recommendation around an n=1 pragmatic approach: use StreetEasy + CitySnap as the primary browsing UI, run 15-minute free NYC Open Data lookups per serious candidate (HPD Online, DOB NOW, ZoLa, ACRIS, PLUTO), and engage a real estate attorney for contracts.
- Called out building-level financial risk (reserves, assessments, litigation) as the biggest gap no public dataset covers.
- Flagged NYC-specific gotchas: co-ops invisible in ACRIS at unit level; PLUTO aggregates condos to building level.

### Ingestion Path Decision

- User pushed back: still wants to pull data for personal analysis, even if imperfect.
- Claude surveyed options: Apify marketplace (`qwady/Borough`, `jupri/streeteasy-scraper`, `memo23/apify-streeteasy-cheerio`, `scrapestorm`, `shahidirfan`, `getdataforme`), RapidAPI providers, ScrapingBee, DIY DevTools replay of StreetEasy's internal GraphQL, Zillow Bridge API.
- Recommendation: start with Apify's `qwady/Borough` actor (free tier, purpose-built for NYC, explicit refresh cadence), fall back to `jupri` or `memo23` if field completeness is thin.

### RapidAPI Path Surfaced

- User raised `rapidapi.com/realestator/api/nyc-real-estate-api`.
- Claude confirmed the `realestator` provider also publishes `streeteasy-api` on RapidAPI; both are unofficial StreetEasy scrapers wrapped in an API.
- Recommendation: bake off RapidAPI free tier vs. Apify `qwady` free tier with the same query; pick the one whose JSON has `priceHistory`, `sqft`, and `yearBuilt` most reliably populated.

### RapidAPI Key

- User shared an MCP configuration block from RapidAPI Hub (from Chat session). That config format is irrelevant in Cowork — Claude calls the API directly via HTTP.
- User's live RapidAPI API key was embedded in that config; user decided not to rotate immediately (free tier, no payment info on file). Will rotate after validation.
- Auth headers: `x-api-key` and `x-api-host: realestator.p.rapidapi.com`.

### Migration to Cowork

- Work started in Claude Chat by mistake; user moved to Cowork and imported project context.
- In Cowork, Claude calls APIs directly — no MCP config files, no Node.js, no `claude_desktop_config.json` needed. All prior references to those have been removed from the project docs.

### Documentation

- Created `CLAUDE.md`, `CHANGELOG.md`, `PROJECTPLAN.md`, `TASKS.md` to persist project context and next steps.

---

## 2026-04-19 — Pre-Build Decisions Locked (CTO/CPO Review)

- **GitHub Actions guard**: `pull.py` exits with code 1 if listing count < 10; workflow fails without overwriting `latest.json`. Prevents a bad Apify run from nuking the live app.
- **Mortgage calculator placement**: Sticky bar directly below the main header — always visible while scrolling the table. Not in a modal or sidebar.
- **Mobile responsiveness**: Explicitly deferred to v2. v1 is desktop-only.
- Build begins.

---

## 2026-04-19 — Architecture: GitHub Pages + GitHub Actions + Client-Side Mortgage Math

- Decision: StreetHard will be hosted on **GitHub Pages** (free, zero ops) so the whole family can access it at a shared URL.
- Data layer: `data/latest.json` (overwritten each run) + `data/YYYY-MM-DD.json` (dated archives). JSON is raw Apify output — no pre-computation.
- Presentation layer: `index.html` is a static app shell. Fetches `data/latest.json` on load. All rendering and mortgage math runs client-side in JS.
- **Mortgage calculator is now interactive** — family can adjust down payment, rate, and term; all monthly payments recalculate instantly without a re-run.
- Automation: `.github/workflows/refresh.yml` runs a weekly cron (Sundays). Calls Apify, commits updated JSON, GitHub Pages auto-deploys. Apify token stored as GitHub Secret.
- All project docs (PROJECTPLAN, TASKS, CLAUDE) updated to reflect this architecture.

---

## 2026-04-19 — Output Format Changed to HTML App (StreetHard)

- User decision: replace .xlsx spreadsheet output with a **self-contained HTML app named StreetHard**.
- App is single-file HTML with all CSS/JS/data embedded inline — open in any browser, no server.
- Design system: inspired by StreetEasy — dark navy header, white card layout, blue links, orange accent for highlights.
- Layout: dual-mode (Cards default + sortable Table toggle), inline filters (Beds, Type, Price, Monthly Payment), expandable Price History and Agent info per card.
- Days Listed color-coded: <30 green, 30–90 yellow, 90+ red.
- Project plan and tasks updated accordingly.

---

## Decisions Log (quick reference)

| Decision | Rationale |
|---|---|
| Scope is n=1 personal purchase, not commercial | User explicitly clarified |
| No commercial APIs (ATTOM, RentCast, etc.) | Overkill for n=1 |
| No REBNY RLS pursuit | Broker-gated, not accessible |
| Output: StreetHard HTML app (not .xlsx) | User decision; single-file, browser-ready, StreetEasy-inspired design |
| Primary: RapidAPI NYC Real Estate API, direct HTTP | Claude calls it directly in Cowork, no config needed |
| Fallback: Apify `qwady/Borough` actor | Free tier, NYC-specific, known refresh cadence |
| Supplemental: NYC Open Data (PLUTO, ACRIS) | Authoritative building + sales data, free |
| Run in Claude Cowork mode | Moved from Chat; Cowork can call APIs and write files directly |
| API key rotation deferred | Free tier, no payment info, will rotate post-validation |
