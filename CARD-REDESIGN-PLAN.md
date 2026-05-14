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

---

## What actually shipped (post-ship addendum)

### Commits (in order)
- `b8f5bb5aed` — Card v4 markup + CSS + signal helpers
- `3ab9d26239` — Polish: `##` strip, auto-grow textareas, SVG eye
- `3855b4df09` — Polish: numeric-only OQ/RQ inputs, remove last-seen pill
- `60548d4fa9` — Polish: labeled Seen button
- `cf2717c6c6` — Mobile: hide view toggle (subsequently flipped)
- `78f5628fff` — Mobile: restore view toggle, table horizontally scrollable

### Where ship matched the plan
- One PR. No `?card-v4=1` flag. Confirmed correct call.
- All three derived signals shipped. `psfDeltaVsShortlist` returns a number; call site formats. `priceCutAmount` uses peak-vs-current and matches the "−$XK" mockup.
- Pass1-only listings render `—/mo all-in` with a "pending Pass 2 data" tooltip. Decided up-front, not on device.
- Desktop card view at ≥769px completely unchanged.
- Real-device test on Omar's iPhone was the verification step. No CI.

### Where ship diverged from the plan
- **Two flagged risks turned out to be non-issues.** The plan listed "textarea touch vs swipe conflict" and "debounced note loss on swipe-archive" as items to mitigate. Verified in code before implementing: `initCardSwipe` line 2152 already filters by `event.target.closest('input,textarea,a,button,...')` and `debounceNote`'s setTimeout closure preserves the value across DOM removal. Both mitigations dropped from the work.
- **Swipe-affordance hint deferred.** The plan had a "show subtle '‹ swipe ›' chevron hint for first 3 sessions, localStorage-gated" item. Skipped at implementation time on the grounds that you'd discover swipe quickly enough. Revisit if needed — the localStorage-counter sketch is in the project notes if so.
- **Last-seen pill shipped, then removed.** The plan called for `lastSeenLabel` driving a `.v4-last-seen` chip ("seen 1d ago" with a green dot when fresh, amber when stale). Shipped that way, then pulled after Omar pointed out it was a noisy reassurance signal on every fresh card and duplicated the existing W3 `stalePillHtml`. W3 already shows only when actionable (>7d). The v4 pill, `lastSeenLabel` helper, and `.v4-last-seen` / `.v4-ls-dot` / `.v4-header-row` CSS all removed.
- **Seen toggle drifted from mockup, then was fixed.** v4 mockup had a bordered `[👁 Seen]` button. First implementation reverted to a bare icon. Caught by Omar; rebuilt as `.v4-seen-btn` (32px-tall bordered, blue tint when active). Table view stays icon-only.

### Bugs / polish surfaced by Omar's screenshot audits (not in the plan)
- **`##14C` in addresses.** Pre-existing bug in both card and table renderers — `' #' + listing.unit` doubled when `unit` was already `#14C`. Fixed with `String(listing.unit).replace(/^#+/, '')`.
- **Notes textarea cropped multi-line content.** 56px min-height was a hard ceiling; added `autoGrowTextarea` that sets height to `scrollHeight` on render and on `input`. Min-height still floors empty state.
- **Emoji eye looked unintentionally cute.** Swapped `👁` / `👁‍🗨` for a 16×16 outline SVG via `seenIconSvg()` helper. Single source consumed by both card and table.
- **OQ/RQ inputs accepted non-digits.** `type="number"` allows decimals, "e", "+", "-". Switched to `type="text" inputmode="numeric" pattern="[0-9]*"` plus an `oninput` strip. Mobile keypad shows digits only.
- **Mobile table view bled past viewport.** Not introduced by v4 — Session 28's `#scroll-content { overflow: visible }` mobile rule plus `body { overflow-x: hidden }` meant any wide content got clipped without scroll. Fix: `.table-wrap { max-width: 100vw; overflow-x: auto }` on mobile + `table { min-width: 900px }` so cells stay legible. View toggle stays visible on mobile by Omar's preference.

### Time
Estimated 3 hours, hard cap 5. Actual session covered the initial v4 markup/CSS plus all six commits in one continuous session. Roughly on-budget; the polish rounds were small.

### Closed
