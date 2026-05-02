# SqFt Estimation for Co-ops

NYC co-ops don't publish official square footage at the unit level, so we
estimate from floor plans. Established Session 10 (2026-05-02). 15 co-op
listings now have estimated sqft in StreetHard, all flagged
`sqft_estimated: true` and rendered in gray with a tooltip explaining the
calibration source.

## Why Co-ops Need This

ACRIS doesn't store co-op transactions at the unit level (co-op shares
aren't deeded real property), and Compass / StreetEasy floor plans typically
omit a published sqft figure for co-ops. Without sqft, the StreetHard table
columns Price/SqFt and Pmt/SqFt show as `—`, which is the single most
useful comparison metric for screening listings — so the dashes are a real
gap, not a cosmetic one.

## The Method (Pixel-Polygon)

The reliable method, developed and validated against 8 plans with known
official figures:

1. **Detect the apartment polygon.** Threshold the floor plan image to
   "non-white" pixels, morphologically close to bridge thin wall gaps,
   take the largest connected blob, fill its interior contour. This is
   the gross square footage area in pixels (walls included).

2. **Calibrate the pixel-to-feet scale from one labeled rectangular room.**
   Pick a clean isolated room with a labeled dimension (almost always a
   bedroom; the Living Room is often merged with adjacent rooms in the
   detection step). Read its bounding-box pixel dimensions. The
   architect-and-contractor heuristic: prefer the room with the longest
   labeled wall, since longer rulers minimize relative error from
   pixel-rounding noise.

3. **Compute.** `sqft = polygon_pixels / (px/ft)²`

4. **Sanity-check via $/sqft.** Manhattan UES residential trades in
   roughly $900–$1,800/sqft. If the computed sqft yields a $/sqft outside
   that band, something is wrong — either polygon detection mis-fired or
   the calibration room's pixel measurement is off. Override manually
   with a labeled-room-sum + walls fallback estimate and document the
   reason in `sqft_estimate_note`.

## What Doesn't Work

Things we tried and discarded:

- **Eyeball-based "Method 1" estimates with era-conditioned gross-up factors.**
  Sum labeled rooms, estimate unlabeled spaces (baths, hallways, closets)
  from typology, gross up 11–16% based on building age. This was the
  starting point but proved noisy: typology priors for unlabeled bath/hall
  sizes are off by ±50%, and pre-war Park Avenue masonry walls don't
  follow the same gross-up as post-war concrete construction. Methodology
  worked to ~5%, not the 2% we wanted.

- **Auto-matching detected room blobs to labeled dimensions by aspect ratio.**
  Multiple rooms share aspect ratios; matches were unreliable. Required
  manually identifying which detected blob corresponds to the calibration
  room.

- **Bounding-box-of-polygon = longest exterior wall.** The architect's
  heuristic — "longest labeled dimension equals longest exterior wall" — is
  often wrong. The longest exterior wall spans multiple rooms; the longest
  labeled dimension is just one room.

- **OCR + automated calibration.** Would solve the manual room-pick step
  but adds substantial complexity. Not built; manual room identification
  takes ~5 seconds per plan.

## Failure Modes Documented

The pixel method breaks on:

1. **Multi-floor plans (duplexes/triplexes).** When two or three floors
   are shown on one image, the largest-blob detection only catches one
   floor. Manual override needed. 829 Park Avenue 6/7B was a clean
   example: raw method gave 4,850 sqft (way too high; would imply
   $567/sqft). Adjusted to 2,400 based on labeled-room sum + walls.

2. **Sparse-line B&W blueprint plans.** When walls are drawn as thin
   single-line strokes (no fill, no thick border), morphological closing
   doesn't bridge gaps cleanly and the polygon comes out fragmented.
   1435 Lexington 11E hit this — polygon was 60% of the apartment's true
   area.

3. **Non-uniform image scaling.** Some floor plan images are squashed
   or stretched along one axis (horizontal scale ≠ vertical scale).
   Calibration off any single labeled room produces inconsistent scale
   estimates. 201 East 77th #14AF was the worst case; three different
   calibration rooms gave 1,768, 1,920, and 1,840 sqft. Methodology
   error band on that plan is ±10% rather than the usual ±2%.

## Validated Accuracy

Tested against 8 plans with known official figures:

