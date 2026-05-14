# Mobile Card Redesign — Build Plan v2

Plan for replacing the markup inside `renderCards()` (index.html line 2218)
with a compact mobile layout that elevates OQ/RQ rank + notes as the visual
centerpiece. Incorporates Chief Architect + CTO review.

## Pre-flight check (5 min)

Open `PRODUCT-BACKLOG.md` and confirm nothing in the 14-item slate beats
"the card surface I use 80% of the time on mobile is 40% too tall." If yes,
park this and do that instead. Most likely outcome: nothing beats it.

## Goal

Cut ~40% off card height. Promote OQ/RQ blocks to the visual centerpiece.
Remove bucket toggle buttons (swipe gestures already in `initCardSwipe()`).
Remove agent contact action buttons. Keep every existing data path.

## Scope

**One PR.** No feature flag. No phase rollout. Rewrite in place, push, test
on iPhone, ship. If it's broken, `git revert`.

**Target: 3 hours. Hard cap: 5.** If the comparison-delta line or the
textarea-swipe conflict each eat more than 45 minutes, ship without them
and revisit later.

## Code changes — all in index.html

### Markup — `renderCards()` (line 2218)

Replace the template body. Same listing object in, restructured DOM out:

- **Header strip:** building + neighborhood + last-seen indicator on one row.
- **Address line.**
- **Badge row:** type pill (CONDO/COOP), price-cut amount badge ("✂ −$250K"),
  days-listed badge, built-year chip. All from existing `_phCache` data plus
  the new derived signals below.
- **Price + stats row:** price + trend (↓ from $4.25M) + monthly all-in on
  the left; bed/bath/sqft/$psf laddered on the right; comparison delta
  underneath in green/red.
- **OQ block:** blue-tinted background, OQ label + rank input on one row,
  notes textarea below. Always visible, no expand-to-edit.
- **RQ block:** coral-tinted background, same shape.
- **Utility row:** Seen toggle on the left, "View on StreetEasy" on the right.

Remove from the current template (lines 2246–2251 et al):
- The Inbox/Shortlist/Archive button cluster — swipe handles this.
- The Built-year cell in `.card-stats` — promoted to a badge.
- The per-card mortgage rate/term display — already global in the header.
- The agent contact buttons.
- The footer "Yorkville" — already in the header.

### CSS — add to existing stylesheet

New classes alongside existing (no `.v4-` prefix — straight replacement):

- `.card-header`, `.card-address`, `.card-badge-row`
- `.card-price-stats` (the compact two-column row)
- `.card-oq-block` (background `#F5F8FD`, OQ rank input border `#B5D4F4`)
- `.card-rq-block` (background `#FDF6F3`, RQ rank input border `#F5C4B3`)
- `.card-utility-row`

Update the existing `@media (max-width: 768px)` block (line 936). Desktop
card view at ≥769px is **explicitly unchanged in this PR** — same template
will render fine at desktop widths because cards are already capped.

### Derived signals — three pure functions

```
priceCutAmount(listing) → { absolute: number, percent: number } | null
  // upgrades existing priceSignals() to surface the dollar delta of
  // the most recent PRICE_CHANGED event, not just the ✂ icon

lastSeenLabel(listing) → "today" | "Nd ago" | "—"
  // from listing.last_pass1; returns "—" when last_pass1 is null
  // (new listings only)

psfDeltaVsShortlist(listing, median) → number | null
  // returns a number, formatted at the call site; returns null when
  // median is undefined (empty shortlist) — call site hides the line
```

`shortlistMedian` is computed once per render pass and memoized keyed on
the active filter set (not just timestamp), so filter changes invalidate
correctly.

## Verified in code — not actually risks

These two were in v1; verifying the code shows they don't apply:

- **Textarea triggering swipe.** `initCardSwipe()` at line 2152 already has
  `if (e.target.closest('input,textarea,a,button,.seen-toggle,.rank-val')) return;`
  The new OQ/RQ textareas inherit that protection for free. No change needed.
- **Debounced note save lost on swipe-archive.** `debounceNote()` stores its
  timer in module-scoped `noteTimers` and captures `value` in the setTimeout
  closure. The save fires whether the card is in the DOM or not (the "Saved"
  badge flash is gated with `if (badge)` and silently skips). No flush needed.

## Real risks — with mitigations

| Risk | Mitigation |
|---|---|
| `last_pass1` null on brand-new listings | `lastSeenLabel` returns "—" (or hides the chip) for null input. |
| Empty shortlist makes comparison delta meaningless | `psfDeltaVsShortlist` returns null when median undefined; call site omits the line. |
| Pass1-only listings (8 today, all rentals) lack `monthly_fees`/`monthly_taxes` | **Decision: show monthly as "—" with a small "pending data" tooltip**, rather than NaN or hidden block. Render-side check; no change to `calcMonthlyTotal()`. |
| Tinted OQ/RQ blocks contrast against navy header | Verify `#F5F8FD` and `#FDF6F3` pass WCAG AA against adjacent `#0E1730`. Both are >7:1; safe. |
| Swipe discoverability now that bucket buttons are gone | Add a subtle `‹ swipe ›` hint at the bottom of the card on the first 3 sessions (localStorage flag), then hide. |
| Desktop regression at ≥769px | Explicitly unchanged in this PR. New CSS classes only apply inside `@media (max-width: 768px)`. |

## Out of scope

- Photos. No `images` field in db.json today. Separate ask to memo23.
- Floor-plan integration on the card.
- Tablet variant.
- Swipe animation polish.
- Shared component refactor between table row and card (premature).

## Deploy

One commit via `mcp__github__push_files` to current branch. GitHub Pages
deploys in ~60 seconds. Test on Omar's iPhone. If broken: `git revert`
and re-push. Blast radius: card view degraded for one evening.

## Done means

- v4 card renders on iPhone Safari at expected ~430px height.
- OQ + RQ rank inputs and notes textareas save via existing `putStatus`
  with no regression.
- Swipe right/left moves the card between buckets without conflict from
  textarea focus.
- "Mark seen" and "View on StreetEasy" both work.
- Desktop card view unchanged (visual check at ≥1024px).
