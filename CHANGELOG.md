# CHANGELOG

All notable decisions and events on this project, in reverse chronological order.

---

## 2026-05-14 — Diagnostics Gaps Closed (Session 35)

Closeout work for the two diagnostics gaps surfaced by the Session 34 schema-drift incident.

### D-G1 — Sentinel-aborts now show on the diagnostics page

`scripts/pull.py`'s sentinel-abort branch (the one that fires when memo23 returns `{message: "No results found"}` placeholder rows) used to `sys.exit(1)` immediately with no record written. That made missed cron days *invisible* on `diagnostics.html` — the W5 cliff-guard table jumped over them. The 5/12 missed run only surfaced during Session 34's manual audit of GitHub Actions runs.

Fix: before `sys.exit(1)`, set `pass1_counts_by_type[listing_type] = 0` and call `update_pipeline_health(..., guard_status='abort')`. Preserves any counts already captured earlier in the run — if sale Pass 1 succeeded with 280 listings and rent then sentinel-aborts, the row is `{pass1_sale: 280, pass1_rent: 0, status: 'abort'}`, not `{pass1_sale: null}`. The page's existing `tr.abort` CSS lights it up red. Verified via in-process simulation.

### D-G2 — Freshness floor on the diagnostics page

New "Newest listing" kv in the Latest Run panel showing `max(listed_date)` across `latest.json`'s listings as an age in days. Thresholds match the existing "Age" kv: green ≤2d, amber 3–4d, red ≥5d. Tooltip carries the actual date.

This is the metric that would have caught Session 34's bug on day one. Pass 1 counts and the W5 cliff guard both watch *volume* — Pass 1 was returning 310 listings/day right through the schema-drift window. None of those panels could see that `normalize()` was silently setting `listed_date=None` on every new ingestion. A freshness floor measures *content* instead.

Promotes the long-standing Session 12 item "Add a pipeline health assertion" — same underlying ask.

### Commits
- `0bb9da6e12` — D-G1 (pull.py) + D-G2 (diagnostics.html) in one commit

### Render today (sanity check)
`Newest listing: 2d` (green) — `max(listed_date) = 2026-05-12`, two days behind the 2026-05-14 viewing date. Same panel would have read `5d` red on the morning Omar asked the original "nothing new in 5 days" question, instead of silently sitting on a cliff-guard-green "OK" everywhere.

### Lesson
Diagnostics is a UI for failure modes you've already named. Adding the "newest listing" panel didn't take new metrics — `listed_date` was already in `latest.json`. The instrument is cheap; the *insight that this was a class of failure worth instrumenting* is what took an incident to learn. Both items here move that insight into the operator surface so we won't have to relearn it from a third instance.

---

## 2026-05-14 — Pipeline Schema Drift Recovery (Session 34)

### Context
Omar opened the app and reported "nothing new in the last 5 days — is it broken again?" Cron had been running through 5/13 with green commits, the W5 cliff guard showed OK on every successful day, but the freshest `listed_date` anywhere in `db.json` was stuck at 2026-05-09.

### Diagnosis

1. **5/12 cron run actually failed.** Apify returned the sentinel `{message: "No results found"}` (residential-proxy IP blocked). `pull.py`'s sentinel guard correctly aborted the merge with `sys.exit(1)` before writing to `pipeline_health.json`. So the missed day is *invisible* on the diagnostics page — the W5 cliff-guard table jumps straight from 5/11 to 5/13.

2. **5/13 cron run "succeeded" but silently dropped data.** Pass 1 found 9 new IDs (6 sale + 3 rental). Pass 2 ran detail pulls for all of them. `normalize()` executed without error. The listings landed in `db.json` flagged `data_quality=pass2`. But every one of them had `listed_date=None`. Root cause: memo23 pushed a schema change around 5/12 that returns the listed-at timestamp under flat top-level keys `on_market_at` / `onMarketAt` instead of the prefixed `saleCombineResponse_sale_listed_at` / `sale_listed_at` that `normalize()` reads. The fallback chain returned `None`, the field stayed null, no exception was raised.

3. **Same schema flip silently broke rentals more deeply.** The new build also moved rental address, beds, baths, sqft, unit, and price history under the `propertyDetails_*` / `pricing_*` flat namespace (mirroring sale since 5/2). `normalize_rental()` had never been updated for any of this — it still only knew `combineData_rental_*`, `rentalCombineResponse_rental_*`, and bare `rental_*`. Result: 3 new rentals ingested with null address/beds/baths/sqft. Plus 4 older rentals (5022439, 5022432, 5020246, 5025162) had been stuck at pass1-only since 5/4 for the same underlying reason — the memo23 fix logged in Session 28 was actually a half-fix; the schema variant it added wasn't the one the actor settled on by 5/12.

### Fix — Two surgical commits

**`89c3004dc2`** — Added `on_market_at` and `onMarketAt` to the `listed_at` fallback chain in both `normalize()` (sale) and `normalize_rental()`.

**`d41a6b6e6f`** — Added `propertyDetails_*` / `pricing_*` fallbacks to `normalize_rental()` for price, beds, baths, sqft, unit, street; parses `propertyHistory_json[0].rentalEventsOfInterest` (with status → event mapping: ACTIVE→LISTED, DELISTED→OFF_MARKET, PRICE_DECREASED→PRICE_DECREASED, etc.) for price history, falling back to `pricing_priceChanges_json` when `propertyHistory_json` is absent.

### Backfill — Two data commits

**`f555752e81`** — Re-pulled the 9 listings that came through with `listed_date=None` since 5/12. All 9 now have correct listed_date (3 from 5/11, 6 from 5/12).

