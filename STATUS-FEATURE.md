# STATUS-FEATURE — Listing Status Tracking

Design spec for the in-app status tracking feature. PROJECTPLAN.md has the executive summary; TASKS.md has the to-do; this is the source of truth for the build.

---

## Problem

StreetHard is read-only today. Family members browse the same 419 listings with no way to mark "I've already toured this," "we've vetoed this co-op for the lobby," or "this is the one we're offering on." The buyer's mental model and the app's data model don't meet.

The shopping process is intrinsically stateful — a candidate moves through *seen → toured → shortlisted → offered → won/lost*. We need that state in the app, shared across two devices (laptop + phone), persistent across deploys, and editable by anyone in the family who has the key.

---

## Buyer's Mental Model (Revised — Session 21)

The user thinks in terms of an **email inbox**: new listings arrive, get triaged, and move to either "actively pursuing" or "not interested." The key insight is that a rejected listing should come back if its price drops — like an email that auto-returns to your inbox when something changes.

Workflow:

1. Cron drops new listings into the **Inbox** — the default triage space.
2. User opens StreetHard, sees 12 new listings in Inbox since last visit.
3. Quickly archives the obvious no's. Shortlists the interesting ones.
4. Shortlisted items get OQ/RQ rankings, notes, chips — the due diligence workspace.
5. An archived listing's price drops → it auto-resurrects in the Inbox with a "Price dropped" badge. User re-triages with fresh eyes.
6. Everything syncs across laptop + phone.

No kanban view. No multi-step status progression. Three buckets, clear transitions, one question per listing: "Inbox, Shortlist, or Archive?"

---

## State Model (Three-Bucket Triage)

### Bucket (one of three)

| Bucket | Meaning | OQ/RQ Rankings? | Default sort |
|---|---|---|---|
| `inbox` | Untriaged / new arrivals. The triage workspace. | No | Monthly Payment desc |
| `shortlist` | Actively pursuing. Due diligence, tours, ranking. | **Yes** | OQ# ascending |
| `archive` | Rejected / passed on. Out of active attention. | No | `bucket_changed_at` desc |

Every listing lives in exactly one bucket. Listings without a status row (i.e., all new listings from the cron) are implicitly in `inbox`.

### Transitions

| From | To | Action | Side effects |
|---|---|---|---|
| Inbox | Shortlist | ★ Shortlist button | — |
| Inbox | Archive | Archive ↓ button | Records `price_at_archive` |
| Shortlist | Archive | Archive ↓ button | **Clears OQ/RQ rankings** (server-enforced), records `price_at_archive` |
| Shortlist | Inbox | ← Inbox button | **Clears OQ/RQ rankings** (server-enforced) |
| Archive | Inbox | ← Inbox button (manual) or auto-resurrection (price drop) | — |

**OQ/RQ clearing is server-enforced.** The PUT endpoint detects when `bucket` changes FROM `shortlist` and forcibly nulls `oq_rank` and `rq_rank` regardless of what the client sends. This makes the invariant "rankings only exist on shortlisted items" impossible to violate at the data layer.

### Auto-Resurrection (Archive → Inbox on price drop)

