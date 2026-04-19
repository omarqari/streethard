# TEST RESULTS
Date: 2026-04-19

---

## Overall Verdict: 🟡 YELLOW → leaning GREEN for detail lookups

The detail endpoint is excellent and matches StreetEasy exactly. The search endpoint is too sparse to use standalone. Per-listing price history is not available. Free tier (25 req/mo) limits bulk use but is fine for targeted due diligence.

---

## Test 1 — Active UES Listings Search

**Endpoint:** `GET /sales/search?areas=upper-east-side&limit=3`

**Result: ✅ PASS (with caveats)**

- Returned 1,333 active UES listings
- The `areas=upper-east-side` slug works correctly

**What the search returns per listing:**
```json
{
  "id": "1822919",
  "price": 876000,
  "status": "open",
  "longitude": -73.9537,
  "latitude": 40.7700,
  "url": "https://www.streeteasy.com/sale/1822919"
}
```

**Critical gap:** Search returns ONLY `id`, `price`, `status`, `lat/lng`, `url`. No address, no sqft, no beds/baths, no neighborhood label. To get any useful detail you need a separate `/sales/{id}` call per listing.

**Quota math:** With 25 requests/month free tier, and 1,333 UES listings, you can detail at most ~24 listings per month. That's too few for real browsing.

---

## Test 2 — Specific Listing: 330 East 75th Street #28BC

**Note:** The listing is now **delisted/sold** (closedAt: 2026-03-02, 103 days on market). This does not affect the data quality test — it shows the API retains detail on sold listings.

