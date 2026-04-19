# Handoff Prompt — NYC Real Estate Advisor

Drop this entire prompt into a new Cowork session to pick up exactly where we left off.

---

## Project Context

I'm buying one residential apartment in Manhattan for my family. This is a personal project, not commercial. I've built lightweight tooling in Cowork to pull active listings data from StreetEasy via Apify, calculate monthly payments, and output a sortable spreadsheet for analysis.

**Start by reading these four files in my workspace folder before doing anything:**
- `/Users/omarqari/cowork/NYC Real Estate Advisor/CLAUDE.md` — project orientation, defaults, infrastructure state
- `/Users/omarqari/cowork/NYC Real Estate Advisor/PROJECTPLAN.md` — full strategy, output schema, architecture
- `/Users/omarqari/cowork/NYC Real Estate Advisor/TASKS.md` — what's done and what's next
- `/Users/omarqari/cowork/NYC Real Estate Advisor/TEST_RESULTS.md` — validation results for RapidAPI and Apify

Once you've read those, here is a complete briefing so you don't need to re-derive anything.

---

## What's Been Done

### Data Source Validation (complete)

Two data sources were tested against a real listing — 330 East 75th Street #28BC, The Saratoga (StreetEasy listing ID 1818978, active Douglas Elliman listing at $3,300,000 as of 4/16/2026).

**RapidAPI `nyc-real-estate-api` (provider: realestator/layercity) — YELLOW**
- Host: `nyc-real-estate-api.p.rapidapi.com`
- API key: stored in `/Users/omarqari/cowork/NYC Real Estate Advisor/.env` as `RAPIDAPI_KEY`
- Returns cached/pre-scraped data, instant responses
- 25 free requests/month (~19 remaining as of 4/19/2026)
- Good for: price, sqft, HOA, taxes, beds/baths, days on market, address
- Missing: price history event timeline, agent name/phone/email
- Verdict: Use for quick single-listing sanity checks only. Not used for bulk pulls.

