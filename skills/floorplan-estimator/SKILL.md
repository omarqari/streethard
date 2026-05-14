---
name: floorplan-estimator
description: >
  Estimate square footage from co-op floor plan images using the pixel-polygon
  method, then update StreetHard listings in db.json. Use this skill whenever
  the user mentions floor plans, sqft estimation, square footage, co-op area,
  or drops images into the floorplans/ directory. Also trigger when the user
  says "process floor plans", "estimate sqft", "update square footage", or
  asks about unprocessed floor plans. If the user adds a file to floorplans/
  and asks you to handle it, this is your skill.
---

# Floor Plan SqFt Estimator

Estimate square footage for NYC co-op listings from floor plan images using
the validated pixel-polygon method (~2% accuracy on clean plans). Updates
StreetHard's db.json and pushes to GitHub so the app reflects the new data.

## Workflow Overview

1. **Scan** — find new/unprocessed floor plans in `floorplans/`
2. **Match** — link each image to a listing in db.json
3. **Estimate** — run pixel-polygon method per plan
4. **Validate** — check $/sqft is in $900–$1,800 range
5. **Update** — write estimates to db.json, regenerate latest.json
6. **Push** — commit via `scripts/git_push.py`

## Step 1: Scan for Unprocessed Floor Plans

Read the tracking file `floorplans/processed.json`. If it doesn't exist,
create it as an empty object `{}`. This file maps floor plan filenames to
their processing status:

```json
{
  "1050 5th Avenue 12C.webp": {
    "listing_id": "1814435",
    "sqft": 2800,
    "method": "pixel_polygon",
    "processed_at": "2026-05-02",
    "status": "done"
  }
}
```

List all image files in `floorplans/` (extensions: .webp, .png, .jpg, .jpeg).
Compare against processed.json to identify **new** files — any image filename
not present as a key in processed.json.

**Seed processed.json on first run.** If the file doesn't exist yet, build it
from db.json: for every listing with `sqft_estimated: true`, find the matching
floor plan file by address+unit, and populate the entry. This avoids
re-processing the 15 listings already estimated in Sessions 10–11.

Report to the user: "Found N new floor plan(s) to process: [filenames]"

If no new files, say so and stop.

**Skip files that are validation benchmarks.** Files with sqft already in the
filename (e.g., `870 5th Avenue 15E (2400 sqft).webp`) were used to validate
the method against known figures. Mark them in processed.json with
`"status": "benchmark"` and skip estimation.

**Skip the garbage file.** `d6dd859fa879300f5f904a0b0b4f7c7b-se_extra_large_1500_800.webp`
is a StreetEasy CDN artifact, not a floor plan. Mark it `"status": "skipped"`.

## Step 2: Match Floor Plan to Listing

Floor plan filenames follow the pattern `{address} {unit}.{ext}` — e.g.,
`1050 5th Avenue 12C.webp`. Parse the address and unit from the filename.

Search db.json listings for a match on address + unit. Matching rules:
- Normalize "Fifth" ↔ "5th", "East" ↔ "E", "West" ↔ "W", etc.
- Unit separators: "7-8A" in filename = "7/8A" in listing
- Strip trailing spaces from filenames
- If no match found, report to user and skip (the listing might not be in
  the current dataset, or the filename might need manual correction)

Once matched, pull the listing's `price` field for the sanity check.

## Step 3: Estimate SqFt — The Pixel-Polygon Method

This is the core estimation step. It requires Claude's visual judgment to
pick the calibration room, then runs the bundled script for computation.

### 3a. Read the floor plan image

Use the Read tool to visually inspect the floor plan image. Look for:
- Labeled room dimensions (e.g., "13'6\" x 18'0\"" or "13.6 x 18")
- Which rooms are cleanly isolated rectangles (best for calibration)
- Whether this is a multi-floor plan (duplex/triplex) — if so, flag for
  manual handling

### 3b. Pick the calibration room

Choose ONE room that meets these criteria (in priority order):
1. **Cleanly isolated rectangle** — not merged with adjacent rooms in the
   plan's visual layout
2. **Longest labeled wall** — longer rulers minimize relative error from
   pixel-rounding noise
3. **Prefer bedrooms** — living rooms are often visually merged with
   dining rooms or foyers, making their pixel boundaries ambiguous

Record which room you picked and its labeled dimensions.

### 3c. Measure calibration room pixel dimensions

From the floor plan image, identify the pixel coordinates of the
calibration room's corners. Measure:
- **room_px_width**: horizontal pixel span of the room
- **room_px_height**: vertical pixel span of the room

Parse the labeled dimensions into feet:
- `13'6"` = 13.5 ft
- `18'0"` = 18.0 ft
- `19'8"` = 19.67 ft (8/12)

### 3d. Run the estimation script

```bash
python3 scripts/estimate_sqft.py "floorplans/{filename}" \
    --room-px-width {W} --room-px-height {H} \
    --room-ft-width {W} --room-ft-height {H} \
    --listing-price {price}
```

