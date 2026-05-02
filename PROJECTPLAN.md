# PROJECT PLAN

## Goal

Purchase one residential apartment in Manhattan for the user's family, informed by data analysis on active listings and supporting NYC property records. The tooling will live as a shared family web app so all family members can browse and reference the same live data.

## Strategy

Build a lightweight personal web app (StreetHard) that supplements — rather than replaces — StreetEasy's already-excellent consumer UI. The app is a static site hosted on GitHub Pages, auto-refreshed weekly via GitHub Actions, and accessible to the whole family via a public URL. Mortgage math runs client-side so family members can adjust assumptions interactively. Supplement with free NYC government datasets for due diligence on serious candidates. Explicitly avoid over-engineering for a single purchase decision.

## Search Criteria

### For Sale
Active sale listings in the **Upper East Side**, Manhattan:

- **Sqft:** ≥ 1,500 (caveat: StreetEasy's `sqft:1500-` filter only excludes listings that explicitly have sqft listed below 1,500 — co-ops with no sqft recorded bypass the filter entirely)
- **Price:** $2,000,000 – $5,000,000
- **Geography:** Upper East Side (StreetEasy neighborhood slug: `upper-east-side`)
- **Status:** Active only

**$2M floor rationale:** Sub-$1M 1-bedroom co-ops appeared in the first production pull because the sqft filter doesn't catch listings with no sqft. The price floor eliminates the noise cleanly.

**$5M ceiling:** User preference as of 2026-04-19.

### For Rent
Active rental listings in the **Upper East Side**, Manhattan:

- **Sqft:** ≥ 1,500 (same caveat as sales — listings without sqft bypass the filter)
- **Monthly Rent:** $10,000 – $20,000
- **Geography:** Upper East Side
- **Status:** Active only

Added 2026-04-19 to support rent-vs-buy comparison. The `price` field for rental listings = monthly rent (not a purchase price); the app's `calcMonthlyTotal()` handles this by returning `listing.price` directly for rentals.

## App: StreetHard

### Hosting
- **GitHub Pages** — free, zero ops, auto-deploys on every push
- **Repo:** `github.com/omarqari/streethard` (public)
- **Canonical app URL (Session 16):** `https://streethard.omarqari.com` — custom domain on Spaceship → CNAME → `omarqari.github.io`
- **Fallback URL:** `omarqari.github.io/streethard` stays live during DNS propagation and as a backup
- **Status backend:** `https://api.streethard.omarqari.com` — Railway-hosted FastAPI + Postgres on a separate service. CNAME on Spaceship → Railway service. See `STATUS-FEATURE.md` for the full design and `STATUS-BACKEND-WALKTHROUGH.md` for the build guide.
- No server for the app itself — the static Pages bundle is the app, the Railway service only serves `listing_status`

### Data Refresh
- **GitHub Actions** cron job runs **Monday + Thursday, 9 AM UTC** (twice-weekly; fresh data mid-week and start of week)
- Workflow: call Apify → download results → save `data/latest.json` + `data/YYYY-MM-DD.json` → commit to repo → GitHub Pages auto-deploys
- Apify API token stored as **GitHub Secret** (never in code)
- Manual re-run available via GitHub Actions "Run workflow" button

### File Structure
```
/
├── index.html              ← StreetHard app shell (static, never changes per-run)
├── CNAME                   ← Pages custom-domain marker — contents: streethard.omarqari.com
├── data/
│   ├── db.json             ← Canonical store (puzzle model); never overwritten destructively
│   ├── latest.json         ← Generated from db.json each run for the app to consume
│   └── 2026-04-19.json     ← Dated archive of every past run
├── .github/
│   └── workflows/
│       └── refresh.yml     ← GitHub Actions cron (Mon + Thu)
├── scripts/
│   └── pull.py             ← Apify pull script (runs locally or in CI)
└── api/                    ← Railway service (FastAPI + Postgres) — Session 16
    ├── main.py             ← FastAPI app + routes
    ├── db.py               ← asyncpg pool
    ├── auth.py             ← X-API-Key middleware
    ├── schema.sql          ← One-shot DDL run at startup
    ├── requirements.txt
    ├── Procfile
    └── railway.toml
```

The `api/` subdirectory is wired to Railway via the "Root Directory" setting. The cron pipeline (refresh.yml → db.json) and the API service (Railway → Postgres) deploy independently.

### Architecture: Separation of Data and Presentation
- `index.html` is a **static app shell** — all UI logic, CSS, and mortgage math in JavaScript
- On load, the app fetches `data/latest.json` and renders it client-side
- Mortgage calculator runs **in the browser** — family can adjust down payment, rate, and term interactively without a re-run
- Raw Apify fields stored in JSON; all calculations (monthly payment, PMT/SqFt, etc.) computed in JS at render time

### Design System
Inspired by StreetEasy's visual language:
- **Header**: Dark navy background (`#0E1730`), white wordmark "StreetHard"
- **Accent**: Orange (`#FF6000`) for highlights and active states
- **Links / interactive**: Blue (`#3461D9`)
- **Body**: White background, clean layout
- **Typography**: System sans-serif (`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`)

### Core Layout: Table (default) + Cards toggle
- **Default view**: Sortable table — dense, comparison-optimized
- **Toggle**: Card view for a more visual browse experience
- **Default sort**: Monthly Payment descending
- **Inline filters**: Beds (All / 2+ / 3+ / 4+), Type (All / Condo / Co-op), Max Price, Max Monthly Payment
- **Row expansion**: Click any row to expand in-place — shows Price History, Agent info, Payment Breakdown
- **Mortgage calculator**: Sticky bar directly below the main header — always visible while scrolling. Inputs: Down Payment · Rate · Term. Any change instantly recalculates and re-sorts all rows. Defaults: $750k / 3.00% / 30yr.
- **Mobile**: Deferred to v2. v1 is desktop-only.

### Data Columns (Table view, in order)
| Column | Source | Notes |
|---|---|---|
| Building / Unit | `saleDetailsToCombineWithFederated_data_sale_building_title` + `saleListingDetailsFederated_data_saleByListingId_propertyDetails_address_unit` | |
| Monthly Pmt | Calculated in JS | Primary sort key; recalculates on mortgage input change |
| Ask Price | `saleListingDetailsFederated_data_saleByListingId_pricing_price` | |
| SqFt | `saleListingDetailsFederated_data_saleByListingId_propertyDetails_livingAreaSize` | ~50% coverage; co-ops routinely omit sqft on StreetEasy |
| Beds / Baths | `propertyDetails_bedroomCount`, `_fullBathroomCount`, `_halfBathroomCount` | Baths = full + (0.5 × half) |
| Price/SqFt | Calculated in JS | |
| PMT/SqFt | Calculated | `(Monthly × 12) ÷ SqFt` |
| Type | `saleDetailsToCombineWithFederated_data_sale_building_building_type` | Pill tag: Condo / Co-op |
| Yr Built | `saleDetailsToCombineWithFederated_data_sale_building_year_built` | |
| Days Listed | `saleDetailsToCombineWithFederated_data_sale_days_on_market` | Color-coded — see thresholds below |
| Cross Streets | — | Header present, values blank (not in API) |

### Days Listed Color Thresholds (calibrated for luxury Manhattan pace)
- **NEW** (blue badge): < 7 days
- **Green**: 7–44 days
- **Yellow**: 45–120 days
- **Red**: 121+ days

### Days-on-Market Calculation
`days_on_market` as scraped from Apify is a point-in-time snapshot and becomes stale immediately. The pipeline stores a `listed_date` field (ISO date string: `"2026-04-16"`) derived from the most recent LISTED event in price history (sales) or the `listed_at` timestamp (rentals). The JS app computes days-on-market live at render time:

```js
const dom = listing.listed_date
  ? Math.floor((new Date() - new Date(listing.listed_date)) / 86400000)
  : listing.days_on_market;  // fallback for listings with no price history
```

**TODO:** `index.html` still uses the static `days_on_market` field. Update `calcDaysOnMarket()` (or equivalent) to prefer `listed_date` when present.

### New Listing + Price Cut Badges (P1 — next sprint)
Surface signal that StreetEasy already shows but the app doesn't — without any extra API cost:

- **NEW badge** (blue): listing ID appears in current pull but not in the previous `data/YYYY-MM-DD.json`
- **PRICE CUT badge** (green): price decreased since previous pull

Implementation: during the `_save_partial()` / final write step in `pull.py`, compare current listing prices against the previous dated JSON. Add a `badge` field (`"new"`, `"reduced"`, or `null`) to each normalized listing before writing. `index.html` renders the badge as a pill in the Building/Unit column.

**Pending:** implement `badge` field in `pull.py` + badge rendering in `index.html`.

### Text Search
Free-text search input in the filter bar, between the mode toggle and the dropdown filters. Filters listings in real time (on every keystroke) by matching the query against a concatenated haystack of: `building`, `address`, `unit`, `neighborhood`, `agent_name`, and `agent_firm`. Case-insensitive substring match. Clears with the existing "Clear" button. Highlights with the same blue active-state styling as dropdown filters when non-empty. Expands from 180px to 240px on focus for comfortable typing.

### Expanded Row (click to open inline)
- Full price history event timeline
- "Never sold" / peak-ask warning if applicable
- Agent name, phone, email
- Payment breakdown: Mortgage + Common Charges + Taxes (or Maintenance for co-ops)

### Mortgage Calculator (client-side, interactive)
- Inputs displayed in the header or summary bar: Down Payment · Rate · Term
- Defaults: $750,000 down / 3.00% / 30 years
- Any change instantly recalculates and re-sorts all rows
- Formula: `M = P × [r(1+r)^n] / [(1+r)^n − 1]`
- **Co-op:** mortgage + maintenance only (maintenance includes taxes)
- **Condo/Townhouse:** mortgage + common charges + taxes

## Data Pipeline

### Primary Ingestion: Apify `memo23/streeteasy-ppr`
Pay-Per-Event actor, $3.00 per 1,000 results. Validated GREEN on 2026-04-19.

**Production URL** ($2M–$5M, sqft ≥ 1,500):
```
https://streeteasy.com/for-sale/upper-east-side/price:2000000-5000000%7Csqft:1500-
```

**Apify schema note:** The actor flattens StreetEasy's federated GraphQL API into flat keys with long namespace prefixes. Three key namespaces: `saleListingDetailsFederated_data_saleByListingId_*` (price, beds/baths, sqft, address), `saleDetailsToCombineWithFederated_data_sale_*` (building name, neighborhood, year built, days on market, contacts JSON, price history JSON), `extraListingDetails_data_sale_*` (richer price history JSON). Agent info parsed from `contacts_json`; price history from `extraListingDetails_data_sale_price_histories_json`.

Fields confirmed present (50/50): price, beds, baths, address, unit, building name, year built, days on market, HOA/common charges, taxes, price history (full event timeline), agent name/phone/email. SqFt: 26/50 (co-ops routinely omit sqft on StreetEasy — not a pipeline bug).

**Cost estimate for full UES pull:** ~500–800 listings → ~$1.50–$2.40 per run.

### Data Storage — Incremental Accumulation ("Puzzle" Model)

The Apify actor is brittle: Pass 2 times out, batches fail, some runs only get 10 out of 330 listings. The pipeline must accumulate data like filling in a puzzle — every successful scrape is saved permanently; future runs only fill in what's missing.

#### The Canonical Store: `data/db.json`

A persistent JSON file committed to the repo. This is the **single source of truth** for all listing data. Structure:

```json
{
  "listings": {
    "1818978": {
      "id": "1818978",
      "listing_type": "sale",
      "data_quality": "pass2",
      "last_pass1": "2026-04-20",
      "last_pass2": "2026-04-20",
      "price": 3295000,
      "building": "The Saratoga",
      "monthly_fees": 2448,
      "monthly_taxes": 3384,
      "price_history": [...],
      "agent_name": "Matthew Gulker",
      ...all normalized fields...
    },
    "1811080": {
      "id": "1811080",
      "listing_type": "sale",
      "data_quality": "pass1",
      "last_pass1": "2026-04-20",
      "last_pass2": null,
      "price": 4200000,
      "building": "530 Park Avenue",
      "monthly_fees": null,
      ...sparse fields...
    }
  },
  "last_updated": "2026-04-20",
  "stats": {
    "total": 414, "pass1_only": 324, "pass2_complete": 90,
    "sale": 330, "rent": 84
  }
}
```

Key fields per listing:
- **`data_quality`**: `"pass1"` (basic — price/beds/baths/sqft/address) or `"pass2"` (complete — fees/taxes/agent/price_history). This is the "puzzle piece" flag.
- **`last_pass1`**: Date this listing was last seen in a Pass 1 search. Used to detect delistings — if a listing hasn't appeared in Pass 1 for 14+ days, it's probably gone.
- **`last_pass2`**: Date Pass 2 detail data was last successfully fetched. `null` means never.

#### Run Logic (what changes)

Each cron run does:

1. **Pass 1 (search):** Same as today. Discovers all active listing IDs + basic data.
2. **Merge Pass 1 into db.json:** For each Pass 1 result:
   - **New listing?** Add it with `data_quality: "pass1"`.
   - **Existing pass1 listing?** Update price, days_on_market, etc.
   - **Existing pass2 listing?** Update only volatile fields (price, days_on_market). Do NOT overwrite fees/taxes/agent/history — those are stable.
   - **Price changed on a pass2 listing?** Mark it `needs_refresh: true` so Pass 2 re-scrapes it next time (price history will have a new entry).
3. **Pass 2 (detail pages) — incremental only:** Build the scrape queue from:
   - All listings with `data_quality: "pass1"` (never had Pass 2)
   - All listings with `needs_refresh: true` (price changed since last Pass 2)
   - **Skip** anything already at `data_quality: "pass2"` with unchanged price
   - **Cap** at N listings per run (e.g., 30) to stay within actor reliability. The rest queue for next run.
4. **Merge Pass 2 into db.json:** For each successful Pass 2 result, upgrade the listing: set `data_quality: "pass2"`, fill in fees/taxes/agent/history, set `last_pass2` to today.
5. **Generate `data/latest.json`** from db.json — this is what the app reads. Flat array of all active listings, same format as today.
6. **Detect delistings:** Any listing in db.json whose `last_pass1` is 14+ days old and didn't appear in today's Pass 1 results gets `status: "delisted"`. Delisted listings are excluded from `latest.json` but kept in db.json for historical reference.

#### What this means in practice

**Initial backfill (Session 9, 2026-04-21):** All 373 listings were backfilled to pass2 quality in a single session by calling the Apify API directly in batches of 50–100. Total time: ~15 minutes of Apify runtime. This bypassed the cron pipeline entirely — the right approach for bulk initial population.

**Ongoing cron runs:** Pass 1 discovers new listings and price changes. Pass 2 processes up to 100 per run (new + price-changed only). Typical maintenance run: 5–15 detail pages.

#### Files

- `data/db.json` — canonical store, committed to repo, always the most complete picture
- `data/latest.json` — generated from db.json each run, flat array for the app, overwrites are fine because db.json is the real store
- `data/YYYY-MM-DD.json` — dated snapshot of latest.json for badge diffing (new/reduced)
- `data/partial.json` — removed; no longer needed since db.json is never overwritten destructively

#### Cost Efficiency

Initial backfill (Session 9): ~362 listings × $0.003 = ~$1.09 total. Completed in one session.
Ongoing maintenance: each cron run scrapes ~5–15 new/changed listings (~$0.015–$0.045). Maintenance is nearly free.

### Secondary: RapidAPI NYC Real Estate API
Validated YELLOW. Fast cached lookups, no price history or agent contact. 25 free req/mo (~19 remaining). Use for targeted per-property due diligence only, not bulk pulls.

Auth: `x-api-key` + `x-api-host: nyc-real-estate-api.p.rapidapi.com`. Key in `.env` locally; GitHub Secret in CI.

### Supplemental Free Data
**PLUTO** — year built, building class, units, lot/gross area. Join key: BBL.
**ACRIS** — historical deeded sales (condos only; co-op unit sales not available). Socrata API, no key required.

### Per-Candidate Due Diligence (15 min, free, manual)
- **ZoLa** (`zola.planning.nyc.gov`) — BBL, zoning, assessed value
- **HPD Online** (`hpdonline.hpdnyc.org`) — open housing violations
- **DOB NOW** (`a810-dobnow.nyc.gov`) — permits, complaints, Local Law 11 work
- **ACRIS** — recent unit sales (condos only)
- **Broker** — offering plan, 2 years financials, reserve fund, pending assessments, litigation

## Listing Status Tracking (Backend Migration)

The full design spec lives in `STATUS-FEATURE.md`. This section is the executive summary. Tasks live in `TASKS.md`.

### Problem

StreetHard is read-only. Family members can browse but can't mark which listings they've toured, which they've vetoed, or which they're pursuing. The app's data model is a fixed snapshot; the buyer's mental model is a stateful flow (*seen → toured → shortlisted → offered*). The two need to meet.

A second dimension — wanting to be re-surfaced when a rejected listing's price drops — is orthogonal to status. We track it as a separate `watch` flag.

### Architecture Decision: Railway-hosted FastAPI + managed Postgres

The static GitHub Pages app does two fetches on load: `data/latest.json` from Pages (the existing listings) and `/status` from a Railway-hosted FastAPI service (the per-user overlay). Merge by `listing_id` in the browser. Writes go straight to `PUT /status/{id}` against Railway, key-gated.

| Considered | Why rejected |
|---|---|
| `data/status.json` in the repo, written via GitHub PAT from the browser | PAT must ship to the client. Every status click becomes a git commit. Two writers race. Repo history pollution. |
| Serverless proxy (Vercel/Cloudflare) → repo | Hides the PAT but doesn't solve concurrency or commit-rate. |
| OAuth flow (real auth) | Wildly over-engineered for a family of 2–4 sharing one identity. Adds a login screen to a tool the user just wants to open. |
| Google Sheets / Airtable / Notion | Vendor lock-in for a 10-row schema. Their UIs leak through, rate limits bite. |
| `localStorage` only | Doesn't sync laptop ↔ phone. Phone-on-tour state is the whole point. |

### Why `db.json` stays in the repo, and status moves to Railway

| `db.json` (stays in repo) | `listing_status` (moves to Railway) |
|---|---|
| Bot-written by the cron, weekly cadence | Per-click; multiple writes per minute possible |
| Public market data | Mutable opinions + private notes |
| One writer | Two devices, racy |
| Version history is genuinely useful (price diffs) | Version history is noise |
| Static-friendly, Pages serves it directly | Server-of-truth simplifies concurrency |

Two stores, two access patterns, two rates of change. Don't unify them.

### State Model

Six statuses (final names TBD; see Open Questions): `none` (default, implicit) → `watching` → `viewing` → `shortlisted` → `offered`, plus `rejected` reachable from anywhere. Plus an orthogonal `watch` boolean for re-surfacing on price changes. Plus free-text `notes` and a fixed-vocabulary multi-select `chips` array (deal-breakers like `no light`, `bad layout`, `building risk`). One row per listing in `listing_status`. Schema in STATUS-FEATURE.md.

### Stack

- **Backend:** FastAPI on Python 3.12, asyncpg, no ORM. Same repo as the app, new `api/` subfolder, deployed as a separate Railway service via Root Directory setting. Postgres via Railway managed plugin. Schema applied at startup from `api/schema.sql`; idempotent `CREATE … IF NOT EXISTS`. No Alembic.
- **Frontend:** Two parallel fetches in `index.html`, merge by `listing_id`. Status pill in column 1, watch bookmark icon, expanded-row notes editor and chip selector, gear-icon Settings panel for the API key. Optimistic UI, immediate single-row PUTs. Notes get a 1-second debounce on keystrokes only.
- **Auth:** A single static `WRITE_API_KEY` generated by the user, pasted into Railway env vars and into each device's `localStorage`. Reads are public, writes are key-gated. The family shares one identity; no per-user attribution.
- **Offline:** localStorage outbox flushed on `online` / `visibilitychange` events. Closed-tab-while-offline (Service Worker + IndexedDB) deferred to v1.5.
- **Hobby tier ($5/mo)** so the service doesn't sleep — auto-sleep makes the first click after a quiet day visibly laggy.
- **Custom domains (Session 16):** `streethard.omarqari.com` for the static app (CNAME → `omarqari.github.io`), `api.streethard.omarqari.com` for the API (CNAME → Railway service). DNS records on Spaceship. Default `*.up.railway.app` and `omarqari.github.io/streethard` stay live as fallbacks.
- **Backups:** Railway snapshots cover v1. Don't ship a backup script.

### Cron pipeline is untouched

`refresh.yml` → `db.json` is orthogonal to this work. Listing data continues to flow exactly as it does today; the new service runs in parallel with no coupling.

### Phasing

- **v1** — ship it. Six statuses, watch flag, notes, chips, Settings panel, optimistic UI, offline outbox via `online` / `visibilitychange`. Inline filters ("show only Shortlisted," "hide Rejected"). Acceptance criteria in TASKS.md.
- **v1.5** — niceties. Service Worker + IndexedDB so the app works offline in a closed tab. Per-IP write rate limit. Export-to-CSV of marked listings. Watch-triggered visual diff when a watched listing's price drops.
- **v2** — only if needed. Per-user identity, multi-key with attribution on notes. Push notifications. None of this is required for n=1.

### Resolved Pre-Build Questions (Sessions 14–16)

- **Language pick:** FastAPI on Python 3.12. ✅
- **Per-user attribution:** dropped — shared write key. ✅
- **Repo strategy:** same repo, `api/` subfolder. ✅
- **Backups:** Railway snapshots only at v1. ✅
- **Hobby tier:** confirmed, $5/mo. ✅
- **Custom domains:** `streethard.omarqari.com` + `api.streethard.omarqari.com`. ✅ (Session 16)

### Still-Open Questions (Session 16, non-blocking for build)

- **Final status names.** Currently `watching / viewing / shortlisted / rejected / offered` + implicit `none`. Confirm before the schema CHECK constraint hardens, or accept that renaming later is an idempotent ALTER + client update.
- **DNS cutover timing.** Old `omarqari.github.io/streethard` URL stays live during propagation (24–48h worst case). Drop the fallback CORS origin once both devices verify load via custom domain.
- **Mobile Safari `localStorage` eviction.** iOS 17 wipes site data after ~7 days of non-use. Settings panel must show a "key not set" empty state, not crash. Decide whether to mitigate now (IndexedDB) or accept the periodic re-paste at v1.
- **Spouse / family writes.** Decision deferred — shared write key works today; revisit only if attribution ever matters.
- **Domain.** Confirm staying on the default `*.up.railway.app` URL for v1, or call out a preferred custom domain now (saves a re-deploy later).
- **Chip vocabulary.** The proposed list (`no light`, `bad layout`, `building risk`, `priced too high`, `noise`, `condition`, `bad block`, `flip tax`, `board risk`) is curated on purpose; confirm or amend before the schema ships.

### Non-Negotiables (consistent with existing project posture)

- n=1 personal use. No multi-tenancy, no auth flow, no rate limit infrastructure beyond what Hobby tier gives us.
- No commercial real estate APIs. Nothing here changes that — this is metadata about listings, not new market data.
- `db.json` in the repo is sacrosanct. No status data leaks into it; the pipeline stays single-purpose.
- No build step. The frontend remains a single static `index.html`.
- Static GitHub Pages hosting for the app remains the default. The API service is the only piece moving off Pages.

## Phased Timeline

### Phase 1 — Setup ✅ Complete
Data sources validated. Apify confirmed as primary. Mortgage calculator defaults locked. Output schema defined. Architecture decided.

### Phase 2 — v1 Build + First Pull ✅ Complete

**Step 1 — Build `index.html`** ✅ Done
- Static app shell with all UI and JS mortgage calculator
- Fetches `data/latest.json` on load
- Table view default, card view toggle
- Inline filters and mortgage inputs
- Row expansion with price history + agent + payment breakdown

**Step 2 — Build `scripts/pull.py`** ✅ Done
- Calls Apify `memo23/streeteasy-ppr` with production URL
- Downloads results, saves as `data/latest.json` + `data/YYYY-MM-DD.json`
- Two-pass strategy: Pass 1 = search URL (discovers IDs, simple field names), Pass 2 = individual listing pages (full data with federated GraphQL prefix field names)
- Pass 1 fallback: if Pass 2 yields < MIN_LISTINGS, falls back to Pass 1 sparse data so app stays live
- Reads Apify token from environment variable (local: `.env`; CI: GitHub Secret)
- Guard clause: exits code 1 if listing count < 10 (prevents overwriting `latest.json` on bad run)

**Step 3 — First pull + pipeline debugging** ✅ Done
- Ran against production $2M–$5M URL, `maxItems: 500`
- Debugged and fixed Pass 2 normalization: Apify uses federated GraphQL flat key names that original `normalize()` didn't know about
- Result: 50 normalized, 0 skipped. Full field coverage on all required fields.

**Step 4 — GitHub setup** ✅ Done
- Repo live at `github.com/omarqari/streethard`
- GitHub Pages enabled; family URL live
- `APIFY_TOKEN` GitHub Secret set
- `.github/workflows/refresh.yml` running; weekly cron + manual trigger verified

**Phase 2 enhancements (post-v1):**
- **Incremental pipeline ("Puzzle" model):** ✅ Implemented Session 8. `data/db.json` canonical store. Pass 2 capped at 100/run (raised from 30 in Session 9), abort+salvage on timeout, delisting detection. Full architecture documented above under "Data Storage."
- **Full Pass 2 backfill:** ✅ Completed Session 9. All 373 listings (330 sale, 43 rental) at pass2 quality. Direct API calls in batches of 50–100, bypassing the cron pipeline. See RETRO-SESSION9.md.
- **Text search:** ✅ Free-text search bar in filter bar (Session 8).
- **Price history full dates:** ✅ Shows "Apr 16, 2026" instead of "Apr 2026" (Session 8).
- **Rental comp analysis:** ✅ Pipeline built; rental Pass 2 schema verified. `normalize_rental()` rewritten with verified field names. End-to-end production run on a standard apartment still pending.
- **New/reduced badges:** Compare current pull against previous dated JSON → `badge` field on each listing → pill badge in app. Architecture documented above. Pending implementation.
- **Co-op sqft gap:** Evaluate whether to add a supplemental co-op pass without the sqft filter

### Phase 3 — Shortlisting (~5–20 candidates)
Run the 15-minute due diligence checklist per serious candidate. Maintain a running shortlist with status (watching / viewing / shortlisted / rejected / offered).

**Shortlist feature (in-app) — options TBD before building:**
The app needs a way for family members to mark listings as seen/liked/rejected. Several approaches exist with different tradeoffs:

- **localStorage** — works immediately, zero infrastructure. Device-local only; marks not shared across family members. Simple prototype.
- **GitHub API (repo JSON)** — shortlist stored as a JSON file in the repo; app writes it via GitHub API using a personal access token. Shared across all family members (one source of truth). Requires a PAT in the browser — not safe for a public Pages URL.
- **Google Sheets** — lightweight shared backing store; free. Requires a service account or OAuth; adds complexity.
- **Airtable / Notion** — easy UI for non-technical family members but introduces a third-party dependency.

**Decision needed before building:** What's the family sharing model? If only one person uses the app, localStorage is fine. If multiple family members need to see each other's marks, a shared backing store is required. The right choice determines the entire architecture.

**Do not implement until the sharing model is decided.**

### Phase 4 — Finalists (1–3 candidates)
Engage real estate attorney. Request offering plan and 2 years of financial statements. Inspector if feasible. Deep read of board minutes for co-ops.

### Phase 5 — Purchase
Offer, negotiation, contract, financing, board package (co-op), closing.

## Success Criteria
- Informed offer on a Manhattan apartment within 6–12 months
- Confidence in pricing supported by comps, not guesswork
- No post-close surprises on known-in-advance risks
- Family can access and use the app without any technical help

## Explicit Non-Goals
- Building a commercial product or SaaS
- Comprehensive real-time coverage of all NYC listings
- Backend server, database, or authentication
- Commercial data licenses (ATTOM, CoreLogic, RLS)
- Replacing StreetEasy's UI

## Budget Envelope
- Apify: ~$1.50–$2.40 per weekly pull; $5 free credit covers ~2 months
- RapidAPI: $0 (free tier, 25 req/mo)
- GitHub Pages: $0
- PLUTO / ACRIS: $0
- Real estate attorney: ~$3,000 (non-negotiable)
- Inspector: $400–$800

Total data/tooling cost: under $20. Attorney and inspector are the real line items.