When a listing is archived, the app records `price_at_archive` (the listing's ask price at that moment). On each page load, the frontend compares each archived listing's current price against `price_at_archive`. If current price < `price_at_archive`, the listing auto-promotes to Inbox with a "Price dropped" badge.

If the user re-archives at the new lower price, `price_at_archive` updates to the new price — no ping-pong unless there's another drop.

Edge case: if `price_at_archive` is null (listing had no price, or legacy data), skip the comparison.

### Notes (free text)

Persist across all buckets. A textarea in the expanded row. Soft-cap ~2,000 chars in the UI. Last-write-wins. Notes provide context regardless of bucket — "overpriced by $200K" is useful if the listing resurrects.

### Chips (structured deal-breakers — Shortlist only in v1)

A fixed vocabulary of multi-select chips: `no light`, `bad layout`, `building risk`, `priced too high`, `noise`, `condition`, `bad block`, `flip tax`, `board risk`. Stored as a JSON array. Only shown/editable on Shortlisted items (during due diligence). Designed to make "why did we kill this?" answerable in one glance.

### OQ/RQ Rankings (Shortlist only)

OQ# (Omar's Queue) and RQ# (Roya's Queue) are integer priority ranks. Only meaningful while a listing is shortlisted — they represent "my personal priority order among the listings I'm actively pursuing." Cleared on exit from Shortlist because they'd be stale/meaningless if the listing returns later.

---

## Architecture Decision

### Chosen: Railway-hosted FastAPI + managed Postgres

The app makes two fetches on load:

1. `data/latest.json` from GitHub Pages — the listings (bot-written, weekly).
2. `https://api.streethard.omarqari.com/status` — the status overlay (per-click, mutable).

Merge by `listing_id` in the browser. Render. Writes go to `PUT /status/{id}` immediately, optimistic in the UI, key-gated on the server.

Both ends sit on user-owned custom domains (Session 16):

- `streethard.omarqari.com` → CNAME → `omarqari.github.io` (the static app)
- `api.streethard.omarqari.com` → CNAME → the Railway API service

DNS records live on Spaceship (Omar's registrar). The default `*.up.railway.app` and `omarqari.github.io/streethard` URLs continue to resolve as fallbacks during the cutover but are not the canonical surface.

### Why this over the alternatives

| Option | Why rejected |
|---|---|
| `data/status.json` in the repo, written via GitHub PAT from the browser | Requires shipping a PAT to the client, even a fine-grained one. Rate-limited. Every status click is a git commit — an absurd ratio of writes-to-noise in repo history. Two writers within the same minute can race. |
| Serverless proxy (Vercel/Cloudflare) → repo | Same fundamental problem — we'd just be hiding the PAT behind another service. Doesn't solve concurrency. |
| OAuth flow (real auth) | Massively over-engineered for a family of 2–4 people sharing one identity. Adds a login screen to a tool the user just wants to open and use. |
| Google Sheets / Airtable / Notion | Vendor lock-in for a 10-row schema. Their UIs leak through, latency varies, and rate limits bite at the worst moment. |
| Pure `localStorage` | Doesn't sync across devices. Phone-after-tour state lost when you open the laptop at home. |

### Why `db.json` stays in the repo

| `db.json` (stays in repo) | `listing_status` (moves to Railway) |
|---|---|
| Bot-written, weekly cadence | Per-click, multiple writes per minute possible |
| Public market data | Mutable opinions + private notes |
| One writer (the cron) | Two devices, racy |
| Version history is genuinely useful (price diffs) | Version history is noise |
| Static-friendly (Pages serves it) | Server-of-truth simplifies concurrency |

Two stores, two access patterns, two rates of change. Don't unify them.

---

## Schema (Revised — Session 21, Three-Bucket)

One table. One PK. No migrations framework; the SQL is idempotent and runs at FastAPI startup.

```sql
-- api/schema.sql (target state after migration)
CREATE TABLE IF NOT EXISTS listing_status (
    listing_id        TEXT        PRIMARY KEY,
    bucket            TEXT        NOT NULL DEFAULT 'inbox'
                                  CHECK (bucket IN ('inbox','shortlist','archive')),
    bucket_changed_at TIMESTAMPTZ,
    price_at_archive  INTEGER,
    oq_rank           INTEGER,
    rq_rank           INTEGER,
    oq_notes          TEXT        NOT NULL DEFAULT '',
    rq_notes          TEXT        NOT NULL DEFAULT '',
    chips             JSONB       NOT NULL DEFAULT '[]'::jsonb,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS listing_status_updated_at_idx
    ON listing_status (updated_at DESC);

CREATE INDEX IF NOT EXISTS listing_status_bucket_idx
    ON listing_status (bucket);
```

### Migration from old schema (run once)

```sql
ALTER TABLE listing_status ADD COLUMN IF NOT EXISTS bucket TEXT NOT NULL DEFAULT 'inbox';
ALTER TABLE listing_status ADD COLUMN IF NOT EXISTS bucket_changed_at TIMESTAMPTZ;
ALTER TABLE listing_status ADD COLUMN IF NOT EXISTS price_at_archive INTEGER;

-- Migrate existing data
UPDATE listing_status SET bucket = 'shortlist' WHERE watch = true;
UPDATE listing_status SET bucket_changed_at = updated_at;

-- After verifying new code works:
-- ALTER TABLE listing_status DROP COLUMN IF EXISTS status;
-- ALTER TABLE listing_status DROP COLUMN IF EXISTS watch;
```

### Notes on the schema

- `listing_id` matches the StreetEasy ID used as key in `db.json`. No FK — `listing_status` survives independently of `db.json` revisions.
- `bucket` is TEXT + CHECK. Three values only. Simple, clear, no cycle-order to reason about.
- `bucket_changed_at` tracks when the listing last changed buckets. Used to sort Archive (most recently archived first) and for potential future "how long has this been shortlisted?" UX.
- `price_at_archive` records the ask price at the moment of archiving. Used by the auto-resurrection comparison on frontend load. NULL if never archived or if price was unavailable.
- `oq_rank` / `rq_rank` are only meaningful when `bucket = 'shortlist'`. The API enforces: on any transition OUT of shortlist, these are set to NULL server-side.
- `chips` JSONB — opaque blob the client owns. Never queried server-side.
- `updated_at` is server-set on every write.

---

## API

Base URL: `https://api.streethard.omarqari.com` (custom domain on Spaceship → Railway service, decided Session 16). The default `*.up.railway.app` URL is also live and works for ad-hoc curl while DNS is propagating.

### `GET /health`

Liveness check used by Settings → Test Connection and by Railway's healthcheck.

```json
200 OK
{"ok": true, "db": "connected"}
```

### `GET /status`

Public read. No auth. Returns every row.

```json
200 OK
{
  "items": [
    {
      "listing_id": "1818978",
      "status": "shortlisted",
      "watch": true,
      "notes": "Saratoga PHC — Omar toured 4/22, liked layout but hates the lobby renovation timeline",
      "chips": ["building risk"],
      "updated_at": "2026-05-02T18:14:22Z"
    }
  ]
}
```

Note: rows with `status='none'`, no notes, no chips, and `watch=false` are still returned if they exist in the table — but the app only inserts a row on first non-default change, so the result set stays small. `Cache-Control: no-store`.

### `PUT /status/{listing_id}`

Upsert. `X-API-Key` header required. Body is partial — only the fields being updated.

```http
PUT /status/1818978
X-API-Key: <WRITE_API_KEY>
Content-Type: application/json

{"status": "shortlisted", "chips": ["building risk"]}
```

```json
200 OK
{
  "listing_id": "1818978",
  "status": "shortlisted",
  "watch": true,
  "notes": "Saratoga PHC — ...",
  "chips": ["building risk"],
  "updated_at": "2026-05-02T18:14:22Z"
}
```

Implemented as `INSERT ... ON CONFLICT (listing_id) DO UPDATE SET ...` so first-touch and subsequent writes use the same code path. Always returns the full row.

### `POST /status/batch`

Used by the offline outbox flush. `X-API-Key` required. Body is an array of partial updates.

```http
POST /status/batch
X-API-Key: <WRITE_API_KEY>
Content-Type: application/json

[
  {"listing_id": "1818978", "status": "viewing"},
  {"listing_id": "1811080", "watch": true}
]
```

Returns 200 with the updated rows on success; 207 with a per-item status array if some fail. Idempotent — replaying the same batch is safe.

### Auth

A single static `WRITE_API_KEY`, generated by the user (`openssl rand -hex 32`), pasted into:

- Railway → Variables → `WRITE_API_KEY`
- Each device's `localStorage['streethard.api_key']` via the Settings panel

Server-side: read header → `hmac.compare_digest(provided, expected)` → 401 on mismatch. Constant-time compare so we don't leak the key length via timing.

The family is read-only by default. If anyone with the key writes, they all share the same identity — no per-user attribution. That's the deliberate design; we're not building a multi-tenant app.

### CORS

Allow exactly `https://streethard.omarqari.com` (the canonical Pages origin under the custom domain). During the DNS cutover window, also allow `https://omarqari.github.io` so the old URL keeps working until Pages settles. Allow `*` only during local dev. `Access-Control-Allow-Headers: Content-Type, X-API-Key`. Methods: `GET, PUT, POST, OPTIONS`.

Once both devices are confirmed loading the app via `streethard.omarqari.com`, drop the `omarqari.github.io` entry from `ALLOWED_ORIGIN`.

---

## Frontend Integration (Revised — Session 21)

All changes land in `index.html`. No build step, no new files.

### On load

```js
const [listingsRes, statusRes] = await Promise.all([
  fetch('data/latest.json'),
  fetch(`${API_BASE}/status`).catch(() => ({ json: () => ({ items: [] }) }))
]);

const listings = (await listingsRes.json()).listings;
const statusMap = new Map((await statusRes.json()).items.map(s => [s.listing_id, s]));

// Merge status into listings
for (const listing of listings) {
  Object.assign(listing, statusMap.get(listing.id) ?? { bucket: 'inbox' });
}

// Auto-resurrection: archived listings with price drops → inbox
const resurrections = [];
for (const listing of listings) {
  if (listing.bucket === 'archive' && listing.price_at_archive && listing.price < listing.price_at_archive) {
    listing.bucket = 'inbox';
    listing.bucket_changed_at = new Date().toISOString();
    listing._price_dropped = true; // transient badge flag
    resurrections.push({ listing_id: listing.id, bucket: 'inbox', bucket_changed_at: listing.bucket_changed_at });
  }
}
if (resurrections.length > 0) {
  fetch(`${API_BASE}/status/batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-API-Key': getApiKey() },
    body: JSON.stringify(resurrections)
  }).catch(() => {}); // best-effort
}
```

Status fetch failure is non-fatal — listings render in Inbox with no transition buttons (read-only mode).

### Tab navigation

Three tab pills in the filter bar: **Inbox** | **Shortlist** | **Archive**. Active tab read from `location.hash` on load (default: `#inbox`). Hash updates on tab switch. localStorage stores last tab as fallback.

