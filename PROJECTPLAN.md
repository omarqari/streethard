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
- **Repo:** `github.com/[user]/streethard`
- **Live URL:** `[user].github.io/streethard` (custom domain optional later)
- No server, no backend, no database

### Data Refresh
- **GitHub Actions** cron job runs weekly (Sundays)
- Workflow: call Apify → download results → save `data/latest.json` + `data/YYYY-MM-DD.json` → commit to repo → GitHub Pages auto-deploys
- Apify API token stored as **GitHub Secret** (never in code)
- Manual re-run available via GitHub Actions "Run workflow" button

### File Structure
```
/
├── index.html              ← StreetHard app shell (static, never changes per-run)
├── data/
│   ├── latest.json         ← Always the most recent pull (overwritten each run)
│   └── 2026-04-19.json     ← Dated archive of every past run
├── .github/
│   └── workflows/
│       └── refresh.yml     ← GitHub Actions weekly cron
└── scripts/
    └── pull.py             ← Apify pull script (runs locally or in CI)
```

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

### Data Storage
- `data/latest.json` — overwritten each run; what the live app reads
- `data/YYYY-MM-DD.json` — immutable dated archive; never overwritten
- Raw Apify output stored as-is (no pre-computation); all math runs client-side
- Git history of `data/` directory = full audit trail of every weekly pull

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
- **Rental comp analysis:** UES rental data alongside PMT/SqFt for buy-vs-rent comparison
- **New/reduced badges:** Compare current pull IDs against previous `data/` JSON to surface new listings and price cuts with visual badges
- **Co-op sqft gap:** Evaluate whether to add a supplemental co-op pass without the sqft filter

### Phase 3 — Shortlisting (~5–20 candidates)
Run the 15-minute due diligence checklist per serious candidate. Maintain a running shortlist with status (watching / viewing / shortlisted / rejected / offered).

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