**Endpoint:** `GET /sales/1801061`
*(The API uses StreetEasy's `/sale/{id}` numeric ID, not the building/unit URL slug)*

**Full API Response:**
```json
{
  "id": "1801061",
  "status": "delisted",
  "listedAt": "2025-11-19",
  "closedAt": "2026-03-02",
  "daysOnMarket": 103,
  "address": "330 East 75th Street #28BC",
  "price": 3395000,
  "closedPrice": null,
  "borough": "manhattan",
  "neighborhood": "lenox-hill",
  "zipcode": "10021",
  "propertyType": "condo",
  "sqft": 2400,
  "ppsqft": 1414,
  "bedrooms": 3,
  "bathrooms": 2.5,
  "type": "sale",
  "latitude": 40.76979828,
  "longitude": -73.95529938,
  "monthlyHoa": 2400,
  "monthlyTax": 3384,
  "amenities": ["balcony","bike_room","central_ac","city_view","concierge","courtyard",
    "dishwasher","dogs","doorman","elevator","fios_available","full_time_doorman",
    "garage","hardwood_floors","laundry","package_room","parking","pets",
    "public_outdoor_space","roofdeck","roof_rights","skyline_view","smoke_free",
    "washer_dryer","wheelchair_access"],
  "builtIn": 1985,
  "description": "Apartment 28BC at The Saratoga is a sun-drenched, triple-exposure 3-bedroom, 2.5-bath residence with two private terraces..."
}
```

### Required Fields Scorecard

| Field | Expected | Got | Status |
|---|---|---|---|
| Address | 330 East 75th Street #28BC | 330 East 75th Street #28BC | ✅ Exact match |
| Price | $3,300,000 | $3,395,000 | ⚠️ Discrepancy — listing was reduced before selling; price history would explain this |
| Common Charges (HOA) | $2,448/mo | $2,400/mo | ⚠️ $48 off — minor, likely rounding |
| Taxes | $3,368/mo | $3,384/mo | ⚠️ $16 off — minor |
| Tax Abatement | No info | Not in response | ❌ Missing |
| Days on Market | Present | 103 | ✅ |
| Price History | Date + Price + Event | Not in this endpoint | ❌ Need "Past Sales" endpoint |

### Nice-to-Have Fields Scorecard

| Field | Status | Notes |
|---|---|---|
| Seller's agent name | ❌ Missing | Not in response at all |
| Seller's agent contact | ❌ Missing | Not in response at all |
| Description | ✅ Present | Full free-text description |
| sqft | ✅ 2,400 | Present |
| Beds / Baths | ✅ 3 bed / 2.5 bath | Present |
| $/sqft | ✅ $1,414 | `ppsqft` field |
| Building amenities | ✅ 25 amenities | Extensive, machine-readable list |
| Year built | ✅ 1985 | `builtIn` field |
| Building units / stories | ❌ Missing | Not in response |
| Property type | ✅ condo | Present |
| Neighborhood | ✅ lenox-hill | Present (slug format) |

---

## Test 2b — New Active Listing (Douglas Elliman, listed 4/16/2026)

**Background:** The Sotheby's listing (ID 1801061) was delisted 3/2/2026. A new listing at the same unit was posted 4/16/2026 by Douglas Elliman — 3 days before this test. That listing has its own API ID: `1818978`.

**Key lesson:** The `/building/the-saratoga/28bc` URL slug returns the old listing's ID in the page source. The correct way to get the *current active* listing is to use the search endpoint or parse `saleInventorySummary.availableListingDigests` from the StreetEasy page source.

**Endpoint:** `GET /sales/1818978`

### Required Fields — New Listing

| Field | Expected | Got | Status |
|---|---|---|---|
| Address | 330 East 75th Street #28BC | 330 East 75th Street #28BC | ✅ Exact |
| Price | $3,300,000 | $3,300,000 | ✅ Exact |
| Common Charges (HOA) | $2,448/mo | $2,448/mo | ✅ Exact |
| Taxes | $3,368/mo | $3,368/mo | ✅ Exact |
| Tax Abatement | No info | Not in response | ❌ Missing |
| Days on Market | 3 | 3 | ✅ Exact |
| Price History | Date + Price + Event | ❌ Not available | ❌ See below |

All discrepancies from the earlier test were because we were looking at the wrong (old) listing. The new listing matches StreetEasy exactly on every available field.

---

## "Past Sales" Endpoint — What It Actually Does

**NOT** per-listing price history. It is a bulk area search for closed/delisted sales, with the same filters as active sales (`areas`, `closedAfter`, price range, beds, etc.). Useful for pulling comps in a neighborhood. Not useful for the event timeline (listed → price cut → delisted → re-listed) visible on StreetEasy's Property History tab.

**Per-unit price history is not available via this API.** StreetEasy does not expose that data through any third-party channel.

---

## Key Findings

**What this API is good for:**
- Bulk search across UES (or any neighborhood) to get IDs + prices quickly
- Detail lookups for shortlisted properties: address, price, sqft, beds/baths, HOA, taxes, amenities, year built, description — all there
- Historical data: retains delisted/sold listings with all fields intact

**What's missing:**
- **Per-listing price history** (the event timeline: listed → price cut → delisted) — not available from this API or any third-party. StreetEasy only surface on the listing page itself.
- Agent/broker contact info — not in the API at all
- Building units / stories
- Tax abatement status

**How to get the correct API ID from a StreetEasy listing page:**
The API uses StreetEasy's internal 7-digit `/sale/{id}` numeric ID.
The building/unit URL (`/building/the-saratoga/28bc`) does NOT work as an API parameter.
The page embeds multiple IDs (old and new listings). To get the *current active* listing ID, look for `saleInventorySummary.availableListingDigests` in the page source — the first ID there is the active one.
Do NOT use the first `/sale/{id}` you find on the page — it may be an older delisted listing.

**Free tier math:**
- 25 requests/month
- 1 search call = 1 request (returns up to 100 listing IDs + prices)
- 1 detail call = 1 request (returns full data for 1 listing)
- Practical budget: 1 search + 24 detail lookups/month. Fine for targeted due diligence; too tight for bulk scanning.
- If the API proves useful: Pro tier is $50/mo for 10,000 requests.

---

## Recommendation

**Proceed with this API** for per-property due diligence lookups once you have shortlisted candidates from StreetEasy browsing. The detail endpoint is solid.

**Do NOT rely on it for bulk scanning** at free tier. StreetEasy's own UI handles the browsing; use this API for the 5-20 properties you're actually serious about.

**Requests used this session:** ~6 of 25 monthly free tier. ~19 remaining.

---

---

# APIFY — memo23/streeteasy-ppr

Date: 2026-04-19
Actor: `memo23/streeteasy-ppr` (Pay-Per-Event)
Run ID: `T8c9OCnFjkiHFssFB`
Cost: $0.009 for 1 listing
Duration: 17 seconds

---

## Overall Verdict: 🟢 GREEN — fills every gap RapidAPI left

Price history with full event timeline, agent name + direct phone + email, exact pricing match, sqft, beds/baths — all present. This is the complete data source.

---

## Test — Specific Listing: 330 East 75th Street #28BC (ID: 1818978)

**Input URL:** `https://streeteasy.com/sale/1818978`

### Required Fields Scorecard

| Field | Expected | Got | Status |
|---|---|---|---|
| Address | 330 East 75th Street #28BC | 330 East 75th Street, Unit 28BC | ✅ Exact |
| Price | $3,300,000 | $3,300,000 | ✅ Exact |
| Common Charges (HOA) | $2,448/mo | $2,448/mo | ✅ Exact |
| Taxes | $3,368/mo | $3,368/mo | ✅ Exact |
| Tax Abatement | No info | Not in response | ❌ Still missing |
| Days on Market | 3 | 3 | ✅ Exact |
| Price History | Date + Price + Event | ✅ Full timeline back to 2006 | ✅ **Gap filled** |

### Nice-to-Have Fields Scorecard

| Field | Status | Notes |
|---|---|---|
| Seller's agent name | ✅ Present | Matthew Gulker |
| Seller's agent phone | ✅ Present | (917) 848-1338 |
| Seller's agent email | ✅ Present | mgulker@elliman.com |
| Agent firm | ✅ Present | Douglas Elliman |
| Listing description | ✅ Present | Full text |
| sqft | ✅ 2,400 | `livingAreaSize` field |
| Beds / Baths | ✅ 4 bed / 3 full bath | See note below |
| $/sqft | ✅ $1,375 | `price_per_sqft` field |
| Building amenities | ✅ Present | Structured list (CONCIERGE, DOORMAN, ELEVATOR, GARAGE, FIOS, PACKAGE_ROOM, LIVE_IN_SUPER, COURTYARD, ROOF_DECK) |
| Year built | ✅ 1985 | Via building fields |
| Building units | ✅ 197 residential units | Present |
| Property type | ✅ condo | `RESALE` sale type |
| Neighborhood | ✅ Lenox Hill | `area_name` field |

**Note on beds/baths discrepancy:** Apify returns 4 beds / 3 full baths / 0 half baths. RapidAPI returned 3 beds / 2.5 baths. The listing description itself says "4 Bedrooms" — the Douglas Elliman re-listing appears to have reclassified the home office as a 4th bedroom. Apify matches the live listing; RapidAPI retained the old Sotheby's configuration.

### Full Price History (back to 2006)

| Date | Price | Event | Broker |
|---|---|---|---|
| 2026-04-16 | $3,300,000 | LISTED | Douglas Elliman |
| 2026-03-02 | $3,395,000 | DELISTED | Sotheby's International Realty |
| 2025-11-19 | $3,395,000 | LISTED | Sotheby's International Realty |
| 2019-05-23 | $4,195,000 | NO_LONGER_AVAILABLE | — |
| 2018-07-30 | $3,700,000 | NO_LONGER_AVAILABLE | — |
| 2018-05-10 | $3,700,000 | LISTED | Sotheby's International Realty |
| 2017-12-21 | $4,195,000 | TEMPORARILY_OFF_MARKET | — |
| 2017-12-07 | $4,195,000 | PRICE_DECREASE (−5%) | — |
| 2017-09-21 | $4,395,000 | LISTED | Warburg |
| 2006-12-04 | $3,495,000 | NO_LONGER_AVAILABLE | — |

**Insight:** This unit has been on the market multiple times since 2006, with an asking peak of $4,395,000 in 2017. It never cleared $3,700,000. Current ask of $3,300,000 is the lowest it's been listed in 20 years — and it went unsold at $3,395,000 for 103 days just last quarter.

---

## What Apify Has That RapidAPI Doesn't

| Gap in RapidAPI | Apify Status |
|---|---|
| Per-listing price history (event timeline) | ✅ Fully present, back to 2006 |
| Agent name | ✅ Matthew Gulker |
| Agent phone | ✅ (917) 848-1338 |
| Agent email | ✅ mgulker@elliman.com |
| Building unit count | ✅ 197 units |
| Beds/baths aligned to active listing | ✅ Matches current Douglas Elliman listing |

---

## Cost Model

- $3.00 per 1,000 results (Pay-Per-Event)
- 1 listing = $0.009
- 100 UES listings = ~$0.90
- 1,000 UES listings = ~$3.00
- Monthly Apify free tier ($5 credit) covers ~550 listing scrapes

**For bulk UES scanning (1,000 listings):** $3. No monthly cap pressure.
**For targeted due diligence (20 listings):** $0.18. Essentially free.

---

## Recommendation

**Use Apify memo23/streeteasy-ppr as the primary data source.** It fills every significant gap RapidAPI left — price history, agent contact, unit count — and costs under $1 for typical use.

**RapidAPI's role narrows** to a fast/cheap check when you already have a listing ID and only need basic facts (price, sqft, HOA, taxes). Its 25-request free tier is fine for that. But it should not be the primary source.

**Together the stack is:**
1. StreetEasy UI → browsing and discovery
2. Apify memo23 → bulk pulls + full detail including price history + agent contact
3. RapidAPI → optional fast lookup if Apify quota is a concern (unlikely at free tier)
4. NYC Open Data (PLUTO, ACRIS) → supplemental building/sales records for shortlisted candidates