```js
function getActiveTab() {
  const hash = location.hash.replace('#', '');
  return ['inbox', 'shortlist', 'archive'].includes(hash) ? hash : 'inbox';
}
```

### Column set per tab

| Column | Inbox | Shortlist | Archive |
|---|---|---|---|
| Building / Unit | ✓ | ✓ | ✓ |
| Monthly Pmt | ✓ | ✓ | ✓ |
| Ask Price | ✓ | ✓ | ✓ |
| SqFt | ✓ | ✓ | ✓ |
| Beds / Baths | ✓ | ✓ | ✓ |
| OQ # | — | ✓ | — |
| RQ # | — | ✓ | — |
| Type | ✓ | ✓ | ✓ |
| Days Listed | ✓ | ✓ | — |
| Actions | ★ / ↓ | ↓ / ← | ← |

### Transition buttons

Per-row action buttons, contextual to current tab:

- **Inbox**: `★ Shortlist` (blue) + `Archive ↓` (gray)
- **Shortlist**: `Archive ↓` (gray) + `← Inbox` (subtle)
- **Archive**: `← Inbox` (blue)

Each button fires `updateStatus(id, { bucket: newBucket, bucket_changed_at: now, ... })`. Archive transitions also include `price_at_archive: listing.price`.

### Optimistic update helper

