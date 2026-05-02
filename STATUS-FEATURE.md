# STATUS-FEATURE — Listing Status Tracking

Design spec for the in-app status tracking feature. PROJECTPLAN.md has the executive summary; TASKS.md has the to-do; this is the source of truth for the build.

---

## Problem

StreetHard is read-only today. Family members browse the same 419 listings with no way to mark "I've already toured this," "we've vetoed this co-op for the lobby," or "this is the one we're offering on." The buyer's mental model and the app's data model don't meet.

The shopping process is intrinsically stateful — a candidate moves through *seen → toured → shortlisted → offered → won/lost*. We need that state in the app, shared across two devices (laptop + phone), persistent across deploys, and editable by anyone in the family who has the key.

---

## Buyer's Mental Model

The user's natural workflow on a tour day:

1. Open StreetHard on the phone in the elevator before a showing.
2. Mark a listing **Viewing** when arriving; type a quick note in the expanded row ("doorman seemed checked-out, lobby smelled of cigarettes").
3. After the tour, either bump to **Shortlisted** or drop to **Rejected**.
4. Tap a deal-breaker chip (`no light`, `bad layout`, `building risk`, `priced too high`, `noise`, `condition`) so a one-glance reason persists for "why was this rejected?"
5. Back on the laptop that evening, all of the above is already there.

A separate dimension: **watch**. Sometimes a listing is rejected on price but the user wants to be told if it ever drops. Watch is orthogonal to status — a Rejected-but-watched listing should re-surface (UI badge or a saved filter) when its price changes.

No kanban view. The buyer doesn't think in columns; they think one-listing-at-a-time inside the existing table they already use.

---

## State Model

### Status (one of)

| Status | Meaning | Typical lifecycle |
|---|---|---|
| `none` | Default. No interaction yet. | Implicit; not stored. |
| `watching` | Interesting, want to keep an eye on it. Not yet seen in person. | none → watching |
| `viewing` | Tour scheduled or just finished. | watching → viewing |
| `shortlisted` | Serious candidate. Offering plan / due diligence stage. | viewing → shortlisted |
| `rejected` | Vetoed. Reasons captured in chips/notes. | any → rejected |
| `offered` | Offer submitted. | shortlisted → offered |

Final names are open until the user signs off — see PROJECTPLAN "Open Questions." The shape (six values, one default) is locked.

### Watch (orthogonal boolean)

`watch: true` means "re-surface this listing when its price changes," regardless of status. Implemented as a bookmark icon next to the status pill. Rejecting a listing does **not** clear `watch` — the two are independent.

### Notes (free text)