The script path is relative to the project root. In the sandbox, use:
`/sessions/nice-quirky-noether/mnt/NYC Real Estate Advisor/skills/floorplan-estimator/scripts/estimate_sqft.py`

And the image path:
`/sessions/nice-quirky-noether/mnt/NYC Real Estate Advisor/floorplans/{filename}`

**Install deps if needed:** `pip install numpy scipy pillow --break-system-packages`

The script outputs JSON with `sqft`, `px_per_ft`, `scale_divergence_pct`,
and `sanity_check`. If exit code is 2, the sanity check failed — see Step 4.

### 3e. Check scale divergence

If `scale_divergence_pct` > 15%, the image may be non-uniformly scaled
(stretched/squashed). This means the calibration room's aspect ratio in
pixels doesn't match its real aspect ratio. Options:
- Try a different calibration room
- Accept higher error band (~5-10% instead of ~2%)
- Note the divergence in `sqft_estimate_note`

## Step 4: Validate $/sqft

The sanity check is critical. Manhattan UES residential trades at
$900–$1,800/sqft. If the estimate falls outside:

**$/sqft < $900** — sqft is overestimated. Common causes:
- Multi-floor plan: polygon detected both floors as one blob
- Closing iterations too high: filled in exterior space (courtyards, hallways)
- Fix: reduce `--close-iterations` to 3, or use manual room-sum fallback

**$/sqft > $1,800** — sqft is underestimated. Common causes:
- Sparse-line blueprint: polygon fragmented, missed rooms
- Threshold too aggressive: labeled text pixels eaten into room area
- Fix: lower `--threshold` to 200, increase `--close-iterations` to 7,
  or use manual room-sum fallback

**Manual room-sum fallback:** When the algorithm fails, sum all labeled
room dimensions and add 15% for walls/hallways/closets. Document this
as `sqft_estimate_method: "floorplan_sum"`.

## Step 5: Update db.json

Once you have a validated estimate, update the listing in db.json:

```python
listing['sqft'] = estimated_sqft
listing['sqft_estimated'] = True
listing['sqft_estimate_method'] = 'pixel_polygon'  # or 'floorplan_sum'
listing['sqft_estimate_note'] = '{Room Name} {dimension}; ~{sqft} sqft'
listing['price_per_sqft'] = round(listing['price'] / estimated_sqft)
```

The `sqft_estimate_note` should be human-readable and document the
calibration source. Examples:
- "Primary Bedroom 13'6\" x 18'; ~2,800 sqft"
- "Living Room 28'9\"; duplex adjusted from 4,850 raw"
- "Floorplan sum; sparse blueprint prevented polygon method"

After updating db.json, regenerate latest.json:

```python
import json
with open('data/db.json') as f:
    db = json.load(f)
listings = list(db['listings'].values())
latest = {
    'generated_at': db.get('last_updated'),
    'listings': listings
}
with open('data/latest.json', 'w') as f:
    json.dump(latest, f)
```

## Step 6: Update processed.json and Push

Add the processed floor plan to `floorplans/processed.json`:

```json
{
  "filename.webp": {
    "listing_id": "1234567",
    "sqft": 2800,
    "method": "pixel_polygon",
    "calibration_room": "Primary Bedroom 13'6\" x 18'",
    "price_per_sqft": 1250,
    "processed_at": "2026-05-02",
    "status": "done"
  }
}
```

Push changes via the GitHub API script (never use git CLI from sandbox):

```bash
python3 scripts/git_push.py "sqft estimate: {address} {unit} = {sqft} sqft" \
    data/db.json data/latest.json
```

Note: `processed.json` is in `floorplans/` which is gitignored — it stays
local and doesn't get pushed. That's fine; it's a local tracking file.

## Failure Modes Reference

These are documented failure modes from the validation runs. Be ready for them:

| Failure | Symptom | Fix |
|---------|---------|-----|
| Multi-floor plan | $/sqft way too low (<$600) | Sum labeled rooms per floor + 15% walls |
| Sparse-line blueprint | $/sqft way too high (>$2000) | Lower threshold, increase closing, or manual sum |
| Non-uniform scaling | Scale divergence >15% | Try different calibration room, accept wider error band |
| Merged rooms | Calibration room pixels include adjacent room | Pick a different, more isolated room |
| No labeled dimensions | Can't calibrate | Cannot estimate; skip and note why |

## Batch Processing

When multiple new floor plans are detected, process them one at a time.
After each successful estimate, immediately update db.json and
processed.json (don't batch all updates to the end — if something fails
midway, you lose the earlier work).

Push to GitHub once at the end after all estimates are complete, not after
each individual one (to avoid excessive commits).

## Summary Report

After processing all new floor plans, give the user a summary:

```
Processed 3 new floor plans:
  68 East 86th Street 10A — 1,950 sqft ($1,410/sqft) via pixel_polygon
  169 East 94th Street TWNHS — skipped (no labeled dimensions)
  [filename] — 2,200 sqft ($1,364/sqft) via pixel_polygon

Updated db.json and pushed to GitHub.
Skipped: 1 (no dimensions)
```
