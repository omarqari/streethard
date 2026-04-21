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
- Padded responses with generic "consult a professional" filler

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

**Co-ops don't appear in ACRIS at the unit level.** Co-op shares aren't deeded real property. Only the underlying building transfers show up. If the user is looking at co-ops, unit-level sale history effectively exists only in StreetEasy / RLS.

**PLUTO aggregates condos to the building level.** One record per condo complex, not per unit. So PLUTO tells you about the building; listings/ACRIS tell you about the unit.

**StreetEasy already does ~90% of browsing.** Price history, comps, $/sqft, days-on-market are all on every listing page. Any tool built is a supplement for custom queries StreetEasy's UI can't answer — not a replacement.

**Building-level financial risk is invisible in public data.** Reserve funds, pending assessments, underlying mortgage, litigation — all from the offering plan package and financial statements from the broker. No dataset has this.

## Mortgage Calculator Defaults

Use these assumptions for all monthly payment estimates unless the user specifies otherwise:

- **Down payment:** $750,000 exactly (fixed dollar amount always, regardless of purchase price)
- **Interest rate:** 3.00% annual
- **Loan term:** 30 years

Formula: `M = P × [r(1+r)^n] / [(1+r)^n − 1]`  
Total monthly = mortgage payment + common charges/HOA + taxes

## Output Format — StreetHard HTML App

The app is called **StreetHard**. It is a static web app hosted on **GitHub Pages**, auto-refreshed weekly via **GitHub Actions**. The whole family can access it at a shared URL.

### Architecture
- `index.html` — static app shell; all UI and mortgage math in client-side JavaScript
- `data/latest.json` — current listings data; fetched by the app on load; overwritten each weekly run
- `data/YYYY-MM-DD.json` — immutable dated archive of every past run
- `scripts/pull.py` — Apify pull script; runs locally or in CI
- `.github/workflows/refresh.yml` — weekly cron; calls Apify, commits JSON, Pages auto-deploys
- Apify token in `.env` locally; `APIFY_TOKEN` GitHub Secret in CI

### Design Language
Dark navy header (`#0E1730`), white card layout, blue links (`#3461D9`), orange accent (`#FF6000`).

- **Default view**: Sortable table (dense, comparison-optimized)
- **Toggle**: Card view
- **Default sort**: Monthly Payment descending
- **Inline filters**: Beds, Type (Condo/Co-op), Max Price, Max Monthly Payment
- **Mortgage calculator** in header: Down Payment · Rate · Term — interactive, recalculates all rows instantly
- **Row expansion**: Price History, Agent info, Payment Breakdown
- **Days Listed**: NEW/blue <7d, green 7–44d, yellow 45–120d, red 121d+
- Single `index.html`, no server, opens in any browser

## Current Infrastructure State

- Running Claude in Cowork mode — Claude calls APIs directly, no config files to edit
- **Primary data source: Apify `memo23/streeteasy-ppr`** — Pass 1 (search URLs) GREEN; Pass 2 (individual listing pages) BROKEN in build 0.0.118. Bug report filed 2026-04-20, awaiting fix. Without Pass 2: no fees, taxes, agent contact, or price history.
- **Secondary: RapidAPI NYC Real Estate API** — validated YELLOW, 25 req/mo free tier, good for fast single-listing lookups; no price history or agent contact
- RapidAPI key in `.env`; Apify account on paid plan
- No PLUTO, ACRIS, or other supplemental data downloaded yet

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

## Tone Guidance for Responses

Be direct. When the user asks "what's the best way to do X," give a ranked opinion with reasoning. When they push back, take it seriously and reassess rather than dig in. Admit mistakes cleanly. Skip the reflexive disclaimers.
