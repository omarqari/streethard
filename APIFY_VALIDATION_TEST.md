# Apify Validation Test — The Saratoga

Use this test at the start of any session to confirm Apify `memo23/streeteasy-ppr` is working before running a full pull.
One listing, one run, ~20 seconds, ~$0.009.

---

## Test Listing: Ground Truth

**Property:** 330 East 75th Street, Unit 28BC — The Saratoga, Lenox Hill, Manhattan  
**StreetEasy listing ID:** `1818978`  
**Direct URL:** `https://streeteasy.com/sale/1818978`  
**Listed by:** Douglas Elliman (Matthew Gulker, mgulker@elliman.com, (917) 848-1338)  
**Listed:** 2026-04-16  
**Status as of 2026-04-19:** Active

### Expected Field Values (ground truth from StreetEasy)

| Field | Expected Value |
|---|---|
| Price | $3,300,000 |
| Common Charges | $2,448/mo |
| Property Taxes | $3,368/mo |
| Bedrooms | 4 |
| Full Bathrooms | 3 |
| SqFt | 2,400 |
| Price/SqFt | ~$1,375 |
| Year Built | 1985 |
| Building Units | 197 |
| Days on Market | 3 (as of 2026-04-19) |
| Type | Condo |
| Agent Name | Matthew Gulker |
| Agent Phone | (917) 848-1338 |
| Agent Email | mgulker@elliman.com |
| Agent Firm | Douglas Elliman |
| Price History | Full timeline back to 2006 (see below) |

### Expected Price History (minimum entries to verify)

| Date | Event | Price |
|---|---|---|
| 2026-04-16 | LISTED | $3,300,000 |
| 2026-03-02 | DELISTED | $3,395,000 |
| 2025-11-19 | LISTED | $3,395,000 |
| 2017-09-21 | LISTED | $4,395,000 |

If price history goes back to at least 2017–2019, the actor is returning full history correctly.

---

## How to Run the Test

### Step 1 — Submit the Apify run

Navigate to: `https://console.apify.com/actors/ptsXZUXADV3OKZ5kd/input`

Use the JSON tab and paste exactly:

```json
{
  "startUrls": [
    { "url": "https://streeteasy.com/sale/1818978" }
  ],
  "addresses": [],
  "flattenDatasetItems": true,
  "monitoringMode": false,
  "moreResults": false,
  "maxItems": 1,
  "proxy": {
    "useApifyProxy": true,
    "apifyProxyGroups": ["RESIDENTIAL"]
  }
}
```

Click **Save & Start**. The run should complete in ~20 seconds.

### Step 2 — Check for 403s immediately

In the run log, look at the first few lines. If you see:
- `[TRANSLATE_URL] entering: 403` → **Actor is broken**. Stop. Post to the issue thread and wait for memo23's fix.
- Normal scraping output (URLs being processed) → Continue to Step 3.

### Step 3 — Fetch the results

Go to the **Storage** tab of the completed run. Copy the Dataset ID. Then fetch:

```
https://api.apify.com/v2/datasets/{DATASET_ID}/items?format=json&clean=true
```

You should get a single JSON object (array of 1 item).

### Step 4 — Verify required fields

Check these fields against the expected values above:

```
saleListingDetailsFederated_data_saleByListingId_pricing_price              → 3300000
saleListingDetailsFederated_data_saleByListingId_pricing_maintenanceFee     → 2448
saleListingDetailsFederated_data_saleByListingId_pricing_taxes              → 3368
saleListingDetailsFederated_data_saleByListingId_propertyDetails_livingAreaSize → 2400
saleListingDetailsFederated_data_saleByListingId_propertyDetails_bedroomCount  → 4
saleDetailsToCombineWithFederated_data_sale_building_year_built             → 1985
saleDetailsToCombineWithFederated_data_sale_building_building_type          → CONDO (or similar)
extraListingDetails_data_sale_price_histories_json                          → non-empty JSON string
```

Also confirm `contacts_json` is populated and parses to an array with at least one entry containing `name`, `phone`, and `email`.

### Step 5 — Pass/Fail verdict

**PASS:** Price = $3,300,000, maintenance = $2,448, taxes = $3,368, sqft = 2,400, price history present with 2026-04-16 LISTED event.  
**FAIL:** Any of those fields missing, wrong, or price history empty/absent.

If FAIL: dump the raw response in full and paste to Claude. Field names may have changed — normalize() will need updating before a full pull.

---

## What This Test Catches

- **403 errors** (StreetEasy iOS API key rotation) — caught in Step 2
- **Field name changes** (Apify schema drift) — caught in Step 4
- **Price history regression** — caught in Step 4/5
- **Agent contact regression** — caught in Step 4/5
- **Proxy failures** (residential proxies not routing correctly) — caught in Step 2

## What This Test Does NOT Catch

- **Search URL pagination** — single listing test can't verify the actor pages through 500+ results
- **Rental field names** — this is a sale listing; rental normalization must be tested separately
- **Co-op maintenance vs. taxes split** — this is a condo; test a co-op separately if that matters

---

## Cost

~$0.009 per run (1 Pay-Per-Event result). Negligible.

---

## History of Actor Outages

| Date | Duration | Root Cause | Resolution |
|---|---|---|---|
| ~2026-03-27 | ~hours | StreetEasy rotated iOS API key | memo23 patched the actor |
| 2026-04-19 | Ongoing | StreetEasy rotated iOS API key again | Awaiting memo23 fix |

This is the known failure mode for this actor. When 403s appear, it is almost certainly this cause. Check the actor's Issues tab first before debugging anything else.