**Apify `memo23/streeteasy-ppr` — GREEN (primary source)**
- Actor ID: `ptsXZUXADV3OKZ5kd`
- Pay-Per-Event: $3.00 per 1,000 results (~$0.009 per listing)
- $5 free credit on account (Omar's account, signed in via GitHub)
- Scrapes StreetEasy live using residential proxies — not a cached database
- Returns everything: price, sqft, beds/baths, address/unit, building name, year built, days on market, HOA/common charges, taxes, full price history event timeline (back to first listing, sometimes 2006+), agent name, agent direct phone, agent email, amenities
- Validated against listing 1818978: all required fields matched StreetEasy exactly
- **Important:** Only tested against a direct listing URL so far (`https://streeteasy.com/sale/1818978`). Has NOT yet been tested against a search results page URL. Field coverage on bulk search scrapes is unconfirmed — some rich fields (price history, agent contact) may only populate when scraping individual listing pages.

### Key Technical Findings

**StreetEasy listing IDs:** The API uses 7-digit `/sale/{id}` numeric IDs (e.g., `1818978`), not the building/unit URL slug (`/building/the-saratoga/28bc`). To find the current active listing ID from a StreetEasy building page, look for `saleInventorySummary.availableListingDigests` in the page source — the first ID is the active listing.

**Co-op vs Condo math:** Co-op maintenance fees on StreetEasy INCLUDE property taxes. Condo common charges do NOT include taxes (they are listed separately). The monthly payment formula must branch by type — adding taxes on top of maintenance for a co-op double-counts by $3,000–$4,000/mo.

**Apify proxy config:** Always use `"useApifyProxy": true, "apifyProxyGroups": ["RESIDENTIAL"]` in the actor input. Residential proxies make requests look like home users; without them StreetEasy's bot detection blocks the scrape.

---

## The Immediate Task: First Real Pull (v1 Test)

Run Apify `memo23/streeteasy-ppr` against the UES search URL and produce the output spreadsheet.

### Search Parameters
- Geography: Upper East Side, Manhattan
- Price: $2,500,000 – $4,000,000 (test range; full project ceiling is $6M)
- SqFt: ≥ 1,500
- Status: Active only

### Apify Input JSON to Use
```json
{
  "startUrls": [
    {
      "url": "https://streeteasy.com/for-sale/upper-east-side/price:2500000-4000000%7Csqft:1500-"
    }
  ],
  "addresses": [],
  "flattenDatasetItems": true,
  "monitoringMode": false,
  "moreResults": true,
  "maxItems": 500,
  "proxy": {
    "useApifyProxy": true,
    "apifyProxyGroups": ["RESIDENTIAL"]
  }
}
```

Navigate to `https://console.apify.com/actors/ptsXZUXADV3OKZ5kd/input`, paste the JSON above (use JSON tab), and click Save & Start. The run page URL will contain the run ID needed to fetch results.

### Output Spreadsheet Schema

Columns in this exact order, sorted **descending by Monthly Payment**:

| # | Column | Source Field | Notes |
|---|---|---|---|
| 1 | Building | `building_title` | e.g., "The Saratoga" |
| 2 | Street | `address_street` | e.g., "330 East 75th Street" |
| 3 | Apt | `address_unit` | e.g., "28BC" |
| 4 | Cross Streets | — | Leave blank; not in API |
| 5 | Year Built | `building_year_built` | |
| 6 | Price | `pricing_price` | Raw asking price |
| 7 | Monthly Payment | Calculated | See formula below |
| 8 | SqFt | `livingAreaSize` | |
| 9 | # of Bedrooms | `bedroomCount` | |
| 10 | # of Bathrooms | `fullBathroomCount` + (`halfBathroomCount` × 0.5) | e.g., 3 full + 1 half = 3.5 |
| 11 | Price / SqFt | `price_per_sqft` | |
| 12 | Annualized Monthly Payment / SqFt | Calculated | (Monthly Payment × 12) ÷ SqFt |
| 13 | Type | `building_building_type` | Condo, Co-op, Townhouse, etc. |
| 14 | Days Listed | `days_on_market` | |

### Monthly Payment Formula

**Mortgage calculator defaults (always use these unless I say otherwise):**
- Down payment: $750,000 exactly (fixed dollar amount, not a percentage)
- Interest rate: 3.00% annual
- Loan term: 30 years
- Formula: `M = P × [r(1+r)^n] / [(1+r)^n − 1]` where P = price − 750000, r = 0.03/12, n = 360

**Branch by property type:**
- If Type = **Co-op**: Monthly Payment = mortgage payment + maintenance fee (`maintenanceFee`)
  *(maintenance already includes taxes — do NOT add taxes separately)*
- If Type = **Condo** (or anything else): Monthly Payment = mortgage payment + common charges (`maintenanceFee`) + taxes (`taxes`)

### Apify Field Name Reference (confirmed from test)

These are the actual flattened field names returned by the actor:

```
saleListingDetailsFederated_data_saleByListingId_pricing_price          → asking price
saleListingDetailsFederated_data_saleByListingId_pricing_maintenanceFee → HOA / maintenance / common charges
saleListingDetailsFederated_data_saleByListingId_pricing_taxes          → property taxes (condos only)
saleListingDetailsFederated_data_saleByListingId_propertyDetails_livingAreaSize  → sqft
saleListingDetailsFederated_data_saleByListingId_propertyDetails_bedroomCount   → bedrooms
saleListingDetailsFederated_data_saleByListingId_propertyDetails_fullBathroomCount
saleListingDetailsFederated_data_saleByListingId_propertyDetails_halfBathroomCount
saleDetailsToCombineWithFederated_data_sale_days_on_market              → days on market
saleDetailsToCombineWithFederated_data_sale_building_title              → building name
saleDetailsToCombineWithFederated_data_sale_building_year_built         → year built
saleDetailsToCombineWithFederated_data_sale_building_building_type      → condo / co-op / etc.
saleDetailsToCombineWithFederated_data_sale_price_per_sqft              → $/sqft
saleDetailsToCombineWithFederated_data_sale_price_histories_json        → JSON string, parse separately
saleListingDetailsFederated_data_saleByListingId_propertyDetails_address_street
saleListingDetailsFederated_data_saleByListingId_propertyDetails_address_unit
```

Note: field names are long flattened keys. The actor was run with `flattenDatasetItems: true`. If the bulk search pull returns different field names than above, adapt accordingly — the structure may differ from the single-listing test.

### Fetching Results After Run Completes

After the Apify run succeeds, get the dataset ID from the Storage tab, then fetch:
```
https://api.apify.com/v2/datasets/{DATASET_ID}/items?format=json&clean=true
```
Open that URL in the browser tab used by Apify (so authentication cookies are present) to retrieve the full JSON without CORS issues.

---

## Post-v1 Validation Checklist

After the first pull succeeds, check:
1. Did the actor paginate through all search result pages, or stop at page 1? (Count results vs. expected ~50–150 listings in the $2.5M–$4M UES range)
2. Are `maintenanceFee` and `taxes` populated for bulk search results, or only when scraping individual listing pages?
3. Are price history and agent contact fields populated in bulk mode?

---

## Project Defaults Reference

- **Workspace folder:** `/Users/omarqari/cowork/NYC Real Estate Advisor/`
- **API keys:** `/Users/omarqari/cowork/NYC Real Estate Advisor/.env`
- **Apify actor:** `memo23/streeteasy-ppr` (ID: `ptsXZUXADV3OKZ5kd`)
- **RapidAPI host:** `nyc-real-estate-api.p.rapidapi.com`
- **Down payment:** $750,000 exactly
- **Interest rate:** 3.00%
- **Loan term:** 30 years
- **Sort order:** Descending by Monthly Payment
- **Output format:** .xlsx spreadsheet saved to `/Users/omarqari/cowork/NYC Real Estate Advisor/`
