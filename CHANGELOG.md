# CHANGELOG

All notable decisions and events on this project, in reverse chronological order.

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
