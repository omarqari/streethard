# TEST CRITERIA

Acceptance criteria for evaluating any data source (RapidAPI, Apify, etc.) before committing to it.

---

## Test 1 — Bulk Search: Active UES Listings

**Query:** Active sale listings in the Upper East Side, Manhattan.

**Pass criteria:**
- Returns multiple active listings (not an empty result or error)
- Results include at minimum: address, price, beds, baths
- Results are filterable by neighborhood (UES specifically, not all of Manhattan)
- Results appear current (not stale / delisted properties)

**Fail criteria:**
- Zero results
- No neighborhood filtering
- Missing price on majority of results

---

## Test 2 — Specific Listing Detail: 330 East 75th Street #28BC

**Reference listing:** https://streeteasy.com/building/the-saratoga/28bc  
**Building:** The Saratoga  
**Unit:** 28BC  
**Full address:** 330 East 75th Street #28BC, New York, NY

### Required Fields (must be populated to pass)

| Field | Expected Value |
|---|---|
| Address | 330 East 75th Street #28BC |
| Price | $3,300,000 |
| Common Charges | $2,448/mo |
| Real Estate Taxes | $3,368/mo |
| Tax Abatement | Should indicate none / no abatement |
| Days on Market | Any value — just must be present |
| Price History | At minimum one entry with: Date, Price, Event |

### Nice-to-Have Fields (record what populates, don't fail on absence)

| Field | Notes |
|---|---|
| Seller's agent name | |
| Seller's agent contact info (phone / email) | |
| Listing description (free text) | |
| Home features (beds, baths, sqft, floor, etc.) | |
| Building amenities | |
| Building units total | |
| Building stories | |
| Year built | |

---

## Scoring

After running both tests against a data source, grade it:

**Green** — Required fields populated on the specific listing + bulk search returns UES results with address and price. Move forward with this source.

**Yellow** — Bulk search works but specific listing is missing 1–2 required fields. Note which fields and decide if they're dealbreakers.

**Red** — Bulk search returns nothing useful, or specific listing is missing most required fields. Try the next source in the fallback chain.

---

## Fallback Order (if current source fails)

1. RapidAPI `realestator` (primary — test first)
2. Apify `qwady/Borough` (free tier, NYC-specific)
3. Apify `jupri/streeteasy-scraper` (pay-per-result, ~$1/1000)