A textarea in the expanded row. No length limit enforced server-side; the app should soft-cap at ~2,000 chars in the UI. One field per listing. Last-write-wins (no per-paragraph attribution; we don't have per-user identity).

### Chips (structured deal-breakers)

A fixed vocabulary of multi-select chips: `no light`, `bad layout`, `building risk`, `priced too high`, `noise`, `condition`, `bad block`, `flip tax`, `board risk`. Stored as a JSON array. Designed to make "why did we kill this?" answerable in one glance two months later.

The chip vocabulary is small and curated on purpose — free-text "tags" devolve into the same idea spelled three different ways. We pick the list; the user picks from it.

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

## Schema

One table. One PK. One JSONB column for the chip array. No migrations framework; the SQL is idempotent and runs at FastAPI startup.

```sql
-- api/schema.sql
CREATE TABLE IF NOT EXISTS listing_status (
    listing_id   TEXT      PRIMARY KEY,
    status       TEXT      NOT NULL DEFAULT 'none'
                           CHECK (status IN ('none','watching','viewing','shortlisted','rejected','offered')),
    watch        BOOLEAN   NOT NULL DEFAULT FALSE,
    notes        TEXT      NOT NULL DEFAULT '',
    chips        JSONB     NOT NULL DEFAULT '[]'::jsonb,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS listing_status_updated_at_idx
    ON listing_status (updated_at DESC);

-- Most rows will have status='none' once we add bulk listings.
-- Partial index keeps the "show me only marked listings" query fast.
CREATE INDEX IF NOT EXISTS listing_status_active_idx
    ON listing_status (status)
    WHERE status <> 'none';
```

### Notes on the schema

- `listing_id` matches the StreetEasy ID we already use as the key in `db.json`. No FK — `listing_status` survives independently of `db.json` revisions, which is what we want when a listing temporarily disappears from a Pass 1 search.
- `status` is TEXT + CHECK rather than a Postgres ENUM. Adding a value to an ENUM requires a migration; adding to a CHECK is a one-line idempotent `ALTER TABLE ... DROP CONSTRAINT ...; ADD CONSTRAINT ...` that fits our no-Alembic posture.
- `chips` JSONB rather than a join table — we never query "all listings with chip X" server-side. The app filters in the browser. JSONB is the right primitive for "opaque blob the client owns."
- `updated_at` is server-set on insert and on every write. Used for cache busting on the client and as a tie-breaker if we ever add per-device queues.

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

## Frontend Integration

All changes land in `index.html`. No build step, no new files.

### On load

```js
const [listingsRes, statusRes] = await Promise.all([
  fetch('data/latest.json'),
  fetch(`${API_BASE}/status`).catch(() => ({ json: () => ({ items: [] }) }))
]);

const listings = (await listingsRes.json()).listings;
const statusMap = new Map((await statusRes.json()).items.map(s => [s.listing_id, s]));

for (const listing of listings) {
  Object.assign(listing, statusMap.get(listing.id) ?? defaultStatus());
}
```

Status fetch failure is non-fatal — the app continues with default-status overlays. Family member without the API key, or Railway briefly down, doesn't degrade the read experience.

### Where the UI changes go

| Change | Location in `index.html` |
|---|---|
| Status pill (column 1) | New leading cell in the table row template; `data-status="..."` for CSS coloring |
| Watch bookmark icon | Inside the same column-1 cell, after the pill |
| Expanded-row notes editor | Append to the existing expansion content alongside Price History / Agent / Payment Breakdown |
| Chip selector | Same expansion block, above the notes textarea |
| Settings panel | New gear icon top-right of header → opens a modal with API key input and Test Connection button |
| Filter — "Show only my Shortlisted" | New chip in the existing filter bar |
| Filter — "Hide Rejected" | Same; on by default once any listing is rejected |

### Status pill cycle

Tapping the pill cycles forward: `none → watching → viewing → shortlisted → rejected → offered → none`. Long-press / right-click opens a menu to jump directly to any status. Rejecting prompts for chips before committing the change — a one-tap "rejected" without a reason is a regret waiting to happen.

### Optimistic update helper

```js
async function updateStatus(listingId, patch) {
  // 1. Mutate in-memory, re-render row immediately.
  const row = listings.find(l => l.id === listingId);
  Object.assign(row, patch, { updated_at: new Date().toISOString() });
  renderRow(row);

  // 2. PUT to server. On failure, queue for offline flush, leave UI as-is.
  try {
    const res = await fetch(`${API_BASE}/status/${listingId}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': localStorage.getItem('streethard.api_key') ?? ''
      },
      body: JSON.stringify(patch)
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch (err) {
    enqueueOutbox(listingId, patch);
  }
}
```

Notes get a 1-second debounce on keystrokes (only the notes field; status / watch / chips fire immediately). Single-row PUTs only — no commit-flooding problem because Railway is the source of truth, not git.

### Offline outbox (phone on tour)

`localStorage['streethard.outbox']` holds an array of `{listing_id, patch, ts}` entries. Flushed via `POST /status/batch` on:

- `window.addEventListener('online', flushOutbox)`
- `document.addEventListener('visibilitychange', () => { if (!document.hidden) flushOutbox() })`

This handles the realistic case: in an elevator, no signal, mark a listing Viewing, signal returns, queue flushes silently. Closed-tab-while-offline (Service Worker + IndexedDB) is deferred to v1.5 — the tour-day case doesn't need it.

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

## v1 / v1.5 / v2

**v1 — ship it.** Six statuses, watch flag, notes, chips, Settings panel with API key + Test Connection, optimistic UI, offline outbox via `online` / `visibilitychange`. Cycle pill and bookmark in column 1. Inline filters for "show only Shortlisted" and "hide Rejected." Acceptance criteria below.

**v1.5 — niceties.** Service Worker + IndexedDB so the app keeps working in a closed tab while offline. Per-IP rate limit on writes. Export-to-CSV of marked listings. Watch-triggered visual diff ("price dropped 5% on a watched listing").

**v2 — only if needed.** Per-user identity (multi-key, attribution on notes). Push notification when a watched listing's price changes. None of this is needed for n=1.

---

## v1 Acceptance Criteria

1. **Cross-device sync.** Mark a listing Shortlisted on the iPhone. Open the laptop. After hard refresh, the same listing shows Shortlisted.
2. **Persistence across deploys.** Push a deploy to GitHub Pages. The Shortlisted listing is still Shortlisted.
3. **Watch is independent.** Reject a watched listing. The bookmark icon stays. The listing still surfaces under any "watched" filter.
4. **Offline tour.** Phone in airplane mode. Mark a listing Viewing. Type a note. Toggle airplane mode off. Within ~3 seconds, the change is on the laptop after refresh.
5. **Bad key fails clearly.** Wrong key in Settings → Test Connection shows a red error inside the modal. Writes from that device are blocked with a non-silent toast.
6. **Read without key.** Open the app in a clean browser with no key. Statuses still show; status pill is read-only with a tooltip explaining how to add the key.
7. **Cron untouched.** A `refresh.yml` run completes; statuses are unchanged afterward.

When all seven pass on a real iPhone + laptop pair, v1 is done.