```js
async function updateStatus(listingId, patch) {
  const row = listings.find(l => l.id === listingId);
  Object.assign(row, patch, { updated_at: new Date().toISOString() });
  renderCurrentTab(); // re-filter and re-render

  try {
    const res = await fetch(`${API_BASE}/status/${listingId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': getApiKey() },
      body: JSON.stringify(patch)
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch (err) {
    enqueueOutbox(listingId, patch);
  }
}
```

Notes: 1-second debounce on keystrokes. Bucket transitions fire immediately.

### Offline outbox

`localStorage['streethard.outbox']` holds `{listing_id, patch, ts}` entries. Flushed via `POST /status/batch` on `online` / `visibilitychange`. Same as before — handles the elevator/tour scenario.

---

## Deployment Topology

```
GitHub repo (single)
├── /                                ← Pages root (existing)
│   ├── index.html
│   └── data/{db,latest,YYYY-MM-DD}.json
│
└── /api/                            ← Railway Root Directory
    ├── main.py                      ← FastAPI app
    ├── db.py                        ← asyncpg pool
    ├── schema.sql
    ├── requirements.txt
    └── railway.toml
```

Two services, one repo. The cron pipeline (`refresh.yml` → `db.json`) is untouched and orthogonal to the API service.

### Railway

- New project → Deploy from GitHub → **Root Directory: `api`**
- Add Postgres plugin → `DATABASE_URL` injected automatically
- Hobby plan ($5/mo) so the service doesn't sleep — auto-sleep would make the first click after a quiet day visibly laggy
- Custom domain: `api.streethard.omarqari.com` (Settings → Custom Domain → add → Railway prints a CNAME target → user pastes that target into Spaceship's DNS panel as a CNAME record)
- Default `*.up.railway.app` URL stays live as a fallback for curl/dev work
- Healthcheck path: `/health`
- Auto-deploy on push to `main`

### Env vars (Railway)

| Var | Source | Notes |
|---|---|---|
| `DATABASE_URL` | Postgres plugin | Auto-injected |
| `WRITE_API_KEY` | User-generated | `openssl rand -hex 32` |
| `ALLOWED_ORIGIN` | `https://streethard.omarqari.com` | CORS allowlist (canonical app origin) |
| `ALLOWED_ORIGIN_FALLBACK` | `https://omarqari.github.io` | Optional, only set during DNS cutover; remove once `streethard.omarqari.com` is verified live on both devices |