| Plan | Official | Estimate | Miss |
|------|----------|----------|------|
| 975 Park 16A | 2,200 | 2,209 | +0.4% |
| 330 E 79th 10A | 2,400 | 2,468 | +2.8% |
| 870 5th 15E | 2,400 | 2,619 | +9.1% |
| 167 E 61st 24C | 1,600 | 1,595 | -0.3% |
| 201 E 79th 6I | 1,900 | 1,936 | +1.9% |
| 563 Park 4E | 2,000 | 2,144 | +7.2% |
| 8 E 96th 7C | 1,800 | 1,821 | +1.2% |
| 525 E 82nd 6EFG | 2,500 | 2,602 | +4.1% |

3/8 within 2%, 5/8 within 5%, 7/8 within 10%. The misses come from
visual pixel-coordinate-reading noise (±10 pixels per wall endpoint).
On well-behaved plans (flat-scale, clean color separation, isolated
rooms), 0–3% accuracy is consistent.

For screening purposes (deciding which units to visit), this is more
than enough. **For negotiation/offer pricing, get an ANSI-Z765
measurement** from NYC Measure or a Compass partner ($250–400). That's
the number that matters when arguing over $/sqft.

## How It's Rendered in StreetHard

When `sqft_estimated: true` is set on a listing, the table view shows
SqFt, Price/SqFt, and Pmt/SqFt cells in gray (`color: #9aa0a6`) with a
dotted underline and a hover tooltip displaying `sqft_estimate_note`.
Card view applies the same styling to the SqFt and Price/SqFt chips.

The behavior is data-flag-driven: any future estimate just needs
`sqft_estimated: true` on the listing record to inherit the styling.
No app code changes required.

## Data Schema

Fields on each listing in `data/db.json` and `data/latest.json`:

- `sqft` — integer, the estimate
- `sqft_estimated` — boolean, `true` for our estimates, absent or `false`
  for official sqft from Apify
- `sqft_estimate_method` — string identifier; currently
  `"pixel_polygon"` for plans we calculated, `"floorplan_sum"` for the
  earlier Method 1 estimate on 14AF
- `sqft_estimate_note` — human-readable text shown in the tooltip:
  the calibration room and dimension used, plus the estimated range and
  any sanity-check overrides
- `price_per_sqft` — recomputed from `price / sqft` whenever sqft changes

## Listings With Estimates as of 2026-05-02

Sessions 10 and 11 added pixel-method estimates for 15 co-ops:

| Listing | Price | Sqft | $/sqft | Method note |
|---------|-------|------|--------|-------------|
| 201 E 77th 14AF | $2.799M | 1,700 | $1,646 | Floorplan sum; user pushback; held at 1,700 |
| 1170 5th 6A | $3.2M | 3,500 | $914 | Primary Bedroom calibration |
| 245 E 87th PH | $3.3M | 3,000 | $1,100 | Primary Bedroom; terraces excluded |
| 8 E 96th 14C | $3.25M | 2,400 | $1,354 | Living/Dining calibration |
| 829 Park 10B | $2.85M | 1,750 | $1,629 | Duplex; upper-level Primary Bedroom |
| 1050 5th 12C | $3.5M | 2,800 | $1,250 | Master Bedroom 19' |
| 1050 5th 2E | $3.395M | 2,550 | $1,331 | Primary Bedroom 18'8" |
| 115 E 67th 8B | $2.895M | 2,300 | $1,259 | Living/Dining 26' |
| 1215 5th 5B | $2.995M | 3,400 | $881 | Living Room 29'6"; large pre-war |
| 1220 Park 2C | $2.895M | 3,000 | $965 | Adjusted from 3,800 (sanity) |
| 196 E 75th 3AB | $3.395M | 2,500 | $1,358 | Master Bedroom 17' |
| 29 E 64th 10C | $2.75M | 1,600 | $1,719 | Living Room 24' |
| 3 E 69th 7/8A | $3.1M | 2,000 | $1,550 | Duplex; pixel under-detected |
| 55 E 87th 4JK | $3.25M | 2,550 | $1,275 | Living Room 28'9" |
| 829 Park 6/7B | $2.75M | 2,400 | $1,146 | Duplex; raw 4,850 inflated |

Sanity-adjusted estimates (1220 Park 2C, 3 E 69th 7/8A, 829 Park 6/7B) have
explicit notes documenting the override.

## File Locations

- Floor plan images: `floorplans/` (gitignored; user-side scratch space)
- Estimation script: built ad-hoc in `/tmp/`; not committed because the
  workflow is interactive (Claude reads each plan, picks a calibration
  room visually, computes)
- Application rendering: CSS class `.estimated` in `index.html` (lines
  ~277–283); JS `wrapEst()` helper in `renderTable()` and `renderCards()`
