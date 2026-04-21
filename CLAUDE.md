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
- `data/db.json` — **canonical store**; persistent dict of all listings keyed by ID; each has `data_quality` ("pass1" or "pass2"); never overwritten destructively
- `data/latest.json` — generated from db.json each run; flat array for the app to fetch on load
- `data/YYYY-MM-DD.json` — immutable dated archive of every past run
- `scripts/pull.py` — **incremental** Apify pull script; Pass 1 discovers listings, Pass 2 only fills in what's missing (capped at 100/run); saves db.json after every step
- `.github/workflows/refresh.yml` — cron Mon+Thu 9 AM UTC; calls Apify, commits data/, Pages auto-deploys
- Apify token in `.env` locally; `APIFY_TOKEN` GitHub Secret in CI

### Design Language
Dark navy header (`#0E1730`), white card layout, blue links (`#3461D9`), orange accent (`#FF6000`).

- **Default view**: Sortable table (dense, comparison-optimized)
- **Toggle**: Card view
- **Default sort**: Monthly Payment descending
- **Text search**: Free-text search bar filters by building, address, unit, neighborhood, agent name/firm
- **Inline filters**: Beds, Type (Condo/Co-op), Max Price, Max Monthly Payment
- **Mortgage calculator** in header: Down Payment · Rate · Term — interactive, recalculates all rows instantly
- **Row expansion**: Price History, Agent info, Payment Breakdown
- **Days Listed**: NEW/blue <7d, green 7–44d, yellow 45–120d, red 121d+
- Single `index.html`, no server, opens in any browser

## Current Infrastructure State

- Running Claude in Cowork mode — Claude calls APIs directly, no config files to edit
- **Primary data source: Apify `memo23/streeteasy-ppr`** — Pass 1 GREEN, Pass 2 GREEN (fixed by memo23 2026-04-20). Both operational.
- **Pipeline: Incremental ("Puzzle" model)** — `data/db.json` is the canonical store. Each cron run discovers new listings via Pass 1 and fills in detail via Pass 2 (capped at 100/run). See PROJECTPLAN.md for full architecture.
- **db.json state:** 373 active listings — **ALL at pass2 quality** (330 sale, 43 rental). Full fees, taxes, agent contact, price history across the board. Backfilled in Session 9.
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
- `RETRO-SESSION9.md` — CTO/Architect/CPO retrospective on the backfill lesson
- `data/db.json` — canonical listing store (the source of truth; never overwritten destructively)
- `data/latest.json` — generated from db.json for the app to consume
- `data/YYYY-MM-DD.json` — dated snapshots for badge diffing
- `scripts/pull.py` — incremental Apify pull script
- `index.html` — StreetHard app shell

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