### Local dev

`uvicorn api.main:app --reload` against a local Postgres or a `DATABASE_URL` pointing at the Railway DB. CORS allows `http://localhost:*` when an `ENV=dev` flag is set.

### Backups

Railway snapshots cover v1. The data is small (one row per actively-tracked listing, hundreds at most) and reproducible from the user's memory if the worst case happens. We don't ship a backup script in v1.

---

## Security Posture

- **Reads are public.** The `/status` endpoint exposes notes content. Notes will contain opinions about buildings, agents, and price reasoning. The user accepts that — the URL is unguessable enough for n=1, and the alternative (read auth) doubles the deployment complexity.
- **Writes are key-gated.** Constant-time compare. Single key shared across the family.
- **No PII.** Don't put SSNs, account numbers, or anything sensitive in notes. Mentioning that in onboarding is on the user.
- **HTTPS everywhere.** Railway terminates TLS automatically.
- **Rate limit.** None in v1. Hobby tier resource limits are the de-facto rate limit. Add per-IP limit in v1.5 if abuse ever shows up in logs.
- **Key rotation.** Generate a new key, update Railway env, paste into each device's localStorage. Old key fails 401 on next write — clean cutover.

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Railway service down during a tour | Medium | Optimistic UI + offline outbox makes it invisible most of the time; flush on reconnect |
| User rotates the key but forgets one device | Medium | Settings → Test Connection makes the broken-key state obvious; clear error message |
| Two devices write the same field within seconds | Low | Last-write-wins by `updated_at`. Acceptable for n=1; the family has chat for coordination |
| Postgres plugin hits free-tier ceiling | Very low | The data is tiny. Hobby tier is well within limits. |
| `/status` exposed publicly to scrapers | Low | URL is unguessable; data is opinions about real estate, not credentials. |
| Listings disappear from `db.json` (delisting) but `listing_status` row persists | Expected | The merge in the browser tolerates orphan status rows by ignoring them. They re-attach if the listing returns. |
| User loses interest in maintaining $5/mo Hobby tier post-purchase | Real, by design | Once the apartment is bought, the data can be exported and the Railway service archived. |

---

## 30-Minute Starter Snippet

For day-one of build. Not production-ready — minimal smoke-test scaffolding.

```python
# api/main.py
import os, hmac
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import asyncpg

DATABASE_URL = os.environ["DATABASE_URL"]
WRITE_API_KEY = os.environ["WRITE_API_KEY"]
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "https://streethard.omarqari.com")
ALLOWED_ORIGIN_FALLBACK = os.environ.get("ALLOWED_ORIGIN_FALLBACK")
ALLOWED_ORIGINS = [o for o in (ALLOWED_ORIGIN, ALLOWED_ORIGIN_FALLBACK) if o]

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "PUT", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)

pool: asyncpg.Pool | None = None

@app.on_event("startup")
async def startup():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=4)
    with open("schema.sql") as f:
        async with pool.acquire() as conn:
            await conn.execute(f.read())

def require_key(provided: str | None):
    if not provided or not hmac.compare_digest(provided, WRITE_API_KEY):
        raise HTTPException(status_code=401, detail="invalid api key")

@app.get("/health")
async def health():
    async with pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"ok": True, "db": "connected"}

@app.get("/status")
async def get_status():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM listing_status")
    return {"items": [dict(r) for r in rows]}

@app.put("/status/{listing_id}")
async def put_status(listing_id: str, patch: dict, x_api_key: str | None = Header(default=None)):
    require_key(x_api_key)
    # Upsert with COALESCE so partial patches preserve unchanged fields.
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO listing_status (listing_id, status, watch, notes, chips)
            VALUES ($1,
                    COALESCE($2, 'none'),
                    COALESCE($3, FALSE),
                    COALESCE($4, ''),
                    COALESCE($5, '[]'::jsonb))
            ON CONFLICT (listing_id) DO UPDATE SET
                status     = COALESCE($2, listing_status.status),
                watch      = COALESCE($3, listing_status.watch),
                notes      = COALESCE($4, listing_status.notes),
                chips      = COALESCE($5, listing_status.chips),
                updated_at = NOW()
            RETURNING *
        """,
            listing_id,
            patch.get("status"),
            patch.get("watch"),
            patch.get("notes"),
            patch.get("chips"),
        )
    return dict(row)
```