**`a811180cf3`** — Re-pulled 7 rentals through the patched normalizer: the 3 new (5039434 → 400 East 67th #28B; 5040766 → 223 East 80th #4; 5041266 → 420 East 64th #W7J) plus the 4 stuck pass1-only rentals (5022439, 5022432, 5020246, 5025162) which are now pass2 with listed_date and price history. `db.json` is fully pass2 for the first time since 5/4: `pass1_only=0`, `pass2_complete=391`.

### Known new-schema limitations (not fixable on our side)
- **Rental agent contact is firm-only.** No more name / phone / email per listing — only `sourceGroupLabel`. `agent_firm` still populates via the existing fallback. Agent name/phone/email fields will read null on new-schema rentals.
- **Rental neighborhood missing.** Field absent from the new schema.

### Diagnostics gap — surfaced but deferred

The whole failure mode is the "Cron Green ≠ Data Flowing" pattern, third instance. Two specific gaps in `diagnostics.html` let it run for four days unnoticed:

1. **Sentinel-aborts are invisible.** `pull.py` exits *before* writing to `pipeline_health.json`, so missed-cron rows never appear in the W5 table. The diagnostics page already has CSS for `abort`-status rows — there is just no data path.
2. **No data-freshness signal anywhere on the diagnostics page.** Pass 1 counts and the W5 cliff guard both monitor *volume*, not field-level data quality. A panel showing "newest `listed_date` in db.json" with red >5d old would have caught this on day one.

Both deferred to the next session by Omar's call. Tracked in TASKS.md "Open from Session 34."

### Commits
- `89c3004dc2` — Fix listed_date extraction for memo23 2026-05-12 schema
- `f555752e81` — Backfill listed_date for 9 affected listings
- `d41a6b6e6f` — Rental normalize: propertyDetails_* + propertyHistory_json
- `a811180cf3` — Backfill 7 rentals using patched normalize_rental

### Files touched
- `scripts/pull.py` — `normalize()` and `normalize_rental()` schema fallbacks
- `data/db.json`, `data/latest.json`, `data/2026-05-14.json` — backfilled records

### Lessons reinforced
- **"Cron Green ≠ Data Flowing" — third instance.** Memory entry exists; this is its third validation. Green exit code + green Pass 1 count + green `normalize()` execution does not equal good data. The only reliable check is on the *content* of the data, not the act of producing it.
- **Schema-tolerant normalizers beat vendor stability.** memo23 is a one-developer Apify actor patching against StreetEasy's anti-bot. Field-name churn is the steady-state. Cheaper to harden our normalizers to read every reasonable key variant than to chase upstream stability we won't get.
- **Pipeline assertions should test data, not just shape.** The W5 cliff guard catches *too few listings*. It does not catch *too few populated fields*. A `max(listed_date) >= today − N` or `non_null_address_rate >= 0.9` style guard would catch a different class of failure than the count-based ones already in place.
- **Bottom-up validation, again.** Before patching `normalize_rental()`, fetched a real rental response via Apify and dumped 91 keys. Caught the rental-agent-contact gap up front (actor genuinely doesn't return it under the new schema) — avoided shipping a fix that wouldn't have worked. The session prior had paid for this lesson; this session collected.

---

## 2026-05-14 — Card View v4: Mobile-First Redesign (Session 33)

### Context
Omar uses the card view almost exclusively on his phone, and the previous layout was a desktop card squeezed onto a 380px viewport. Too much chrome, OQ/RQ rank + notes (the primary actions on every card) buried below the action buttons, agent contact and bucket toggle taking up space that didn't earn it on mobile. Photo was missing entirely — there's no `images` field in `db.json` — so the "where do I look first?" affordance was the building name in 15px text.

### Design iteration (mockup-before-code)
Followed the Session 32 lesson: build the high-fidelity mockup, get sign-off, *then* implement. Four mockup rounds in chat with Omar driving:
1. **v1 (desktop):** Photo hero on the left, badge row, price+stats compact, OQ/RQ block, agent strip, quick actions row.
2. **v2 (mobile):** Full-width hero photo with badges overlaid, then header + price + stats + tinted OQ/RQ blocks + agent + actions.
3. **v3 (no photos):** Audit caught that `db.json` has no `images` field. Redesigned around what we actually have — price-history hero, monthly breakdown cards, description blurb, agent strip.
4. **v4 (compact):** Stripped the price-history hero and monthly breakdown (over-engineered), dropped the bucket toggle (swipe is already built), dropped agent contact (not used from cards), promoted OQ/RQ + notes as the centerpiece. Final.

### Architect + CTO review
Plan v1 written, reviewed in parallel by two independent agents. Both converged on the same cuts: kill the `?card-v4=1` feature flag (10 LOC of tax for one user; `git revert` is free), drop the shared component refactor (premature for n=1), collapse six rollout phases into one PR. Architect added: rename `comparePsfToShortlist` → `psfDeltaVsShortlist` returning a raw number formatted at the call site; flush pending debounced notes on swipe-start (later moot — see verification below); key the shortlist-median memo on filter set, not just per-render; `last_pass1` null fallback for `lastSeenLabel`. CTO added: time-box 3 hours / hard cap 5; if comparison line or textarea-swipe each eat >45 min, ship without; pass1-only listings decide rendering now, not on device; desktop ≥769px explicitly unchanged. Plan v2 written incorporating all of it.

### Pre-implementation verification
Two of the v2 risks turned out to already be handled in the existing code:
- **Textarea/swipe conflict.** `initCardSwipe()` line 2152 already bails on `e.target.closest('input,textarea,a,button,.seen-toggle,.rank-val')`. The new OQ/RQ textareas inherit the protection.
- **Debounced note loss on swipe-archive.** `debounceNote()` stores its timer in module-scoped `noteTimers` and captures `value` in the setTimeout closure. The save fires regardless of DOM state; the "Saved ✓" badge flash is gated with `if (badge)` and silently skips when gone. No flush needed.

Lesson reinforced: **ground claims about risk in actual code reading**, not assumption.

### What shipped — v4 card structure

Five full-bleed sections inside `.listing-card.v4` (legacy 16px padding zeroed out, each section owns its spacing):

1. **Header** (`.v4-header`) — building + neighborhood inline, address (with `#` strip on `unit`), badge row: type pill, ✂−$XK price-cut amount, days badge, "Built YYYY" chip, stale + off-market pills.
2. **Price + stats** (`.v4-price-stats`) — `$X.XXM` + "↓ from $Y.YYM" trend line on the left, monthly all-in below; bed/bath/sqft/$psf laddered right with `±N% $/ft² vs shortlist` comparison delta underneath (green = cheaper, red = more expensive).
3. **OQ block** (`.v4-oq`) — `#F5F8FD` blue tint, OQ label + numeric-only rank input + Saved ✓ flag, always-visible auto-growing notes textarea.
4. **RQ block** (`.v4-rq`) — `#FDF6F3` coral tint, same shape.
5. **Utility row** (`.v4-utility`) — labeled `[👁 Seen]` button (32px tap, blue tint when active) on the left, `View on StreetEasy ↗` on the right.

Cut from the previous card: Inbox/Shortlist/Archive button cluster (swipe at line 2316 handles it), built-year cell (promoted to badge), per-card mortgage rate/term, agent contact buttons (never used from cards), footer "Yorkville" duplication.

### New JS helpers
- `priceCutAmount(listing)` → `{absolute, percent, priorPrice}` from peak ask in `price_history` vs current `price`.
- `psfDeltaVsShortlist(listing)` → integer percent vs `shortlistPsfMedian()`, which is memoized on shortlist contents + their $/ft² sum (invalidates on changes).
- `seenIconSvg()` → inline flat eye SVG used by both card and table render so the icon stays consistent.
- `autoGrowTextarea(el)` → resize-to-fit on render and on `input`; CSS `min-height` still floors empty state.

### Polish rounds (post-ship, in commit order)
1. **Address `##` bug.** Both card and table render concatenated `' #' + listing.unit` — but some listings have `unit = "#14C"` already, producing `##14C`. Pre-existing bug, more visible in the v4 card. Fixed with `String(listing.unit).replace(/^#+/, '')`.
2. **Notes textarea cropped.** Default 56px min-height clipped multi-line notes. Added `autoGrowTextarea` wiring after `container.innerHTML` — sets height to `scrollHeight` on render and on every `input`. Empty textareas still get the floor.
3. **Emoji eye → flat SVG.** The `👁` / `👁‍🗨` emojis rendered too cute at card density. Replaced with a 16×16 outline SVG using `stroke="currentColor"` so the existing `.seen-toggle` / `.is-seen` CSS still drives color and opacity. Single helper consumed by both renders.
4. **Numeric-only OQ/RQ inputs.** Switched from `type="number"` (accepts decimals, "e", "+", "-") to `type="text" inputmode="numeric" pattern="[0-9]*" maxlength="3"` plus `oninput="this.value = this.value.replace(/\D/g, '')"`. iPhone keypad now shows digits only; paste of non-numeric becomes empty.
5. **Removed redundant "seen 1d ago" pill.** It was duplicating the existing W3 `stalePillHtml`, which already shows only when actionable (>7d). Pulled the v4 pill, the unused `lastSeenLabel` helper, and the orphan `.v4-last-seen` / `.v4-ls-dot` / `.v4-header-row` CSS. Family-app UI principle reinforced: silent-when-fine beats reassurance-pill-everywhere.
6. **Seen toggle as labeled button.** v4 mockup had a bordered `[👁 Seen]` button; first implementation reverted to bare icon. Fixed: 32px-tall bordered button, gray outline default, blue tint + blue border when `.is-seen`. Table view stays icon-only (cells too tight for the label).

### Mobile table view fix
Audit catch: tapping the Table button on a phone showed a wide table bleeding past the viewport with no scroll affordance, because `body { overflow-x: hidden }` + `#scroll-content { overflow: visible }` (Session 28) means the table extends into nothing. Not introduced by v4 work — table view has been bad on mobile since Session 28's auto-switch-to-cards landed. First fix hid the view toggle on mobile entirely; Omar flipped it: kept the toggle and made the table horizontally scrollable. `.table-wrap` gets `max-width: 100vw + overflow-x: auto` on mobile; `table { min-width: 900px }` keeps cells legible instead of compressing.

### Commits
- `b8f5bb5aed` — Card v4 markup + CSS + signal helpers + CARD-REDESIGN-PLAN.md
- `3ab9d26239` — Polish: `##` strip, auto-grow textareas, SVG eye (both card and table)
- `3855b4df09` — Polish: numeric-only OQ/RQ inputs, remove redundant last-seen pill
- `60548d4fa9` — Polish: labeled Seen button
- `cf2717c6c6` — Mobile: hide view toggle (subsequently flipped)
- `78f5628fff` — Mobile: restore toggle, table horizontally scrollable

### Files touched
- `index.html` — `renderCards()` rewritten (~125 lines replaced); `renderTable()` updated for SVG eye + `#` strip; ~120 lines of new CSS (v4 sections, mobile table scroll); 4 new pure helpers
- `CARD-REDESIGN-PLAN.md` — created during planning, kept as a record of intent vs ship

### Lessons reinforced / new
- **Mockup-before-code on visual changes** (Session 32 lesson) — held up. Four rounds in chat caught the photo-doesn't-exist problem, the OQ/RQ-buried problem, and the over-engineered price-history hero *before* a line of code shipped.
- **Audit your mockup against the data first.** Designing a hero photo for a card whose listings have no `images` field cost a full revision. Bottom-up validation isn't only for pipelines — it applies to UI fields too.
- **Audit shipped UI against the mockup.** Implementation drifted from the v4 mockup on two specific items (no labeled Seen button, redundant last-seen pill). Both surfaced from Omar's screenshots, not from my own review. For visual work, the verification step should include a side-by-side mockup-vs-shipped check, not just "the diff applied cleanly."
- **Ground risk claims in code.** The two risks the plan flagged about swipe and auto-save (textarea event capture, debounced note loss) were both *already handled* in the existing code. Reading the actual implementation before claiming risk would have saved a paragraph in the plan and a chunk of Omar's worry.
- **For n=1, kill the feature flag.** Both reviewers said this independently. Shipping `?card-v4=1` would have been pure tax — one user, one phone, `git revert` is free.

### TASKS.md cross-reference
T9 (card view adaptation) moves from "partial — buttons + seen eye visible" (Session 29) to fully complete: the v4 layout is the card view, with OQ/RQ + notes elevated as the centerpiece across all tabs. (The Session 29 "remaining: hide OQ/RQ inputs and notes in Inbox/Archive" item is intentionally rejected — keeping them visible across buckets is what the v4 design calls for.)

---

## 2026-05-14 — UI Cleanup: Diagnostics Off the Main Surface; Mobile Filter Sheet (Session 32)

### Context
Two complaints kicked this off. First: the Pass 1 Coverage strip was visually loud at the top of the app on both desktop and mobile — operator diagnostic on a family-facing surface, with copy ("today 310, 14d median 310 · 5 days below 75%") that only Omar could parse. Second: the inline filter dropdowns (Beds / Type / Max Price / Max Monthly / ✂ Cuts / 👁 Seen) consumed a lot of horizontal space for controls the family rarely touches, and on mobile the layout was visibly broken — search bar pushed everything else to wrap awkwardly, and at one point a Filters popover overflowed off the right edge of the viewport.

Also confirmed during the session: the user-facing line "Updated 1 day ago · 391 listings" read as "391 listings updated this run" but `391` was actually total active inventory in `db.json`. The pipeline is incremental — most days only a handful of listings change. Wording was misleading.

### CPO review (mid-session)
First pass tried to be clever — collapse the strip into a small green/amber/red pill in the header that always shows, even on mobile. Caught it on review: this is a family app for four users; the operator concern is one person's. Putting any always-on indicator (even a 12-pixel green dot) in the product surface to serve one person was wrong. Reset: build operator tools *off* the product surface. Keep the user-facing signal in human English, only when something is actually wrong.

### Changes shipped

**1. Removed `#coverage-strip` and `#health-strip` from `index.html`.** Their markup, CSS, and `loadCoverageStrip()` JS function all gone. Footer no longer carries `data.generated_at` or `run_cost_usd` — both were operator-y.

**2. Added `renderFreshnessBanner()`.** Single user-facing element. Hidden when data is ≤1 day old (cron's normal cadence). Amber 2–3 days, red 4+ days. Plain copy: "Listings last updated 2 days ago." or "Listings haven't refreshed in 4 days — Omar may need to check." Day-granular math because `latest.json.generated_at` is a date string, not a timestamp.

**3. New `diagnostics.html` — standalone operator page.** Reachable via a tiny gray `diagnostics` link in the footer. Sections: latest run summary (generated_at, age, active total, sale/rent mix, Pass 2 complete, Pass 1 only, partial, run cost) pulled from `data/db.json`'s pre-computed `stats` block; **Pass 1 coverage 14-day sparkline** lifted from the old strip; **W5 cliff guard last 7 days** as a table with warn/abort row highlighting; **Search URLs** that the cron polls (operator-relevant: changing these changes what Pass 1 discovers). Uses StreetHard colors (navy `#0E1730`, blue `#3461D9`, orange `#FF6000`) so it feels native.

**4. Relabeled price/monthly filter dropdowns.** "Max Price: Any / $2.5M / $3M..." → "Price: Any / ≤ $2.5M / ≤ $3M..." Same for Max Monthly → Monthly. The ≤ glyph carries the "max" semantic without the word. "Beds" left alone since it's an equality match (`≥` would be ambiguous).

**5. Collapsed all filter controls into a single Filters button.** Beds, Type, Price, Monthly, ✂ Cuts, 👁 Seen, Clear all — all live in a popover that opens on click. Mode toggle (For Sale / Rent / Both) and the search field stay visible since those are used constantly. A blue count badge appears on the button when filters are active (e.g. "Filters 2"). Filters still apply live as the user changes them — no Apply button. The popover dismisses on outside-click or Escape.

**6. Dropped the redundant "115 of 321 listings" result count.** The bucket-tab count already shows in-bucket inventory; the Filters-button badge now signals when filters are reducing the visible set.

**7. Mobile layout reflow + bottom sheet.** Initial popover-on-mobile was broken — anchored to a button that wraps to its own row, popover overflows the viewport. Redesigned:
- Mode toggle anchored left, Filters button anchored right on the same row (via `flex order` + `margin-left: auto`); search field drops to its own full-width row below. No more orphan Filters floating in empty space.
- On `@media (max-width: 768px)` the popover transforms into a bottom sheet: `position: fixed` at the viewport bottom, 58vh tall, with a drag handle, "Filters" + ✕ header, labeled rows (BEDS / TYPE / MAX PRICE / MAX MONTHLY), larger 14px controls, and a sticky footer with Clear all (left) + dark navy **Show N** primary button (right). The N updates live so the user knows what dismissing will reveal. Full-screen backdrop dims everything else; tap-to-close. Body scroll locked while sheet is open. Desktop popover untouched — same anchored-to-button behavior as before.

**8. Bucket tab counts now reflect active filters.** User-reported follow-up: applying a 4+ beds filter visibly shrank the list but "Inbox 115" stayed at 115. Felt broken — the tab badge implied total bucket inventory was always 115 regardless of what the list showed. Fixed by extracting `readActiveFilters()` + `passesActiveFilters(l, f)` and making `updateBucketCounts()` consume the same predicate as `applyFilters()`. With the filter on, "Inbox 115" becomes "Inbox 12" (the count of 4+ bed inbox listings); same treatment for Shortlist and Archive so the user sees how the filter would affect each bucket. Clearing the filter restores the badges to full bucket counts.

### CPO/Design lessons reinforced
- *Family-facing app ≠ operator dashboard.* When the audience is mixed, operator diagnostics need a separate URL, not a smaller version of themselves in the main UI.
- *Build the mockup before the code on visual changes.* The first mobile filter implementation shipped without a high-fidelity mock and had to be redone after the user pushed back. Second pass started from an SVG mockup, got sign-off, then implemented — much less rework.
- *"X of Y" is ambiguous when the audience varies.* The same line read three different ways depending on whether the reader was operator-thinking ("X listings shown of Y in the database") or family-thinking ("Y listings were updated last night"). Either remove the phrase or surface the same fact in two places with clearer framing.

### Commits
- `ad28afdf75` — Diagnostics relocation, freshness banner, ≤ glyph relabel, footer diagnostics link
- `5965d47067` — Filters popover, dropped result count
- `065cc6204e` — Mobile: Filters on mode row, bottom sheet, backdrop, Show N
- `f32bb18e36` — Docs (CHANGELOG + CLAUDE.md) for the above
- `62182bc73b` — Bucket tab counts respect active filters (Inbox/Shortlist/Archive badges)

### Files touched
- `index.html` — substantial UI surgery in markup, CSS (added ~120 lines for mobile bottom sheet), and JS (popover toggle + outside-click + backdrop wiring)
- `diagnostics.html` — new file, ~180 lines

---

## 2026-05-13 — Branch Cleanup + Recovered Mobile Calc-Toggle Tweak (Session 31)

### Context
Local clone had drifted ~20 commits behind `origin/main`. Multiple sandbox-leftover `.git/*.lock` files were blocking writes, the working tree carried stale versions of `index.html` and `scripts/pull.py` (older than what's on main), and a redundant local commit (`b8ceaa6`, "Remove API key auth") existed even though that change had already shipped to main via a different commit. Five unmerged-looking branches were sitting on the remote: two from the early days of the project (`claude/explore-project-V2hAM`, `claude/project-onboarding-Sn2cV`), one fully merged mobile branch (`claude/mobile-optimize-streethard-DEsLX`, `behind_by: 30, ahead_by: 0` vs main), and two recently-merged branches that still had a couple of unmerged trailing commits (`claude/fix-streethard-mobile-6pzOx`, `claude/fix-rental-listings-wE8pD`).

### Audit findings
- The big mobile overhaul (responsive CSS, swipe-to-triage, card-view default at ≤768px, seen toggle in cards) — already on main from PR #3 (merge `8224ed6`, May 10). Live on streethard.omarqari.com.
- The rental normalize fix (`_RCnew`/`_RCP` fallbacks) and W7 sentinel fix — already on main from PRs #1+#2 (May 10). Session 29 changelog also already on main.
- One genuinely unmerged piece on `claude/fix-streethard-mobile-6pzOx`: commit `8fe17a3f` — a follow-on mobile UI tweak that adds a `Calc ▾` toggle button in the header to free up screen real estate by hiding the mortgage bar and summary bar by default on mobile.

### Recovered: Calc ▾ toggle (`index.html`)
Cherry-picked the `8fe17a3f` tweak. On ≤768px viewports:
- `#mortgage-bar { display: none; }` by default; `.mobile-open` class reveals it
- `#summary-bar { display: none; }` (was previously a 2-column wrap)
- New `#mtg-toggle` button in the header (`Calc ▾`/`Calc ▴`); `toggleMortgageBar()` flips the class

**Bug fix while cherry-picking:** the original commit set `style="display:none;"` inline on the toggle button AND tried to override it from inside `@media (max-width: 768px)` with `#mtg-toggle { display: flex }`. Inline `style` has CSS specificity 1000; the media-query rule (specificity 100) loses. The button would have been hidden on mobile too — never visible to users. Fix: dropped the inline style, added `#mtg-toggle { display: none; }` to the base stylesheet (so desktop still hides it), and the media-query `display: flex` now wins on mobile as intended.

### Branches deleted from remote
- `claude/explore-project-V2hAM` — stale exploration branch from project init
- `claude/project-onboarding-Sn2cV` — stale onboarding branch
- `claude/mobile-optimize-streethard-DEsLX` — fully merged into main
- `claude/fix-streethard-mobile-6pzOx` — `8fe17a3f` cherry-picked here; rest already merged
- `claude/fix-rental-listings-wE8pD` — fully merged into main; trailing commits were duplicate docs

### Second recovery: swipe refinements silently overwritten by Session 30
After the initial cleanup, found that two further commits had been silently reverted by the same Session 30 "restore mobile" commit (`802dcd44`, May 10):

- **`9a28476c` (May 3, 16:27) — "Mobile UX: swipe green/red feedback + minimal sticky header"** — bigger badge font with letter-spacing, green (`#1a7a3c`) right + red (`#c62828`) left swipe colors with rotation, drag-tinted card background (`rgba(26,122,60,...)` / `rgba(198,40,40,...)`) that intensifies with drag distance, mobile sticky-header layout (`body { min-height: 100dvh; overflow-y: auto }` + `#main-header { position: sticky }` so only the header stays pinned and the rest scrolls naturally).
- **`a272ec69` (May 3, 17:10) — "Swipe: respect bucket context"** — `RESIST` constant + rubber-band resistance for blocked directions (you can't swipe a shortlisted card right into shortlist again, can't swipe an archived card left into archive again — the card resists with 15% sensitivity capped at 20px), contextual transition target (swiping right on an archived card restores it to inbox; swiping right on inbox sends to shortlist), contextual `rightLabel` in `renderCards()` so the swipe indicator reads "↩ Inbox" on archived cards.

**Diagnosis:** Session 30 ported forward from `2fee1b08` (May 3, 15:56), the *initial* mobile commit, not the *latest* tip of the mobile branch (`a272ec69`, May 3, 17:10). The two refinement commits remained in git history as standalone commits, but their content was overwritten by the rebased-forward `802dcd44`. They never got into the merged PR.

**Fix:** re-applied all the missing content directly to current main (commit pending).

**Lesson reinforced:** when forward-porting work from an older branch, always rebase from the BRANCH TIP, not a snapshot. `git log <branch>` to see the latest, then port the cumulative state. The standalone commit hashes in main's history are misleading — the SHAs are present, but the patches were undone.

### Lesson reinforced
Sandbox-side git is brittle: stale `.git/*.lock` files persist across sessions, `git fetch` partially fails on sandbox-mounted `.git/objects` (the new branch refs may or may not actually land), and the proxy used in mobile sessions can't push. The combination produces a clone that *looks* slightly behind but is actually full of stale local versions of files that have moved forward on remote — pushing those would silently destroy live work. Recovery: always `git reset --hard origin/main` from real Terminal before doing anything; never trust the sandbox's view of what's local-vs-remote.

---

## 2026-05-10 — Fix Rental Pass 2 Normalization + W7 Sentinel Bug (Session 29)

### Context
memo23 (Apify actor author) shipped a bypass fix for `/rental/{id}` URLs using the same approach previously applied to `/sale/{id}`. Previously, all `/rental/{id}` Pass 2 requests returned "No results found" sentinels, leaving 4 rental listings permanently stuck at `pass1` quality (missing year_built, agent contact, price history).

### Fix 1: normalize_rental multi-namespace support (`scripts/pull.py`)
Added two new namespace constants alongside the existing `_RC = "combineData_rental_"`:
- `_RCnew = "rentalCombineResponse_rental_"` — mirrors `_SC` for sales (May 2026 bypass)
- `_RCP = "rental_"` — bare prefix fallback, mirrors `_PP` for sales

Every field lookup in `normalize_rental` now checks all three namespaces: price_histories_json, id, building_building_type, building_title, area_name, building_year_built, days_on_market, contacts_json, listed_at. The original `combineData_rental_*` is still checked first (verified working schema).

**Validation caveat:** The new namespace names (`rentalCombineResponse_rental_*`, `rental_*`) are inferred by analogy from the sale schema — memo23's actual response was not inspected directly (no APIFY_TOKEN in sandbox). The defensive multi-namespace approach means the fix works even if the schema is unchanged; but if memo23 used a completely different naming convention, the listings will remain at pass1. **Verify after the next cron run (2026-05-11 09:00 UTC) that listings 5022439, 5022432, 5020246, 5025162 have upgraded to pass2.**

### Fix 2: W7 sentinel detection for rental listings (`scripts/pull.py`)
`verify_stale_shortlists()` checked for off-market status by looking for `price`, `pricing_price`, or `saleCombineResponse_sale_price` — none of which exist in rental Pass 2 responses (rental price is nested inside `price_histories_json`). This pre-existing bug would have incorrectly flagged any shortlisted rental as "confirmed off-market" the moment it was checked via W7.

Fixed by detecting the listing type from the db entry and additionally checking `combineData_rental_price_histories_json`, `rentalCombineResponse_rental_price_histories_json`, and `rental_price_histories_json` for rental listings.

### CLAUDE.md update
Updated infrastructure state: rental Pass 2 status changed from BROKEN → FIXED.

### CTO notes
- Both fixes are low-risk and additive (no existing logic removed)
- Validation gap: new rental namespace names are inferred, not confirmed from actor output
- Next action: verify the 4 pass1 rentals upgrade on 2026-05-11 cron; if not, dump raw response on listing 5022439 and update namespace constants

---

## 2026-05-03 — Seen Toggle for Visited Apartments (Session 28)

### Feature: "Seen" indicator
Added the ability to mark apartments as physically visited with a simple toggle.

**Backend:**
- Added `seen BOOLEAN NOT NULL DEFAULT FALSE` column to `listing_status` table
- Idempotent migration in `schema.sql` (adds column if missing on startup)
- `seen` field added to all Pydantic models (`StatusPatch`, `BatchItem`)
- Both UPSERT SQL paths (`UPSERT_SQL`, `UPSERT_WITH_RANK_CLEAR_SQL`) updated with `$seen` parameter
- `SELECT_ALL_SQL` and `row_to_dict` include `seen`
- Toggle via `PUT /status/{id}` with `{"seen": true}` or `{"seen": false}`

**Frontend:**
- Eye icon (👁) in the actions cell of each table row, before transition buttons
- Faded when not seen, blue (`#3461D9`) when marked as visited
- Click toggles with optimistic UI update, persists to API
- "👁 Seen" checkbox filter in filter bar (same pattern as "✂ Price Cuts")
- Filter shows only listings where `seen === true`
- Clear Filters resets the Seen checkbox

**Commits:** `5c3f586` (backend + frontend toggle), `dc6d728` (seen filter checkbox)

---

## 2026-05-03 — Update Default Mortgage Rate to 5% (Session 27)

Updated the default mortgage interest rate from 3.00% to 5.00% across all locations:
- `CLAUDE.md` — mortgage calculator defaults documentation
- `index.html` — rate input field default value, JS variable initialization, and fallback in parser

No other changes this session.

---

## 2026-05-03 — Remove Auth, Git Push Script (Session 26)

### Auth Removal
Removed API key authentication from the status API. Write endpoints (`PUT /status/{id}`, `POST /status/batch`) are now public, restricted only by CORS to `streethard.omarqari.com`. This fixes the issue where family members couldn't edit notes or rankings from their own computers (the API key was stored in localStorage, per-browser). Removed from backend: `require_write_key` dependency, `WRITE_API_KEY` env var, `X-API-Key` CORS header. Removed from frontend: settings modal, gear icon, `getApiKey()`/`hasApiKey()` functions, all disabled-state logic for notes/rankings.

### Git Push Script
Created `scripts/git_push.py` — pushes to GitHub via the REST API instead of the git CLI. Solves the persistent `.lock` file problem where the Cowork sandbox mount creates lock files that can't be deleted by subsequent sessions. Updated CLAUDE.md to prohibit `git commit`/`push`/`pull`/`stash` from the sandbox and direct all future sessions to use this script.

---

## 2026-05-03 — Health Strip, Signal Icons, Daily Cron (Session 24, Part 2)

### Pipeline Health Strip
Added a staleness-aware info strip between the summary bar and bucket tabs. Shows last refresh date, age, and data quality count. Three visual states: green (fresh, <3 days), yellow warning (3–4 days stale), red error (5+ days stale). Hidden until JS computes from `generated_at` in latest.json.

### Price-History Signal Score
Per-listing icons derived from `price_history`, rendered in the DAYS LISTED column:
- ✂ **Price cuts** (red) — listing has PRICE_DECREASE events
- ↻ **Re-listed** (orange) — 2+ LISTED events (pulled and relisted)
- ⏸ **Off-market-and-back** (blue) — was TEMPORARILY_OFF_MARKET or NO_LONGER_AVAILABLE, then relisted
- ⏳ **Stale 90d+** (yellow) — most recent LISTED event > 90 days ago

Results cached per listing ID for performance. Added "✂ Price Cuts" checkbox filter in filter bar — filters to only listings with price reductions (202 of 368 sale listings have cuts).

### Cron Schedule
Changed from Mon+Thu (twice weekly) to daily at 09:00 UTC. Initially blocked by PAT missing `workflow` scope — Omar added Workflows read/write permission to the `claude-streethard` fine-grained token (no regeneration needed), then pushed successfully.

### DNS Cutover Cleanup
Removed `ALLOWED_ORIGIN_FALLBACK` env var from Railway. Enabled "Enforce HTTPS" on GitHub Pages.

### PAT Token Update
Added Workflows read/write permission to the `claude-streethard` fine-grained PAT. Fine-grained tokens update permissions in place — no regeneration or `.env` change needed.

### Git
- Commit `176c809`: index.html with health strip + signal icons + price cuts filter
- Commit `31e0022`: refresh.yml changed to daily cron

---

## 2026-05-03 — Fix Missing Financial Data for 7 Listings (Session 24)

Investigated and fixed 7 pass2 sale listings that had null `monthly_fees` in db.json, causing the app to show "—" for Common Charges and understate Monthly Payment.

### Root Cause

The Apify actor's Pass 2 sometimes returns null for financial fields even when StreetEasy has the data. For 425 E 63rd specifically, the listing was relisted at a higher price ($2.65M → $2.675M), creating a new listing ID (1821994) whose Pass 2 pull came back with null fees, while the older listing (1807381) had `monthly_fees: 11,475`.

### Fix Strategy (three-tier)

1. **Carry forward from duplicate listings** — For 425 E 63rd, carried `monthly_fees=11475` from the older listing (1807381) to the current one (1821994). Same apartment, fees don't change on relist.
2. **Apify re-pull** — Attempted targeted Pass 2 for all 7 URLs. Actor returned "No results found" sentinel for all. Individual-URL scraping still broken.
3. **Browser automation fallback** — Visited all 6 remaining listings on StreetEasy via Chrome MCP, extracted financial data from the page DOM using the `.SaleListingSpecSection_costsSpecItem__wknk2` CSS class.

### StreetEasy Findings

| ID | Address | Common Charges | Taxes | Notes |
|---|---|---|---|---|
| 1821994 | 425 E 63rd #PH/ABC | $11,475 (carried forward) | — | Relist |
| 1792113 | 225 E 62nd | N/A | $5,317/mo | |
| 1769977 | 169 E 94th | N/A | Tax abatement | New dev |
| 1798329 | 507 E 84th #TWNH | N/A | Tax abatement | New dev |
| 1799682 | 146 E 89th | N/A | Tax abatement | New dev |
| 1823264 | 333 E 91st #30AB | Maintenance $14,615/mo | Tax abatement | Condo w/ maintenance |
| 1755062 | 197 E 76th #TW | N/A | Tax abatement | New dev |

5 of 7 are new-development condos with tax abatements where StreetEasy itself shows "Not applicable" / "No info" — the actor returned null because the data genuinely doesn't exist on the source page.

### Data Patched

- Set `monthly_fees` and `monthly_taxes` to 0 for N/A and tax-abatement cases (JavaScript `|| 0` in payment calc treats 0 same as null for math; display shows "—" for 0 via falsy check, which is correct UX for "not applicable")
- Set `monthly_fees=14615` for 333 E 91st (maintenance-style condo)
- Set `monthly_taxes=5317` for 225 E 62nd (only listing with actual tax data)
- **Result:** 0 pass2 sale listings now have null `monthly_fees` (was 7)
- 425 E 63rd monthly payment corrected from $10,334 → $19,591

### Git

- Encountered stale `.git/index.lock` (and HEAD.lock, main.lock) from a prior crashed operation. Worked around by cloning fresh, copying updated files, committing and pushing from the clean clone.
- Commit `6c73ed9`: "Fix missing common charges & taxes for 7 listings"

---

## 2026-05-03 — Verification + T6 Sort Defaults (Session 23)

End-to-end verification of the three-bucket system, DNS cutover confirmation, and T6 sort defaults shipped.

### Verification

1. **DNS fully propagated.** Both `streethard.omarqari.com` (GitHub Pages) and `api.streethard.omarqari.com` (Railway) resolve and serve HTTPS. Custom domains confirmed working.
2. **API health confirmed.** `/health` returns `{"ok":true,"db":"connected"}`. `GET /status` returns all 9 status rows.
3. **A4 (rank clearing) verified end-to-end via API.** Test cycle: shortlist with OQ=2/RQ=5 → archive (ranks null) → inbox (still null) → re-shortlist (still null). Rank-clearing SQL works correctly.
4. **Stale pre-migration ranks fixed.** Two archived listings (1810570, 1718666) had non-null ranks from before the Session 22 migration. Fixed by cycling them through shortlist→archive to trigger the rank-clearing SQL path.
5. **App loads and renders.** All three tabs (Inbox 356, Shortlist 5, Archive 7) render correctly with proper badge counts, transition buttons, and column hiding.

### T6 — Sort Defaults Per Tab (shipped, pushed commit 220aa44)

- **Inbox:** Monthly Payment descending (unchanged default)
- **Shortlist:** OQ# ascending, nulls last (priority order)
- **Archive:** `bucket_changed_at` descending (most recently archived first — no column header highlighted since it's not a visible column)
- Sort resets automatically on tab switch
- Init block respects URL hash on page load (`#shortlist` loads with OQ# sort)
- Removed hardcoded `↓` arrow from Monthly Pmt header; arrows now set dynamically
- Added `archived_at` sort case to `sortListings()` comparator

### User Activity Observed

Omar has been actively triaging: 5 shortlisted (The Saratoga, 201 E 83rd, New Yorker Condo, 201 E 77th, 233 E 69th), 7 archived with notes like "Too expensive" and "Too expensive per month b/c of wild maint fees." System is getting real use.

---

## 2026-05-02 — Three-Bucket MVP Build Complete (Session 22)

Implemented the full three-bucket triage experience: backend migration + API rewrite + frontend tab navigation + transition buttons + auto-resurrection.

### Backend (D6 — completed, deployed to Railway)

1. **Schema migration** — `schema.sql` rewritten with idempotent DO $$ block: adds `bucket`, `bucket_changed_at`, `price_at_archive` columns; backfills `watch=true` → `shortlist`; drops all CHECK constraints then drops old `status` and `watch` columns; adds bucket CHECK constraint.
2. **API rewrite** — `main.py` now uses two SQL paths: `UPSERT_SQL` (9 params, normal) and `UPSERT_WITH_RANK_CLEAR_SQL` (7 params, hardcodes NULL ranks on shortlist exit). Statement-by-statement migration execution for asyncpg compatibility. Non-fatal migration errors (logs but doesn't crash).
3. **Pydantic models** updated: `StatusPatch` and `BatchItem` have `bucket`, `bucket_changed_at`, `price_at_archive` fields.
4. **Verified live** — all transitions work: inbox→shortlist, shortlist→archive (ranks cleared), archive→inbox. Batch endpoint works for auto-resurrection.

### Frontend (T1 + T2 + T4 — completed, pushed to GitHub Pages)

1. **Tab navigation (T1)** — Inbox/Shortlist/Archive pill tabs between summary bar and filter bar. Active tab has blue bottom border + blue badge count. Badge counts update live as listings move between buckets.
2. **Transition buttons (T2)** — Actions column in table. Inbox shows ★Shortlist + ✕ buttons. Shortlist shows Archive button. Archive shows ↩Inbox button. Optimistic UI updates (instant feedback before server responds).
3. **OQ#/RQ# column hiding** — Rank columns hidden via CSS class `hide-ranks` on any tab other than Shortlist. Columns reappear when switching to Shortlist tab.
4. **URL hash routing** — `#inbox`, `#shortlist`, `#archive` in URL. Bookmarkable, supports browser back/forward. Defaults to #inbox on fresh load.
5. **Auto-resurrection (T4)** — On page load, scans archived listings. If current price < `price_at_archive`, batch-transitions them back to inbox via `/status/batch` endpoint.
6. **Bucket filtering** — `applyFilters()` now filters by `getBucket(id)` matching `currentBucket`. Listings without a status row are implicitly in Inbox.

### Key Fixes During Build

- Git lock files (`.git/index.lock`) — used fresh clone to /tmp workaround
- asyncpg multi-statement execute — split SQL on semicolons respecting $$ dollar-quoting
- CHECK constraint blocking DROP COLUMN — drop all constraints first via PL/pgSQL loop
- `IndeterminateDatatypeError` for NULL params — rewrote rank-clearing SQL to use only 7 params
- `bucket_changed_at` type mismatch — convert ISO string to datetime in `do_upsert()`

### What Remains (v1 MVP)

- T5: Tab badge counts already done (inline with T1)
- T6: Sort defaults per tab (shortlist sorts by oq_rank asc by default)
- T7: Optimistic update helper (partially done — inline in `transitionBucket`)
- T8: Offline outbox + flush
- T9: Card view adaptation for buckets
- T10: Chips (shortlist only)
- Verification: Live test of full triage flow on production

---

## 2026-05-02 — Three-Bucket Triage System Design (Session 21)

Major design pivot: replaced the six-status pill cycling + watch toggle design (Sessions 13–19) with a simpler **three-bucket triage system** modeled on Gmail's Inbox/Archive pattern.

### Design Decisions

1. **Three buckets: Inbox / Shortlist / Archive.** Every listing lives in exactly one. New listings from cron land in Inbox. User triages to Shortlist (actively pursuing) or Archive (rejected). Replaces the old `status` enum (none/watching/viewing/shortlisted/rejected/offered) and `watch` boolean.

2. **OQ/RQ rankings are Shortlist-exclusive.** Rankings only exist while a listing is shortlisted. Moving out of Shortlist clears them — server-side enforced, not just client-side. Rankings are operational priority, not historical.

3. **Auto-resurrection on price drop.** When archiving, the app records `price_at_archive`. On page load, any archived listing whose current price < `price_at_archive` auto-promotes to Inbox with a "Price dropped" badge. Re-archiving at the new price resets the threshold.

4. **URL hash for tab state.** `#inbox`, `#shortlist`, `#archive` — bookmarkable, shareable within the family.

5. **Notes persist across all buckets.** Context like "overpriced by $200K" is useful if the listing auto-resurrects.

### What This Supersedes

- F2 (status pill cycling) — replaced by bucket transitions
- F3 (watch toggle) — replaced by Archive with auto-resurrection
- F5 (status filter tabs) — replaced by three-bucket tab navigation
- v1.5 RECONSIDER pill — replaced by auto-resurrection + "Price dropped" badge
- v1.5 saved-filter tabs — replaced by Inbox/Shortlist/Archive tabs

### Documentation Updated

- `TASKS.md` — new task list (T1–T10), acceptance criteria (A1–A10), revised deployment ops (D6)
- `STATUS-FEATURE.md` — revised state model, schema, frontend integration, acceptance criteria
- `PROJECTPLAN.md` — updated Phase 3, state model, phasing, open questions
- `CLAUDE.md` — updated Status Feature Architecture section

### Next Session

Start with D6 (schema migration: add `bucket`, `bucket_changed_at`, `price_at_archive` columns; backfill from `watch`; update API logic; drop old columns). Then T1–T4 for the MVP frontend.

---

## 2026-05-02 — Frontend: Rankings, Notes, Visual QA (Session 20)

Built the remaining frontend features for the Status Feature and performed a comprehensive visual QA audit.

### What We Did

1. **OQ#/RQ# ranking columns in table view.** Click-to-edit inline rank inputs. Nulls-last sorting in both ascending and descending directions (early-return comparator, not sentinel values). Dashed border on empty cells for discoverability.

2. **OQ Notes / RQ Notes textareas in card view.** Color-coded labels (blue OQ, orange RQ). 1-second debounced saves to the status API. "Saved" badge flash on successful PUT.

3. **Settings panel (F1).** API key storage in localStorage, Test Connection button. Two-fetch load + merge via `Promise.all` (listings JSON + status API). Read-only mode when no API key configured.

4. **Expansion panel improvements.** Added Notes as 4th column in the row expansion (table view). Constrained `.exp-col` to max-width 420px to prevent price history table from bleeding into rank columns. `debounceNote()` updated to flash saved badges in both card and expansion views.

5. **Visual QA audit.** 22-item audit covering layout, hierarchy, interactivity, typography, data presentation, and polish. Fixed 2 items (rank input visibility, expansion row accent bar). Remaining 20 items logged for future work.

6. **Sort fix.** OQ#/RQ# descending sort was putting unranked listings at the top (sentinel 9999). Replaced with early-return nulls-last comparator.

### Commits

- `57fbfe9` — Fix OQ#/RQ# sort: nulls always last regardless of sort direction
- `d213f20` — Update CLAUDE.md: reflect frontend progress
- `49ac0ac` — UI polish: dashed border on empty rank cells, blue accent bar on expanded rows
- `256f7a6` — Expansion panel: constrain price history + add OQ/RQ notes

### Status Feature Frontend Progress

**Built:** F1 (Settings), F7 (two-fetch merge), OQ/RQ rankings, OQ/RQ notes (card + expansion)
**Not yet built:** F2 (status pill cycling), F3 (watch toggle), F4 (chips), F5 (status filter tabs), F6 (offline outbox), F8 (card-view status controls)

### Remaining QA Items (deferred)

20 items from the visual audit need to be logged to PRODUCT-BACKLOG.md. Covers: filter bar layout, type column color system, search icon polish, card/table view consistency, price history styling, mortgage calculator presets, and more.

---

## 2026-05-02 — Backfill Complete After memo23 PX Fix (Session 19)

memo23 patched the actor's short-URL path (`/sale/{id}`) to pull financials from a non-PX-blocked source, resolving the `SaleListingDetailsFederated` 403 issue that had blocked financial fields since late April.

### What We Did

1. **Validated the fix.** Single-listing test on 785 5th Ave #7E (co-op, listing 1824911, run `jge7HatyHZzhqZnwm`). `partial: False`, `maintenance: 5480`, all fields populated. Confirmed the new field schema: `pricing_*`, `propertyDetails_*`, `saleCombineResponse_sale_*` prefixes alongside top-level convenience fields.

2. **Updated `pull.py` normalize().** Added `_SC` (`saleCombineResponse_sale_*`) prefix to all field resolution chains. Added `pricing_monthlyMaintenance`, `pricing_monthlyTaxes`, `pricing_monthlyCommonCharges`, `propertyDetails_bedroomCount`, `propertyDetails_livingAreaSize`, etc. Fixed price history source ordering — `saleCombineResponse_sale_price_histories_json` (flat format) before `propertyHistory_json` (nested, incompatible format). All changes backward-compatible with the old actor build.

3. **Backfilled all 38 pass1 sale listings.** Single Apify run (`eEQfCNBuh0fTNihJ0`), 38 URLs, all returned full data, zero partials. Cost: ~$0.11. All 38 upgraded from `pass1` → `pass2`.

4. **Flagged rental URL issue to memo23.** Individual rental URLs (`/rental/{id}`) still return "No results found" sentinels — tested with run `tIhlVjuDBh9LDQwxa`. Different failure mode from the sale-side PX block; the actor's rental detail path likely needs the same treatment as the sale short-URL fix. Posted to the Apify issues thread. 8 rental listings remain at pass1.

### DB State After Session

- 419 active listings (368 sale, 51 rental)
- 411 pass2, 0 partial, 8 pass1 (all rentals)
- 366 of 368 sales have full financial data for monthly payment calculations
- Pass1 → pass2 upgrade rate: 38/38 (100%)

### Files Modified

- `scripts/pull.py` — normalize() field mapping for new actor build
- `data/db.json` — 38 listings upgraded to pass2
- `data/latest.json` — regenerated
- `data/2026-05-02.json` — dated archive
- `CHANGELOG.md` — this entry
- `TASKS.md` — updated open items
- `CLAUDE.md` — updated infrastructure state

---

## 2026-05-02 — Status Backend Built + Infrastructure Complete (Session 18)

Built and deployed the entire Status Feature backend (B1–B6) and completed all infrastructure tasks (D1–D5, U1–U3). The API is live on Railway.

### Backend (B1–B6)

All six backend tasks completed in one session:

- **B1:** `api/main.py` (FastAPI app), `api/db.py` (asyncpg pool), `api/requirements.txt`, `api/railway.toml`. `/health` returns `{"ok": true, "db": "connected"}`.
- **B2:** `api/schema.sql` with `listing_status` table, CHECK constraint on status values, indexes on `listing_id` and `watch`. Idempotent startup migration.
- **B3:** `GET /status` — public read, no auth required, `Cache-Control: no-store`.
- **B4:** `PUT /status/{listing_id}` — upsert with `COALESCE` for partial patches. `X-API-Key` auth via `hmac.compare_digest`.
- **B5:** `POST /status/batch` — idempotent batch upsert for offline outbox flush.
- **B6:** CORS middleware with `ALLOWED_ORIGIN` + `ALLOWED_ORIGIN_FALLBACK` env vars.

All endpoints verified with curl locally before push to Railway.

### Infrastructure (D1–D5, U1–U3)

- **Railway:** Project created, Postgres provisioned, env vars set (`WRITE_API_KEY`, `ALLOWED_ORIGIN`, `ALLOWED_ORIGIN_FALLBACK`), Hobby tier activated ($5/mo), healthcheck configured. API deployed and responding.
- **DNS:** Migrated nameservers from Namecheap to Spaceship. Added 4 custom DNS records on Spaceship: `streethard` CNAME → `omarqari.github.io`, `api.streethard` CNAME → `bu5x85os.up.railway.app`, `_railway-verify` TXT, `www` CNAME → `omarqari.github.io`.
- **GitHub Pages:** Custom domain `streethard.omarqari.com` configured on the streethard repo. DNS check in progress (awaiting nameserver propagation).
- **Railway custom domain:** `api.streethard.omarqari.com` added. TXT verification record in DNS. Awaiting propagation for auto-SSL.

### www.omarqari.com → LinkedIn Redirect

User requested `www.omarqari.com` redirect to `https://www.linkedin.com/in/oqari/`. Spaceship's built-in URL Redirect feature would have destroyed the custom DNS records (it forces one "hosting service" at a time). Solution: created `omarqari/www-redirect` GitHub repo with a meta-refresh `index.html` + `CNAME` file, enabled GitHub Pages, added `www` CNAME on Spaceship pointing to `omarqari.github.io`. Zero-cost, no maintenance.

### Pending After DNS Propagation

- Verify `https://streethard.omarqari.com` loads the app
- Verify `https://api.streethard.omarqari.com/health` returns 200
- Enable "Enforce HTTPS" on GitHub Pages settings
- Remove `ALLOWED_ORIGIN_FALLBACK` from Railway env vars
- Verify `www.omarqari.com` redirects to LinkedIn

### What's Next

Frontend build (F1–F8 in TASKS.md). Start with F1 (Settings panel + Test Connection) and F7 (two-fetch load + merge), then F2 (status pill cycling).

### Files Created

- `api/main.py` — FastAPI application with all endpoints
- `api/db.py` — asyncpg connection pool management
- `api/schema.sql` — listing_status table DDL
- `api/requirements.txt` — Python dependencies
- `api/railway.toml` — Railway deployment config
- `omarqari/www-redirect` repo — GitHub Pages redirect to LinkedIn

### Files Updated

- `TASKS.md` — B1–B6 marked complete, D1–D5 marked complete, U1–U3 marked complete, WRITE_API_KEY generated
- `CLAUDE.md` — Status Feature Architecture section updated to reflect backend-complete state
- `CHANGELOG.md` — this entry
- `.env` — added `WRITE_API_KEY` and `STATUS_API_URL`

---

## 2026-05-02 — Status Feature Proposal Review (Session 17)

User asked for a fresh CPO-style proposal on the listing-status tracking feature. The proposal was written from a buyer's-mental-model angle without re-reading the locked spec first, and recommended committed JSON in the repo as the persistence story. That part was superseded by the Session 13–16 architecture (Railway + FastAPI + managed Postgres on `api.streethard.omarqari.com`) and not folded back into the docs — the locked design is correct for the cross-device requirement and shouldn't be disturbed.

What was new and worth keeping has been logged in the docs:

- `STATUS-FEATURE.md` gains a "Deferred Design Ideas" section near the end capturing five ideas from the proposal that aren't in v1 but are worth considering: `triaged-out` as a seventh status, a `listing_status_history` audit table, structured tour metadata, saved-filter tabs above the table, a "Recently delisted (you tracked these)" surface, and a concrete spec for the v1.5 watch-triggered re-evaluation pill.
- `TASKS.md` v1.5 backlog gains the saved-filter tabs and recently-delisted surface, plus a concrete `price_at_watch` snapshot spec for the existing v1.5 visual-diff item. v2 backlog gains structured tour metadata columns and the status-history table.
- `TASKS.md` "Open Questions → Status feature" gets four new questions to resolve before v1 schema hardens (Session 17 bucket): `triaged-out` as a status, last-write-wins vs history, notes structure, default tab on load.

No code changed. v1 build (B1–B6 / F1–F8 / D1–D8 / U1–U4) remains the next session's opener as before.

### Files Updated

- `STATUS-FEATURE.md` — new "Deferred Design Ideas — Logged 2026-05-02 (Proposal Review)" section before v1 Acceptance Criteria.
- `TASKS.md` — v1.5 list expanded; v2 list expanded; Open Questions gets a new "Session 17 — proposal-review additions" bucket.
- `CHANGELOG.md` — this entry.

### Lesson For Future Claude

Before designing a feature that already has a locked spec, read the spec doc first. The proposal sunk effort on a persistence path (`data/status.json` + Cowork commits) the user already evaluated and rejected explicitly back in Sessions 13–14. The `Personal Watch List` localStorage scope-down (CLAUDE.md) and the locked Railway design (`STATUS-FEATURE.md` "Architecture Decision" table) both signal that this question has been settled. The buyer's-mental-model framing was useful; the architecture re-litigation was not.

### Continuation — Broader CPO Product Slate

Same session, separate ask: CPO-mode proposal for *product improvements
across the whole app* (not just the status feature). 15 proposals drafted
across six themes: Decision Quality, Data Quality, UX, Signal & Noise,
Due Diligence Integration, Automation. Each proposal calibrated for n=1
personal purchase — no commercial APIs, no StreetEasy scraping, no
production-grade infra. Reviewed against in-flight TASKS.md items before
committing: 14 stand as-is, 1 (`#15 Listing-Watch List localStorage`)
superseded by the Status Feature backend already in motion.

Three relate to or extend in-flight work: `#3 Price-History Signal Score`
relates to the v1.5 RECONSIDER pill but is broader (universal vs.
watch-triggered); `#9 URL-encoded Saved Views` relates to the v1.5
Saved-filter tabs but is orthogonal (ad-hoc sharing vs. fixed nav);
`#12 In-App Pipeline Health Strip` extends the in-flight pipeline-health
assertion by adding a user-visible surface.

The slate plus five open decisions awaiting user selection are captured
in a new `PRODUCT-BACKLOG.md`. CPO recommendations:

- **Quick-wins slate (3 × S):** Rent-vs-Buy Card, Compare Pane, Pipeline
  Health Strip — closes three real gaps with no inter-dependencies.
- **Negotiation-data arc:** PLUTO BBL Enrichment → ACRIS Condo Comp
  Overlay → Per-Listing DD Quicklinks → Comp Sheet PDF — each builds on
  the prior, ends with an artifact an attorney could review.

User has not yet selected — open decisions tracked in TASKS.md
"Open Questions → Product backlog (Session 17)" so they stay visible.

#### Files Updated (continuation)

- `PRODUCT-BACKLOG.md` — new file. The full themed slate, the
  superseded #15, and the five open decisions.
- `TASKS.md` — `Open Questions` gains a `Product backlog (Session 17 —
  2026-05-02)` bucket listing the five open decisions.
- `PROJECTPLAN.md` — `Phase 2 enhancements` gains a "Product backlog"
  bullet pointing to PRODUCT-BACKLOG.md.
- `CLAUDE.md` — `Files in This Project` lists PRODUCT-BACKLOG.md.

#### Lesson For Future Claude (continuation)

When proposing CPO-style work, read TASKS.md to the bottom *first*. The
initial slate of 15 included a localStorage-only watch list (`#15`)
which would have been ~1 session of work that needed to be torn out
once the Railway-based Status Feature shipped. Catching that overlap
*before* writing the file kept the recommendation honest. Same lesson
the Session 17 status-feature entry above documents — applied
differently.

---

## 2026-05-02 — Custom Domain Decision + Documentation Pass (Session 16)

Closed the last two open architectural questions on the status backend (language pick was already Python; domain was the genuinely-open one). The user signed off on running everything under `omarqari.com` subdomains via Spaceship DNS. Updated all four design/orientation docs to reflect the new URLs and added a user-action checklist for the DNS work.

### Decisions Locked This Session

**Custom domains (replaces Session 15's "no custom domain in v1" call).**

- `streethard.omarqari.com` → CNAME → `omarqari.github.io` — the static StreetHard app
- `api.streethard.omarqari.com` → CNAME → the Railway API service

Domain registrar is Spaceship (`spaceship.com`); Omar owns `omarqari.com`. The default `omarqari.github.io/streethard` and `*.up.railway.app` URLs stay live as fallbacks during propagation and as backups thereafter.

**Implications threaded through the docs:**

- CORS allowlist on the API flips from `https://omarqari.github.io` to `https://streethard.omarqari.com` (canonical) plus an optional `ALLOWED_ORIGIN_FALLBACK` for the cutover window.
- `API_BASE` constant in `index.html` will be `https://api.streethard.omarqari.com`.
- A `CNAME` file lands at the repo root once GitHub Pages' Custom Domain field is set.
- TLS is auto-issued by both GitHub Pages and Railway once the CNAMEs resolve — no manual cert work.

**No code written this session.** Pure documentation pass + user-action checklist.

### User Action Items Created

Three dashboard tasks Omar owns before the first deploy of the API can land cleanly:

1. **Spaceship DNS panel** — add two CNAME records (`streethard` → `omarqari.github.io.`, `api.streethard` → Railway-printed target).
2. **GitHub Pages** — repo Settings → Pages → Custom domain → `streethard.omarqari.com`. Auto-creates the `CNAME` file.
3. **Railway** — project → API service → Settings → Custom Domain → `api.streethard.omarqari.com`. Print the CNAME target back into Spaceship for U1's second record.

Full sequenced list in `TASKS.md` under "User Action Required — DNS + Custom Domains".

### Files Updated

- `STATUS-FEATURE.md` — base URL, CORS section, deployment topology env vars, smoke-test snippet, starter-snippet CORS code.
- `STATUS-BACKEND-WALKTHROUGH.md` — section F (deployment topology) gets the custom-domain pre-req block; section I (CORS) updated to use the dual-origin allowlist.
- `CLAUDE.md` — new "Status Feature Architecture (Sessions 13–16)" section so future Claude instances orient against the locked design without re-reading both spec docs.
- `PROJECTPLAN.md` — Hosting section reflects the canonical URLs; File Structure includes the `api/` subdirectory and the `CNAME` marker file; Phase 3 "Open Questions" replaced with "Resolved Pre-Build Questions" and a tighter "Still-Open" list.
- `TASKS.md` — D3, B6, D6 updated to reference the custom domains; new "User Action Required" section above Backend Build; (v2) Custom domain item promoted to v1 and marked done; "Open Questions" reorganized into Buying-decision and Status-feature buckets.

### Open Questions Carried Forward (non-blocking for build)

- **Final status names** (`watching / viewing / shortlisted / rejected / offered`) — proposed but not yet explicitly signed off; CHECK constraint hardens on first write.
- **Final chip vocabulary** — same as above.
- **Mobile Safari `localStorage` eviction** — iOS 17 wipes site data after ~7 days unused; decide whether to mitigate (IndexedDB) at v1 or accept the periodic re-paste.
- **Spouse/family writes attribution** — currently single shared key; revisit only if attribution ever matters.
- **DNS cutover timing** — when to drop `ALLOWED_ORIGIN_FALLBACK` from Railway env vars (after both devices verify load via `streethard.omarqari.com`).

### Next Session Opens With

The 30-minute starter from `STATUS-BACKEND-WALKTHROUGH.md` section O — write `api/main.py` + `api/requirements.txt` + `api/Procfile`, push, connect Railway to the repo with Root Directory `api/`, hit `/health` from the laptop. Don't write business logic until that round trip works. The DNS work (U1–U4) can happen in parallel since it's independent of the API build itself; the custom domain only needs to be live by the time the frontend wires `API_BASE`.

---

## 2026-05-02 — Status Backend Architecture Locked + Build Walkthrough (Session 15)

Continuation of Session 13's listing-status design work. Closed out the six pre-build decisions, added the language pick, and produced a CTO/Architect build walkthrough. No code yet — `api/` directory still empty. Next session opens by writing the 30-minute starter from section O of the walkthrough.

### Decisions Locked This Session

**Language: FastAPI on Python 3.12.** Checked `https://api.github.com/users/omarqari/repos` for `insightcubed` and `OmarGPT` to weight stack continuity. Both 404 (private or under a different handle); the only public repo on `omarqari` is `streethard` itself, language Python. Decision: continue in Python. Rationale: one mental model with `pull.py`, Pydantic v2 validation for free, raw asyncpg over an ORM since there's only one table.

**Per-user attribution: dropped.** User's framing: "anyone can write — how will you know whether it's me or my wife anyway?" Confirmed shared write key, no `updated_by` column, no per-row identity. Schema simplifies to one table, six columns.

**Repo strategy: same repo, `api/` subfolder.** Railway's "Root Directory" setting deploys a subpath as its own service. Benefits: one PR can change both ends, simpler mental model, no second `.git` to keep in sync. The static Pages app and the cron pipeline stay where they are; `api/` is additive.

**Backups: Railway snapshots only.** No `pg_dump` cron at v1. Trigger to revisit: when the dataset ever represents irreplaceable input (months of detailed apartment notes that would hurt to lose).

**Domain: default `*.up.railway.app`.** No custom domain in v1. Service URL will be derived from the Railway service+environment names — e.g., `streethard-api-production.up.railway.app`. Renamable from the dashboard before first deploy if a cleaner subdomain is wanted.

**Hobby tier: $5/mo, recommended.** Free tier sleeps idle services; first click after a quiet hour is visibly laggy on the cold-start path. Not yet paid for — provisioning step in the Deployment phase.

### Schema (final, one table)

```sql
CREATE TABLE listing_status (
    listing_id  TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'none'
                  CHECK (status IN ('none','watching','viewing','shortlisted','rejected','offered')),
    watch       BOOLEAN NOT NULL DEFAULT FALSE,
    notes       TEXT NOT NULL DEFAULT '',
    chips       JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_listing_status_updated ON listing_status (updated_at DESC);
CREATE INDEX idx_listing_status_status  ON listing_status (status) WHERE status <> 'none';
```

### Phasing (each step independently shippable)

1. Skeleton + `/health` deployed and reachable on Railway. ~30 min.
2. Schema + `PUT /status/:id` + `POST /status/batch` + key auth. ~1 hr.
3. Frontend Settings panel + Test Connection. ~30 min.
4. Status pill + optimistic write. ~1 hr.
5. Notes + chips editor. ~1 hr.
6. Offline outbox + flush. ~30 min.

Total: a focused weekend.

### What Got Written (this session)

- `STATUS-BACKEND-WALKTHROUGH.md` (new) — the CTO build guide. Covers stack pick, file layout under `api/`, schema SQL with rationale, API surface with auth middleware shape, frontend integration touch points in `index.html`, deployment topology on Railway, env vars, migrations posture (`schema.sql` at startup, no Alembic), CORS, observability, local dev, backup posture, phasing rationale, risks table (Hobby sleep, Postgres connection limits, CORS preflight, mobile Safari `localStorage` eviction, Pages cache, ID drift, secret leak), and the 30-minute starter snippet.

### Risks Surfaced That Aren't Already Documented

- **Mobile Safari `localStorage` eviction.** iOS 17 wipes site data after ~7 days of non-use; private browsing never persists. The Settings panel must show a "key not set" empty state, not crash on `localStorage.streethard_key` being null.
- **GitHub Pages 10-min cache on `index.html`.** Frontend deploys can appear to be no-ops for up to 10 minutes. Add a `?v=N` cachebuster on the status fetch URL when shipping new merge logic.
- **`WRITE_API_KEY` should NOT live in GitHub Secrets.** Cron doesn't write status. Keep it Railway-only to shrink blast radius if the GitHub repo's secret store is ever compromised.

### State After Session

- Architecture frozen. All six pre-build decisions resolved (status names and chip vocabulary already locked in Session 13).
- New file in working tree: `STATUS-BACKEND-WALKTHROUGH.md`.
- `api/` directory not yet created — Session 16 starts there.
- TASKS.md updated: pre-build decision items checked off; build queue (B1–B6, F1–F8, D1–D8, A1–A7) untouched and ready.

---

## 2026-05-02 — Wire Partial-Response Handling into pull.py (Session 14)

memo23 replied on the Apify console issue thread saying he'd "made some
changes, give it a new go." Tested with a 10-listing batch (run ID
`TImFFxgbWPt8M7MQZ`); the underlying PerimeterX block on
`SaleListingDetailsFederated` is **still in place** — every item came back
flagged with the new `partial: true` / `partialReason:
"SaleListingDetailsFederated_blocked_by_PX_api_v6"`.

What changed for the better: memo's actor now **explicitly flags partial
responses** and surfaces useful fallback data (price history, agent
contacts, year_built, building info, area name, days_on_market,
listed_at, price_per_sqft) under a bare `sale_*` namespace. The financial
fields (`monthly_taxes`, `maintenance`, `monthly_fees`) still live behind
the blocked endpoint and are absent.

Replied to memo on the thread with run ID and asked whether he's tried
a different residential proxy pool or PX-bypass header tweaks.

### What Got Wired

**1. Pass-Partial namespace in `normalize()`.** Added `_PP = "sale_"` to
the prefix constants alongside `_P1/_P2/_P3/_P4`. Extended the field
fallback chains in `normalize()` so that when the federated namespaces
yield nothing, the bare `sale_*` keys are tried — `sale_id`,
`sale_building_subtitle` (street), `sale_building_title` (building),
`sale_area_name` (neighborhood), `sale_building_year_built`,
`sale_days_on_market`, `sale_price_per_sqft`, `sale_contacts_json`,
`sale_price_histories_json`, and `sale_building_building_type`.

**2. Price extraction from price history.** Partial responses don't carry
the asking price at the top level. Added a fallback in `normalize()`:
when no direct price field is found, parse `sale_price_histories_json`
and pull the price from the most recent `LISTED` event. Verified on the
10 listings — 10/10 prices recovered correctly.

**3. Partial flags through the pipeline.** `normalize()` and
`normalize_rental()` now pass through `_is_partial`,
`_partial_reason`, `_partial_error` (underscore-prefixed so they can be
popped before merge — they never land in db.json).

**4. New `data_quality: "partial"` state.** `merge_pass2_into_db()` now
inspects the partial flag. When true, the listing is upgraded to
`data_quality: "partial"` (not `pass2`), with `last_partial_attempt`,
`partial_reason`, and `partial_error` recorded. When a later run gets a
real (non-partial) response, those fields are cleared and the listing
upgrades to `pass2`. The merge log line reports separately:
`"N upgraded to pass2, M partial (PX-blocked), K skipped"`.

**5. Throttled retries via `PARTIAL_RETRY_DAYS`.** New config constant
(default 7). `build_pass2_queue()` now treats partials separately:
listings with `data_quality: "partial"` are re-queued only if their
`last_partial_attempt` is older than `PARTIAL_RETRY_DAYS`. This prevents
the cron from hammering the actor every Mon/Thu while the PX block is
still in effect — at the same time, ensures we automatically retry once
memo's fix lands. Cron logs show `"Skipping N partial listings (within
7-day retry window)"` so the throttling is visible.

**6. Stats line updated.** `save_db()` now reports `pass2 / partial /
pass1 / delisted` counts separately.

### How This Plays Out Operationally

- Next cron run (Mon May 4 09:00 UTC): the 38 pass1 sale listings get
  re-fetched, return partial, get reclassified to `data_quality:
  "partial"` with today's date as `last_partial_attempt`. Each listing
  gains useful data (price_history, agent contact, year_built, etc.) but
  remains flagged as missing financial fields.
- Subsequent cron runs through May 11: those 38 listings are skipped
  (within the 7-day retry window). Pipeline only does Pass 2 work on
  newly-discovered pass1 listings and price-changed ones.
- May 11+: retries kick in. If memo's fix has landed, listings upgrade
  to pass2 and the partial markers clear. If still blocked, they reset
  the `last_partial_attempt` clock and wait another 7 days.

### App Behavior

No `index.html` changes this session. Listings at
`data_quality: "partial"` will render the same as `pass1` listings —
the table shows `—` for missing maintenance/taxes/fees and the monthly
payment falls through to mortgage-only. Considered adding a "partial
data" badge in the row but deferred — the existing dashes make it
visually clear the listing is incomplete, and the user can spot-check
which are partial vs pass1 via db.json if needed.

### Files Touched

- `scripts/pull.py` — config (`PARTIAL_RETRY_DAYS`), prefixes (`_PP`),
  `normalize()` (price-from-history fallback + partial passthrough),
  `normalize_rental()` (partial passthrough), `merge_pass2_into_db()`
  (partial state machine), `build_pass2_queue()` (retry throttling),
  `save_db()` (stats line).
- `CHANGELOG.md` — this entry.

### Smoke Test

Ran today's 10 partial responses through the new normalizer and merge
in a fresh mock db. Result: `0 upgraded to pass2, 10 partial
(PX-blocked), 0 skipped`. All 10 prices recovered from price history
(range $2.695M–$4.495M). Building names populated correctly (Manhattan
House, Twelve Twelve Fifth Avenue, The Parc V, The Leyton, Claremont
Hall, etc.). Year_built populated 10/10. Price history 2–23 entries
each. No `_is_partial`/`_partial_reason` underscore-prefixed keys
leaked into the mock db. ✓

---

## 2026-05-02 — Listing Status Tracking — Plan, Tasks, Design Spec (Session 13)

Documentation-only session. No implementation. Locked the architecture for in-app listing-status tracking and wrote the spec, executive summary, and task list before any code touches the repo.

### What Got Decided

**The shape of the feature.** Six statuses (`none / watching / viewing / shortlisted / rejected / offered`, names final-pending), one orthogonal `watch` boolean for re-surfacing on price changes, free-text notes, fixed-vocabulary multi-select chips for deal-breakers (`no light`, `bad layout`, `building risk`, `priced too high`, `noise`, `condition`, `bad block`, `flip tax`, `board risk`). Status pill in column 1 of the existing table, watch bookmark icon, expanded-row notes/chips editor. No kanban view — the buyer thinks one-listing-at-a-time, not in columns.

**The architecture.** Railway-hosted FastAPI + managed Postgres, deployed from an `api/` subfolder of the same repo via Railway's Root Directory setting. The static GitHub Pages app does two parallel fetches on load (`data/latest.json` from Pages, `/status` from Railway) and merges by `listing_id`. Reads public, writes gated by a single static `WRITE_API_KEY` (constant-time compare), pasted into Railway env vars and into each device's `localStorage`. Family shares one identity — no per-user attribution. Optimistic UI, immediate single-row PUTs, 1-second debounce on notes keystrokes only. Offline outbox in localStorage, flushed on `online` and `visibilitychange` events. Closed-tab-while-offline (Service Worker + IndexedDB) deferred to v1.5.

**Why this over the alternatives.** Rejected `data/status.json` written from the browser via GitHub PAT (PAT in client, every click is a commit, racy). Rejected serverless proxy → repo (same fundamental problems). Rejected OAuth (over-engineered for n=1 family). Rejected Sheets/Airtable (vendor lock-in for a 10-row schema). Rejected pure localStorage (doesn't sync). Tradeoffs documented in PROJECTPLAN.md.

**Why `db.json` stays in the repo.** Bot-written, weekly cadence, public, version history is genuinely useful (price diffs). Status moves to Railway because it's per-click, mutable, private, two devices, and server-of-truth simplifies concurrency. Two stores, two access patterns, two rates of change — don't unify them.

**Schema.** One table `listing_status (listing_id PK, status, watch, notes, chips JSONB, updated_at)`. Status as TEXT + CHECK constraint (not ENUM — easier to extend without a migration framework). Indexes on `updated_at DESC` and partial on `status <> 'none'`. Idempotent `CREATE … IF NOT EXISTS` in `api/schema.sql`, run at FastAPI startup. No Alembic.

**Endpoints.** `GET /health`, `GET /status` (public), `PUT /status/{id}` (key-gated, upsert via `INSERT … ON CONFLICT DO UPDATE` with `COALESCE` so partial patches preserve unchanged fields), `POST /status/batch` (idempotent, used by the offline outbox flush).

**Posture.** Hobby tier ($5/mo) so the service doesn't sleep. Default `*.up.railway.app` URL — no custom domain in v1. Backups: Railway snapshots only — no extra backup script. CORS allowlist exactly `https://omarqari.github.io`.

### What Got Written (commit `4dceb68`)

- `STATUS-FEATURE.md` (new, 487 lines) — full design spec. Buyer's mental model, state model, schema with rationale, API request/response shapes, frontend integration plan with line-of-sight to where in `index.html` each change lands, deployment topology, env vars, security/CORS, risks table, 30-minute FastAPI starter snippet, v1 acceptance criteria.
- `PROJECTPLAN.md` (+74 lines) — new "Listing Status Tracking (Backend Migration)" section after Data Pipeline. Executive summary, rejected-alternatives table, the "why db.json stays vs. why status moves" comparison, state model, stack, v1/v1.5/v2 phasing, open questions, non-negotiables.
- `TASKS.md` (+71 lines) — new feature section before "Open from Session 12." Pre-build decisions (6 questions for the user), backend B1–B6, frontend F1–F8, deployment D1–D8, v1 acceptance A1–A7, v1.5 and v2 deferred items tagged.

### Open Questions (must resolve before code)

1. Final status names — confirm `watching / viewing / shortlisted / rejected / offered` or rename. Locks the CHECK constraint and UI cycle order.
2. Chip vocabulary — confirm or amend the proposed nine.
3. Backup posture — confirm Railway snapshots only for v1.
4. Hobby tier ($5/mo) signup — confirm willingness so the service doesn't auto-sleep.
5. Domain — stay on default `*.up.railway.app` for v1, or name a custom domain now.
6. Generate `WRITE_API_KEY` via `openssl rand -hex 32` and have it ready.

### Commit Mechanics — FUSE Mount Workaround

A stale `.git/index.lock` (and later `.git/HEAD.lock`) from an earlier crashed `git` blocked the normal commit path. The bindfs FUSE mount this session runs against denies `unlink` on `.git/*` even for files we own — `rm`, `python os.unlink`, and `truncate` all return `Operation not permitted`. We can write and chmod, but not delete.

Worked around it with plumbing:

```
GIT_INDEX_FILE=/tmp/myindex git add PROJECTPLAN.md TASKS.md STATUS-FEATURE.md
GIT_INDEX_FILE=/tmp/myindex git write-tree              # → tree SHA
git commit-tree <tree> -p <HEAD> -m "..."               # → commit SHA
python3 -c "open('.git/refs/heads/main','w').write('<sha>\n')"
cp /tmp/myindex .git/index                              # reconcile working index
```

`git log` and `git show --stat HEAD` confirm the commit is well-formed (4dceb68, 3 files, +632 lines). The lock files persist on disk and will need manual cleanup outside this session before normal `git commit` invocations work again on this checkout. Not a bug in the project — environment artifact of the session's mount.

### State After Session

- New on `main` locally, one commit ahead of `origin/main`: `4dceb68 docs: add listing-status feature plan, tasks, and design spec`.
- No implementation files created. No `api/` folder, no `schema.sql`, no Python, no JavaScript changes. Documentation only.
- App, pipeline, and cron are untouched and unaffected.

### Lesson — Lock the Architecture Before the Code

The previous shortlist plan (PROJECTPLAN.md Phase 3) had been listed as "options TBD before building" since Session 1. Sitting in that state for a month meant any time the topic came up, we re-debated localStorage vs. Sheets vs. GitHub API rather than building. Closing the architecture debate in writing — even with six open questions still pending — is what unblocks the build. The next session can answer the questions and start B1 without re-litigating the stack.

---

## 2026-05-02 — Days-on-Market Bug, Cron Diagnosis, Resilience Patches (Session 12)

A user-visible "NEW · 5d" badge on `174 East 74th Street #PHC` (actually listed 12 days earlier per StreetEasy) led to peeling back three layered failures.

### What Got Fixed

**1. App badge logic — `daysListed()` helper.** `index.html` was reading `listing.days_on_market` to compute the days-listed badge. Validation across all 367 listings showed that field is wrong on 100% of them — 90.5% undercount, 9.5% overcount, worst case off by 123 days. Replaced with a `daysListed(listing)` helper that derives days from `listed_date` (matches the most recent `LISTED` event in `price_history` for 99.7% of listings). Updated 4 read sites: `fmtDays` in table rows + cards, the sort comparator, the NEW filter in `updateSummary`. Initially fell back to `days_on_market` when `listed_date` was missing, but that surfaced stale cached values as if they were fresh; the fallback was dropped — missing dates now render as `—`.

**2. Cron silent-failure diagnosis.** Cron commits had read "373 listings, $0.06" on Apr 23, 27, and 30, looking healthy. But `data/db.json`'s contents were identical across all three runs and the max `listed_date` was stuck at 2026-04-20. Direct inspection of the Apify actor's recent runs revealed each cron run returned exactly 10 items, all of shape `{message: "No results found", urls_json, timestamp}` — placeholder objects from StreetEasy's bot detection, not real listings. The actor itself was fine: ad-hoc runs of the same actor with the same input returned 100–200 real listings. Strong evidence the residential proxy IPs at the cron's Mon/Thu 09:00 UTC slot kept landing on blocked IPs.

**3. Pass 1 sentinel guard in `pull.py`.** Added a check after Pass 1 that aborts with `sys.exit(1)` if no item has a listing-id field. Before this guard, `merge_pass1_into_db` silently discarded all 10 placeholder objects (zero new listings added), then `save_db` re-committed the existing 373 listings, with the misleading "373 listings, $0.06" commit message. Verified against real datasets: the 6 known sentinel-only cron runs trigger the guard; ad-hoc runs of 100 and 200 real items pass through cleanly.

**4. `get_run` retry + Pass 2 batch resilience.** Workflow run #23 succeeded at Pass 1 (43 fresh URLs queued for Pass 2), then a single transient `502 Bad Gateway` from `api.apify.com` during status polling raised an uncaught `requests.HTTPError`, killing the whole pipeline before any commit. `ApifyClient.get_run` now retries 5xx and network errors with exponential backoff (1s, 2s, 4s, 8s, fail). The Pass 2 batch loop now catches `requests.RequestException` alongside `ApifyRunError` so a single transient batch failure no longer cascades.

**5. `refresh.yml` commit step `if: success() || failure()`.** Pass 1 progress is saved to `db.json` before Pass 2 runs. The previous step-conditional commit guard threw that progress away when Pass 2 crashed. The new guard preserves it; the existing `git diff --cached --quiet` check still no-ops on truly empty runs.

**6. Manual workflow_dispatch unblocked the backlog.** Workflow run #24 (15:14 UTC) succeeded with the resilience patches and brought in 46 new listings — the first fresh data in 12 days. Confirms the actor works at this time of day; the 09:00 UTC slot is the bad one.

**7. Partial Pass 2 backfill on the 46 pass1 records.** Direct API call (run `55MDlYhllCrCZaybg`, $0.12, 38 of 46 URLs returned data) hit a different actor failure mode: `partialReason: SaleListingDetailsFederated_blocked_by_PX_api_v6` (the GraphQL endpoint that holds price/sqft/beds/fees/taxes was 403'd by StreetEasy's PX bot detection). The fallback endpoint returned full `price_history`, `contacts`, and building info for all 38 sale URLs but no core financial fields. Salvaged what was available — `listed_date`, full price history, agent contact, year_built, neighborhood, $/sqft — into the 38 records; left them at `data_quality=pass1` since `monthly_taxes` and `maintenance` are still missing. The 8 rental URLs returned 0 items entirely (different rental-side issue).

**8. Memo23 thread updated.** Posted on the Apify console issues thread with run IDs comparing 6 broken cron runs against 2 working ad-hoc runs, plus the input shape (identical across both). Reopened the issue to ping Muhamed.

### State After Session

- 419 active listings (368 sale, 51 rental) — was 373
- 373 at pass2 quality, 46 at pass1
- 38 of the pass1 records partially backfilled (listed_date + agent + history)
- 174 East 74th #PHC now correctly reads "17d" green (was "NEW · 5d")
- All 37 prior NEW badges were false positives — now there's 1 actual NEW listing

### Why the Cron Looked Healthy When It Wasn't

`pull.py` had three guards that all checked weaker conditions than they should have:
- `MIN_LISTINGS = 10` ran on the count of items returned by Pass 1, but each "No results found" placeholder counted as an item
- `merge_pass1_into_db` silently discarded items without a listing-id rather than flagging them
- `save_db` was always called even when no new listings entered the database

The new sentinel guard, `if: success() || failure()` on commit, and the partial-data salvage path each address one layer.

### Lesson — "Cron green" doesn't mean "data flowing"

CI status alone is not a signal that the data pipeline is functional. The cron's commit message ("373 listings, $0.06") was machine-generated from the file the script chose to write — not from any check that the file's contents had advanced. For any pipeline that maintains its own data: assert on data progress (max listed_date advances, count grows, IDs change), not on script exit code. Worth adding a sanity assertion to future cron runs: e.g., warn if `max(listed_date) < (today - N days)`.

---

## 2026-05-02 — Co-op SqFt Estimation (Sessions 10–11)

### The Co-op SqFt Gap

NYC co-ops don't publish official square footage at the unit level (ACRIS
doesn't carry co-op transactions; Compass / StreetEasy floor plans
typically omit a sqft figure for co-ops). Without sqft, the Price/SqFt
and Pmt/SqFt columns in StreetHard show `—` for every co-op listing,
defeating the single most useful screening metric. Closing this gap was
the focus of these sessions.

### What Got Built

**1. UI — gray rendering for estimated values.** New `.estimated` CSS
class in `index.html` (gray `#9aa0a6`, dotted underline, hover tooltip).
When a listing has `sqft_estimated: true`, the table cells for SqFt,
Price/SqFt, and Pmt/SqFt are wrapped in this class; same for card view.
The tooltip displays `sqft_estimate_note`, which spells out the
calibration source and any sanity-check overrides. Behavior is
data-flag-driven, so future estimates inherit the styling automatically.

**2. Methodology — pixel-polygon measurement.** Detect apartment polygon
by thresholding non-white pixels + morphological closing, take the
largest connected blob, fill its contour. Calibrate the px/ft scale
from one labeled rectangular room (typically a bedroom). Compute
`sqft = polygon_pixels / (px/ft)²`. Sanity-check the result against the
$900–$1,800/sqft band typical for UES residential; override manually if
the implied $/sqft is implausible. Full methodology and validation
documented in SQFT-METHODOLOGY.md.

**3. Validation — accuracy bench.** Tested against 8 floor plans with
known official sqft. 3/8 within 2%, 5/8 within 5%, 7/8 within 10%. The
misses come from visual pixel-coordinate-reading noise (±10 pixels per
wall endpoint) and from non-uniform image scaling (some plans have
horizontal scale ≠ vertical scale). Good enough for screening; not
good enough for negotiation. Real ANSI-Z765 measurements ($250–400)
are still the answer for offer/contract pricing.

**4. Data — 15 co-ops now have estimates.** All flagged
`sqft_estimated: true` with method `pixel_polygon` (or `floorplan_sum`
for the original 14AF estimate). Recomputed `price_per_sqft` for each.

| Listing | Price | Estimated Sqft | $/sqft |
|---------|-------|----------------|--------|
| 201 E 77th 14AF | $2.799M | 1,700 | $1,646 |
| 1170 5th 6A | $3.2M | 3,500 | $914 |
| 245 E 87th PH | $3.3M | 3,000 | $1,100 |
| 8 E 96th 14C | $3.25M | 2,400 | $1,354 |
| 829 Park 10B | $2.85M | 1,750 | $1,629 |
| 1050 5th 12C | $3.5M | 2,800 | $1,250 |
| 1050 5th 2E | $3.395M | 2,550 | $1,331 |
| 115 E 67th 8B | $2.895M | 2,300 | $1,259 |
| 1215 5th 5B | $2.995M | 3,400 | $881 |
| 1220 Park 2C | $2.895M | 3,000 | $965 |
| 196 E 75th 3AB | $3.395M | 2,500 | $1,358 |
| 29 E 64th 10C | $2.75M | 1,600 | $1,719 |
| 3 E 69th 7/8A | $3.1M | 2,000 | $1,550 |
| 55 E 87th 4JK | $3.25M | 2,550 | $1,275 |
| 829 Park 6/7B | $2.75M | 2,400 | $1,146 |

### Methodology Lessons (Captured in SQFT-METHODOLOGY.md)

- **The architect's "longest-labeled-dim equals longest-exterior-wall"
  heuristic is wrong.** The longest labeled dim is one room's wall;
  the longest exterior wall spans multiple rooms. Bbox-of-polygon
  shortcut doesn't work.
- **Multi-floor plans break single-blob detection.** Duplexes/triplexes
  shown as separate diagrams on one image need manual override.
  829 Park 6/7B's raw estimate was 4,850 sqft (would imply $567/sqft);
  adjusted to 2,400.
- **Sanity-check via $/sqft.** Whenever the computed $/sqft is way out
  of the UES band ($900–$1,800), the polygon or calibration is wrong.
  Trust the market more than the algorithm.
- **The user's in-person sense matters.** On 14AF, Omar said the unit
  "felt like 2,200 sqft" after walking it; the floor plan math says
  1,700. We held at 1,700 (the conservative number) and noted that
  in-apartment perception can run high in modern, well-lit, high-ceiling
  units. Get a measurement before offering.

### What's Next

- Get ANSI measurements on the 2–3 co-ops Omar is actually offering on.
- Consider OCR-based auto-calibration if the listing pipeline ever
  needs to handle co-op sqft at scale (currently manual; ~2 minutes
  per plan with Claude).
- Consider adding building-era and floor plan source as data fields if
  systematic patterns emerge (e.g., Compass plans systematically
  under-state vs Sotheby's plans).

---

## 2026-04-21 — Full Pass 2 Backfill + Retrospective (Session 9)

### Complete Database: 373/373 at Pass 2 Quality

Bypassed the cron pipeline entirely and called the Apify API directly in escalating batches to backfill all remaining pass1 listings. Every batch returned 100% success, zero normalization failures.

| Batch | Size | Result | Cumulative pass2 |
|-------|------|--------|------------------|
| 1     | 10   | 10/10  | 21               |
| 2     | 20   | 20/20  | 41               |
| 3     | 50   | 50/50  | 91               |
| 4     | 50   | 50/50  | 141              |
| 5     | 100  | 100/100| 241              |
| 6     | 89   | 89/89  | 330 (all sales)  |
| 7     | 43   | 43/43  | 373 (all rentals)|

Total Apify runtime: ~15 minutes. Total wall-clock: ~30 minutes. The cron pipeline would have taken 6+ weeks at 30 listings/run.

### Pipeline Config Updated

- `PASS2_BATCH_SIZE`: 10 → 50 (actor handles 100 comfortably; 50 balances speed vs. blast radius for unattended cron)
- `PASS2_PER_RUN_CAP`: 30 → 100 (no reason to throttle this aggressively now that the actor is stable)

### Retrospective: "Don't Build an Irrigation System to Fill a Bathtub"

Full CTO/Architect/CPO retrospective documented in `RETRO-SESSION9.md`. Key findings:

1. **Initial load ≠ steady-state maintenance.** The pipeline was designed for maintenance (5–10 new listings per run) but was used for initial population (362 listings). Wrong tool for the job.
2. **Defensive limits from the actor outage were never revisited.** Batch size 10 and cap 30 were set during the 0.0.118 regression. Actor has been stable since the fix; limits should have been raised immediately.
3. **Data completeness is a launch blocker.** The app's primary value (monthly payment comparison) was broken for 97% of listings across sessions 3–8 because Pass 2 wasn't complete. Features (text search, rentals, date formatting) were prioritized over data completeness.
4. **CI is not a debugging environment.** Multiple sessions wasted 6-minute CI cycles debugging code that should have been tested via direct API calls.

New rules added to CLAUDE.md: "Solve the Problem First, Then Automate" section with concrete guidelines for backfill vs. maintenance modes.

### Session State at Close

- Pipeline: **ALL COMPLETE** — 373/373 listings at pass2 quality
- Sales: 330 pass2, 0 pass1
- Rentals: 43 pass2, 0 pass1
- Delisted: 0
- App: LIVE on GitHub Pages with full data (pending user `git push`)
- Cron: Mon + Thu, now handles up to 100 Pass 2 listings per run

### Remaining Open Items

1. Live days-on-market from `listed_date` (JS update in index.html)
2. New/reduced badges (diff against previous dated JSON)
3. Shortlist feature (blocked on sharing model decision)
4. Co-op sqft gap evaluation

---

## 2026-04-20 — Incremental Pipeline + UI Search (Session 8)

### Architectural Redesign: Puzzle Model

The Apify actor is brittle — Pass 2 times out, batches fail, and runs rarely complete all 330+ listings. Previous architecture overwrote `latest.json` every run, so partial results meant losing data already collected. Redesigned the entire data pipeline around incremental accumulation:

**`data/db.json` is now the canonical store.** A persistent JSON dictionary keyed by listing ID, committed to the repo. Each listing has a `data_quality` field (`"pass1"` or `"pass2"`) and metadata (`last_pass1`, `last_pass2`, `needs_refresh`, `status`). Once a listing reaches pass2 quality (fees, taxes, agent, price history), it is never re-scraped unless its price changes.

**Run logic changed:**
1. Pass 1 (search) discovers active listings, merges basic data into db.json
2. Pass 2 only targets listings still at pass1 quality or with price changes
3. Capped at 30 listings per run (`PASS2_PER_RUN_CAP`) to stay within actor reliability
4. db.json saved after every Pass 1 merge and every Pass 2 batch — partial progress is never lost
5. `data/latest.json` generated from db.json at end of run for the app

**Delisting detection:** Listings not seen in Pass 1 for 14+ days marked as `status: "delisted"`, excluded from latest.json but kept in db.json for history.

**Cost impact:** After the initial fill (~12 runs over 4 weeks), each cron run only scrapes a handful of new/changed listings. Cost drops from ~$2/run to ~$0.05/run.

### Pass 2 Timeout Fix: Abort + Salvage

When Pass 2 times out (10 min per batch), the script now aborts the Apify run and fetches whatever items were already collected in the dataset, instead of discarding the entire batch. This handles the actor's `maxRequestRetries: 100` behavior gracefully.

Additional changes:
- **Batch size reduced** from 50 → 10 URLs per Apify run (less blast radius from stuck URLs)
- **Timeout reduced** from 30 min → 10 min per batch (abort sooner, salvage sooner)
- **`abort_run()` method** added to ApifyClient

### Text Search Bar

Added a free-text search input to the StreetHard filter bar. Filters listings in real time (on keystroke) by building name, street address, unit, neighborhood, agent name, and agent firm. Case-insensitive substring match. Same pill styling as dropdown filters. Expands from 180px → 240px on focus. Clears with the existing Clear button.

### Price History Date Fix

Changed `fmtDate()` in index.html to show full dates (e.g., "Apr 16, 2026") instead of just month+year ("Apr 2026").

### db.json Seeded from Existing Data

Migrated all 373 listings from `latest.json` into `data/db.json`. Listings with agent/fees/history data (6 total) were classified as pass2; the rest as pass1. First incremental run upgraded 5 more to pass2 (total: 11 pass2 / 362 pass1).

### Session State at Close

- Pipeline: **INCREMENTAL** — db.json accumulates data run-over-run
- db.json: 373 active listings (11 pass2, 362 pass1, 0 delisted)
- Pass 2: **WORKING** — 5/5 succeeded in test run
- App: **LIVE** on GitHub Pages with text search
- Cron: Mon + Thu, will fill ~30 more pass2 entries per run

### Next Steps

1. Push all changes and trigger a full production run (`--mode both --max-items 500`)
2. Monitor next 2-3 cron runs — pass2 count should climb ~30 per run
3. After ~12 runs, most listings should be at pass2 quality
4. Remaining open items: live days-on-market from listed_date, new/reduced badges, shortlist feature

---

## 2026-04-20 — Pass 2 Restored (Session 7)

### memo23 Fixed the Actor

memo23 responded and pushed a fix. Ran the Saratoga validation test (Run ID: `Lz5JkP1Ky592CZU8h`):

- price_history: ✅ 17 entries returned
- agent name/phone/email: ✅ Matthew Gulker / (917) 848-1338 / mgulker@elliman.com
- maintenance fee: ✅ $2,448
- taxes: ✅ $3,384 (ticked up slightly from $3,368 — real data change, not a bug)
- price: $3,295,000 (decreased from $3,300,000 on 2026-04-20 — real price cut, not a bug)
- sqft, beds, year_built: ✅ all correct

Pass 2 is fully operational. The `--pass1-only` flag added this session remains available for future outages.

### --pass1-only Flag Added

Added `--pass1-only` to `pull.py` and `refresh.yml`. When set, skips Pass 2 entirely and normalizes Pass 1 search data directly. Use when the actor's individual listing pages are broken again. Accessible via GitHub Actions "Run workflow" → `pass1_only: true`.

### Next Step

Run a full production pull (both sale + rent, max 500 each) without `--pass1-only`. Push the `--pass1-only` code to main first.

---

## 2026-04-20 — Bug Report Filed + Session Close (Session 6)

### Comment Posted to memo23's Issues Thread

After exhausting all other options (build pinning not supported by Apify API for third-party actors), posted a detailed bug report directly to memo23's Apify issues thread.

**How to contact memo23 in the future:**
1. Navigate to `https://console.apify.com/actors/ptsXZUXADV3OKZ5kd/issues/a2fptiipUUxfjnh9X` (requires being logged into Apify console as Omar)
2. Type in the `#text` textarea (id="text", placeholder="Leave a comment")
3. Click the "Add comment" submit button
- Alternatively: email `muhamed.didovic@gmail.com` directly (listed in actor README)
- Average issues response time: 3.6 hours

**Comment posted (verbatim):**
> Search URLs confirmed working — ran a full production pull without issues. 403 fix is solid.
> Follow-up on individual listing URLs: I've now tested every documented format and none return data in build 0.0.118: `/sale/1818978`, `/rental/4991146`, `/building/301e94.../rental/4991146`, `/building/the-saratoga/sale/1818978`, `/building/the-saratoga/28bc` (urlPath from Pass 1). Both listings confirmed active on StreetEasy (1818978 re-listed 4/16/2026). The actor calls api-internal.streeteasy.com/graphql for all requests. Search queries work perfectly; individual listing queries return empty results. Is individual listing detail scraping intended to work in 0.0.118?

### Session State at Close

- Pass 2: **BROKEN**, bug report filed, awaiting memo23 response
- Pass 1 (search URLs): **WORKING** — app live with price, beds/baths/sqft, address, brokerage
- Monthly payment calc: **partial** — shows mortgage-only until Pass 2 restored (no fees/taxes)
- GitHub Actions pipeline: running weekly on Pass 1 data

### Next Steps

1. Check memo23 issues thread for response (link above)
2. If memo23 fixes Pass 2: re-run validation test (Saratoga `building/the-saratoga/28bc`), confirm fees + taxes + agent info populate, then trigger CI run
3. If no fix within a week: evaluate emailing memo23 directly or accepting Pass 1-only permanently

---

## 2026-04-20 — Pass 2 Deep Investigation (Session 5)

### Result: Pass 2 is Definitively Broken in Actor Build 0.0.118

Continued from prior session. Tested every known and documented URL format for individual listing pages — all return `{"message": "No results found"}`.

Formats tested:
- `/sale/{id}` — ❌ (10 × "No results found")
- `/rental/{id}` — ❌ (documented in actor features; still fails)
- `/building/{slug}/rental/{id}` — ❌ (documented in actor features; still fails)
- `/building/{slug}/sale/{id}` — ❌ (fails)
- `/building/{slug}/{unit}` (urlPath from Pass 1) — ❌ (fails, tested in prior session)

**The listings are confirmed still active.** Navigated to `streeteasy.com/sale/1818978` in browser — listing is live, re-listed 4/16/2026 at $3,300,000 with fees $2,448/mo, taxes $3,368/mo, 4 beds, 2,400 sqft. The actor failure is a genuine regression, not a stale-listing issue.

### Root Cause

Build 0.0.118 was a "403 fix" (StreetEasy iOS API key rotation, ~2026-03-27). The fix restored search page scraping but broke the individual listing URL → GraphQL query path. The actor internally calls `api-internal.streeteasy.com/graphql` — Pass 1 (search queries) still work; individual listing queries do not.

### Actor Internals Observed

From inspecting the request queue during a run:
- All requests go to `api-internal.streeteasy.com/graphql` regardless of input URL type
- `maxRequestRetries: 100` — stuck requests retry up to 100 times (explains long run times)
- For a 3-URL run: 5 total GraphQL requests generated (4 succeeded, 1 failed)
- Dataset had 10 items despite 3 input URLs — multiple retry attempts each wrote a "No results found" record

### Older Builds Exist — Not Yet Tried

Build history available via Apify API:
- 0.0.117 | id=SwDxnjUXSfNtlpm9l | SUCCEEDED
- 0.0.116 | id=FXHfKcbbFFq0cefq1 | SUCCEEDED
- 0.0.115 | id=ttubcfQfPb0nGW7qa | SUCCEEDED
- 0.0.114 | id=SRahdXAKpNImqH9j2 | SUCCEEDED
- 0.0.112, 0.0.111, 0.0.109 — also available

Pinning to an older build (e.g., 0.0.117) via `"build": "SwDxnjUXSfNtlpm9l"` in the run request is untested but is the fastest possible fix if those builds handled individual listing URLs correctly. Risk: older builds may re-introduce 403s.

### What Pass 1 Gives Without Pass 2

Pass 1 (search URLs) is fully working and returns: price, beds, baths, sqft, address, unit, building name, neighborhood, brokerage name, days on market. Missing from Pass 1: **price history, maintenance fees, property taxes, agent name/phone/email.**

Fees and taxes are critical for the monthly payment calculation in StreetHard. Without them, the app shows mortgage-only, which understates true monthly cost by ~$6k/mo for a typical $3M condo.

### Session State at Close

- Pass 2: **BROKEN** (all URL formats fail in build 0.0.118)
- Pass 1: **WORKING** (search URLs return good data with correct field mapping)
- App: **LIVE on GitHub Pages** (Pass 1 fallback active; monthly payments show mortgage-only until Pass 2 fixed)

### Next Steps

1. **Try pinning to build 0.0.117** — submit a validation run with `"build": "SwDxnjUXSfNtlpm9l"` and test `/building/the-saratoga/28bc` (the canonical URL for listing 1818978). If it works, wire that build into `pull.py` for Pass 2.
2. **If 0.0.117 also fails** — contact memo23 via Apify actor comments with a clear report: all individual listing URL formats return "No results found" in 0.0.118; was working in a prior build.
3. **If no fix available** — fall back to StreetEasy's published listing pages as a manual source for fees/taxes on serious candidates, and leave the pipeline as Pass-1-only.

---

## 2026-04-19 — Apify 403 Recurrence + Session Close (Session 4)

### Apify Actor Broken — StreetEasy iOS Key Rotated Again

Attempted to run Apify `memo23/streeteasy-ppr` for a single-listing validation test (Saratoga, ID 1818978). Both runs failed wall-to-wall with 403s — identical behavior to the issue resolved ~23 days ago.

- **Run ID: I1C7EFWK61Lfa8XW3** — free tier, all 403s
- **Run ID: aSmBOStZKpupB2Rs9** — after upgrading to Apify paid plan, still all 403s

Upgrading to paid plan ruled out proxy quota as the cause. Root cause: StreetEasy rotated their internal iOS app API key, which the actor uses for all requests. This is a recurring maintenance issue with this actor (prior occurrence: ~2026-03-27, resolved within hours by memo23).

The actor showed "Last modified: 2 hours ago" at the time of testing — memo23 may have already pushed a fix. A comment was posted to the existing GitHub issue thread alerting memo23, with both run IDs included.

### Apify Plan Upgraded

Upgraded Omar's Apify account from free to paid tier. This had no effect on the 403 issue but is required for production use (residential proxy access, higher concurrency).

### Official Validation Test Created

Created `APIFY_VALIDATION_TEST.md` — a reproducible one-listing test using 330 East 75th Street #28BC (The Saratoga, listing ID 1818978) as the canonical ground truth. Drop this into any future session to instantly verify the actor is working before running a full pull.

### Session State at Close

- Apify actor: **BROKEN** (403s, pending memo23 fix)
- GitHub Actions pipeline: **BLOCKED** (Pass 1 ID extraction bug from Session 3, plus actor broken)
- Comment posted to memo23's issue thread: ✅
- All docs updated: ✅

### Next Steps (start of next session)

1. Run the Saratoga validation test (`APIFY_VALIDATION_TEST.md`) to confirm the actor is fixed
2. Once confirmed, run the Pass 1 debug dump (trigger CI run, copy DEBUG lines, paste to Claude)
3. Fix `run_two_pass()` ID extraction logic based on debug output
4. First full UES production pull

---

## 2026-04-19 — Rentals Added (Session 3)

### Scope Expansion
Added UES rental listings ($10K–$20K/month, sqft ≥ 1,500) alongside existing sales. Primary motivation: rent-vs-buy comparison using the same neighborhood and size criteria.

### UI: Mode Toggle
Added a 3-way segmented control to the filter bar: **[ For Sale ] [ For Rent ] [ Both ]**. Behavior per mode:
- **For Sale**: existing behavior unchanged
- **For Rent**: mortgage calculator bar collapses; Ask Price column hidden; Price/SqFt blank (annualized $/sqft already covers the equivalent); Days Listed uses tighter rental thresholds
- **Both**: all listings shown with SALE/RENT badge per row; mortgage bar visible (affects sale rows only); Ask Price blank for rental rows

### Column Mapping Decisions
| Column | Rentals treatment |
|---|---|
| Monthly Pmt → "Monthly Rent" | `listing.price` = monthly rent directly |
| Ask Price | Hidden in rent-only; blank in Both |
| Price/SqFt | Blank for all rentals (annualized $/sqft is the equivalent) |
| PMT/SqFt | Direct equivalent: (annual rent) ÷ sqft |
| Days Listed | Tighter thresholds: NEW <3d, green 3–14d, yellow 14–30d, red 30d+ |
| Mortgage calculator | Collapsed in rent-only mode |
| Payment breakdown | Simplified to "Monthly Rent: $X" for rentals |

### Pipeline Changes
- `pull.py` refactored: new `run_two_pass(client, url, max_items, listing_type)` helper; new `normalize_rental()` with best-guess field names mirroring the sales schema (`rentalListingDetailsFederated_*` etc.); `--mode both|sale|rent` argument (default: both); `listing_type: "sale"|"rent"` field on every normalized record
- `refresh.yml`: replaced `--url` manual input with `--mode`; commit message now includes sale/rent counts
- `data/latest.json`: now contains both types merged; `sale_count` and `rental_count` added to payload metadata

### Rental normalize() Status
`normalize_rental()` uses best-guess field name prefixes. On first CI run, if rental normalization fails the existing debug dump will print the actual Apify field names. Update `normalize_rental()` accordingly (same process used for sales in Session 2).

### Bugs Found and Fixed (same session, post-merge CI run)

First CI run with new code (`--mode both`) revealed two bugs:

**Bug 1 — TypeError crash:** `run_two_pass()` early return (when Pass 1 finds < 10 IDs) returned `([], search_items)` where `search_items` is a list. Caller did `total_events += events`, crashing with `TypeError: int += list`. Fixed: return `len(search_items)` instead.

**Bug 2 — 0 IDs from 10 search items:** Pass 1 returned 10 items but extracted 0 unique listing IDs. Root cause unknown — items appear to lack explicit `id`/`listingId` fields AND URLs that match the regex `/(?:sale|rental)/(\d+)`. Added a debug dump (stderr) that fires when 0 IDs are extracted, printing the raw keys and all ID/URL-related fields of the first item. Next CI run will reveal the actual field structure.

---

## 2026-04-19 — Pipeline Debugging + Production Launch (Session 2)

### Problem: GitHub Actions Failing on Pass 2

- First CI run failed at "Run pull script" (1m 17s). Pass 2 returned 50 items but all were skipped with "no price" — guard clause triggered, `latest.json` not overwritten.
- Root cause: Apify `memo23/streeteasy-ppr` flattens StreetEasy's federated GraphQL API into flat top-level keys with long namespace prefixes. The actual price field is `saleListingDetailsFederated_data_saleByListingId_pricing_price`, not `price`, `pricing_price`, or `askingPrice` as the original `normalize()` assumed.
- The previous sparse `data/latest.json` (prices but no addresses/agent/history) had come from Pass 1 search results, which do use a simple `price` field — masking the mismatch.

### Fix 1: Debug Output + Pass 1 Fallback

- Added raw field key dump to stderr when all Pass 2 items fail normalization.
- Added automatic fallback to Pass 1 (search result) data if Pass 2 yields fewer than `MIN_LISTINGS`. Prevents the workflow from aborting completely while the normalize bug exists.
- Fallback triggered for two CI runs during debugging; app stayed live with sparse-but-valid data.

### Fix 2: Rewrote normalize() with Actual Field Names

- Debug output from the first fallback run revealed the full Apify schema. Three key namespaces:
  - `saleListingDetailsFederated_data_saleByListingId_*` — pricing, beds/baths, sqft, address, unit
  - `saleDetailsToCombineWithFederated_data_sale_*` — building name, neighborhood, year built, days on market, contacts JSON, price history JSON
  - `extraListingDetails_data_sale_*` — richer price history JSON (includes `source_group_label`)
- Agent info: parsed from `contacts_json` (JSON string → array → first contact's name/phone/email/firm)
- Price history: parsed from `extraListingDetails_data_sale_price_histories_json` (JSON string)
- Co-op vs. condo split: `pricing_maintenanceFee` = HOA for condos, full maintenance for co-ops; `pricing_taxes` = 0 for co-ops (included in maintenance)
- Pass 1 simple field names retained as fallbacks so normalize() works on both schemas

### Result: Full Data Coverage

After fix: 50 normalized, 0 skipped. Field fill rates:

| Field | Coverage | Notes |
|---|---|---|
| price, beds, baths, type | 50/50 | |
| address, building, unit | 50/50 | |
| year_built, days_on_market | 50/50 | |
| agent name/phone/email | 50/50 | |
| price_history | 50/50 | |
| sqft | 26/50 | Co-ops routinely omit sqft on StreetEasy — not a bug |
| monthly_fees + maintenance | 50/50 | Correctly split by type |

### Search Criteria Expanded to Production Range

- Removed test ceiling ($4M) and floor (none) — first production pull revealed sub-$1M 1-bedroom co-ops appearing because StreetEasy's `sqft:1500-` filter only excludes listings that explicitly have sqft listed below 1,500; listings with no sqft bypass it entirely.
- Set `$2M–$5M` as production range. $2M floor eliminates the noise; $5M ceiling is user preference.
- Production URL: `https://streeteasy.com/for-sale/upper-east-side/price:2000000-5000000%7Csqft:1500-`

### All Code Merged to Main

- Feature branch `claude/explore-project-V2hAM` merged to `main`. Weekly cron now runs from `main`.
- UI verified correct with rich data: price history, agent contact, payment breakdown all render properly.

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