Smoke test:

```bash
# Use the *.up.railway.app URL until the custom-domain CNAME on Spaceship
# resolves; then switch to api.streethard.omarqari.com.
curl https://api.streethard.omarqari.com/health
curl https://api.streethard.omarqari.com/status
curl -X PUT https://api.streethard.omarqari.com/status/1818978 \
  -H "X-API-Key: $WRITE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status":"shortlisted"}'
```

When all three return 200 with sensible JSON, the backend is done. Move to the frontend.

---

## v1 / v1.1 / v1.5 / v2

**v1 — ship it.** Three-bucket triage (Inbox/Shortlist/Archive), tab navigation with URL hash, transition buttons, auto-resurrection on price drops, OQ/RQ rankings (Shortlist-only, server-enforced clearing), notes, Settings panel, optimistic UI, offline outbox. Acceptance criteria below.

**v1.1 — triage speed.** Bulk archive (checkboxes + toolbar). Keyboard shortcut `e` to archive. Chips on Shortlist items.

**v1.5 — niceties.** Service Worker + IndexedDB for closed-tab offline. Per-IP rate limit. Export-to-CSV of shortlisted listings.

**v2 — only if needed.** Per-user identity (multi-key, attribution). Status history / audit trail. Push notifications. None needed for n=1.

---

## Deferred Design Ideas

### Status history / audit trail (v2)

The schema is last-write-wins. A second table (`listing_status_history(listing_id, bucket, changed_at)`) appended on every write would give a free audit log. Cost is ~$0/mo at this volume; worth adding if "wait, why did we archive this?" becomes a real question after a few months.

### Structured tour metadata (v2)

Notes textarea is the only place tour info lives. If structure-vs-free-text becomes painful after ~10 tours, add columns: `toured_at`, `tour_attendees JSONB`, `follow_up_at`, `private_max_offer NUMERIC`.

### "Recently delisted (you tracked these)" surface (v1.5)

Orphan `listing_status` rows persist when a listing leaves `db.json`. A collapsible "Recently delisted that you shortlisted" section would make "what passed us by" visible. Requires the merge step to surface orphan rows rather than dropping them.

### Bulk archive (v1.1)

When 40 new listings land from a cron run, archiving one-by-one is tedious. Gmail solves this with checkboxes + toolbar button. Row markup in v1 includes a hidden checkbox hook for this.

---

## v1 Acceptance Criteria

1. **Cross-device sync.** Shortlist a listing on iPhone. Refresh laptop. Same listing in Shortlist tab.
2. **Persistence across deploys.** Push a deploy. Shortlisted listing still in Shortlist tab.
3. **Archive removes from Inbox.** Archive a listing. Disappears from Inbox, appears in Archive tab.
4. **OQ/RQ cleared on exit.** Rank a shortlisted listing OQ#1. Archive it. Unarchive → Shortlist again. OQ# is empty.
5. **Auto-resurrection.** Archive at $3M. Simulate price drop to $2.8M. Reload. Listing in Inbox with "Price dropped" badge.
6. **Offline tour.** Phone in airplane mode → shortlist → airplane off. Change syncs within ~3 seconds.
7. **Bad key fails clearly.** Wrong key → Test Connection shows red error. Writes blocked.
8. **Read without key.** Clean browser, no key. Listings render in Inbox. Transition buttons hidden/disabled.
9. **Cron untouched.** `refresh.yml` run completes; bucket assignments unchanged.
10. **New listings land in Inbox.** Run cron. New listings appear in Inbox, not Shortlist or Archive.

When all ten pass on a real iPhone + laptop pair, v1 is done.
