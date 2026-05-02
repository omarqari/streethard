# STATUS-BACKEND-WALKTHROUGH — CTO Build Guide

Companion to `STATUS-FEATURE.md` (the design spec). This doc captures the
language-pick rationale, file layout, phasing, and concrete code snippets
decided in Session 14 (2026-05-02 evening) once the user signed off on
the open architectural questions from Session 13.

`STATUS-FEATURE.md` answers *what* and *why*. This doc answers *how to
build it next*.

---

## A. Stack & language pick

GitHub API check: `https://api.github.com/users/omarqari/repos?per_page=100`
returned a single public repo — `streethard` itself, language Python.
The repos `insightcubed` and `OmarGPT` are not public under the `omarqari`
handle (404). No external signal to pull from.

**Pick: FastAPI on Python 3.12.** Stack continuity with `pull.py` is the
deciding factor. One language, one mental model, one set of debugging
muscles. Pydantic v2 gives us request/response validation for free.

Stack: **FastAPI + Uvicorn + asyncpg + Pydantic v2 + Railway managed
Postgres**. No ORM — Postgres has one table; raw SQL with asyncpg is
shorter and faster than SQLAlchemy and we will never regret it at this
scale.

Rejected: Fastify/Node — modestly faster cold starts, neither matters at
n=1, and would split the project's mental model in half.

---

## B. Service shape

One Railway web service, one Postgres add-on, zero workers, zero cron.
Cron stays on GitHub Actions writing `data/db.json`. The API never
touches `db.json`; it only owns status.

Layout under the existing repo:

```
streethard/
├── index.html                 # unchanged
├── data/db.json               # unchanged, bot-written
├── scripts/pull.py            # unchanged
├── .github/workflows/refresh.yml
└── api/                       # NEW — Railway Root Directory
    ├── main.py                # FastAPI app, all routes
    ├── db.py                  # asyncpg pool + query helpers
    ├── auth.py                # API key middleware
    ├── schema.sql             # one-shot DDL, run on startup
    ├── requirements.txt       # fastapi, uvicorn[standard], asyncpg, pydantic
    ├── Procfile               # web: uvicorn main:app --host 0.0.0.0 --port $PORT
    └── railway.toml           # optional; pins build/start commands
```

Total expected size: ~250 lines of Python.

---

## C. Database schema (one table, final)

```sql
CREATE TABLE IF NOT EXISTS listing_status (
    listing_id     TEXT PRIMARY KEY,
    status         TEXT NOT NULL DEFAULT 'none'
                    CHECK (status IN ('none','watching','viewing','shortlisted','rejected','offered')),
    watch          BOOLEAN NOT NULL DEFAULT FALSE,
    notes          TEXT NOT NULL DEFAULT '',
    chips          JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_listing_status_updated
    ON listing_status (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_listing_status_status
    ON listing_status (status)
    WHERE status <> 'none';
```

Rationale:
- TEXT + CHECK over Postgres ENUM — easier to extend without a migration framework.
- `chips` as JSONB — add new tags without ALTER TABLE.
- Partial index on `status <> 'none'` — skips the inevitable mountain of default rows.
- `updated_at` set by the app on write (`SET updated_at = NOW()`); no DB trigger.
- **No `updated_by` column.** Per Session 14 user decision: shared write key, no per-user attribution.

---

## D. API surface

```
GET  /health                   → {ok: true, db: "up"}            public
GET  /status                   → [{listing_id, status, watch, notes, chips, updated_at}, ...]   public
PUT  /status/{listing_id}      → upsert one row, returns the row    key-gated
POST /status/batch             → upsert N rows (offline queue flush) key-gated
```

Auth middleware (`auth.py`):

```python
import hmac
from fastapi import Header, HTTPException
from .config import settings

async def require_write_key(x_api_key: str | None = Header(None)):
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.WRITE_API_KEY):
        raise HTTPException(401, "bad or missing X-API-Key")
```

`hmac.compare_digest` is constant-time — prevents the timing-oracle
class of attack even though it's unlikely at n=1.

`PUT /status/{id}` body: `{status?, watch?, notes?, chips?}` — partial
update via `COALESCE(EXCLUDED.x, listing_status.x)` in the upsert.
`POST /status/batch` body: `{items: [{listing_id, status?, watch?, notes?, chips?}]}`
— wrap in a single transaction.

Don't paginate `GET /status`. ~500 listings × tiny rows ≈ 30 KB JSON.
Set `Cache-Control: no-store` so the merge always sees fresh data.

---

## E. Frontend integration (concrete touch points in `index.html`)

Three surgical changes, all client-side JS:

1. **Extend `loadData()`.** Today it does `fetch('data/latest.json')`.
   Make it `Promise.all([fetch('data/latest.json'), fetch(API_BASE + '/status')])`,
   then build a `Map<listing_id, status>` and merge:
   `listings = listings.map(l => ({...l, ...statusMap.get(l.id) ?? defaults}))`.
   If the status fetch rejects, fall back to defaults and show a small
   "status offline" indicator — the app stays useful.

2. **Optimistic write helper.** New `setStatus(listingId, patch)`:
   mutate the in-memory listing immediately, re-render the affected row,
   then `fetch(API_BASE + '/status/' + id, {method: 'PUT', headers: {'X-API-Key': localStorage.streethard_key, 'Content-Type': 'application/json'}, body: JSON.stringify(patch)})`.
   On failure, push to an `outboxQueue` array in `localStorage` and
   surface a tiny "1 unsaved" pill. No rollback — single-writer family
   means optimistic-then-retry is fine.

3. **Queue flush.** On load and on `window.online` event, drain
   `outboxQueue` via `POST /status/batch`. ~40 lines.

The status pill, notes editor, and chip selector live inside the
existing row-expansion section that already renders Price History —
extend that block, don't fight the layout.

---

## F. Deployment topology

Railway: New Project → Deploy from GitHub repo `omarqari/streethard` →
set **Root Directory: `api/`** → add **Postgres** plugin (one click,
provisions `DATABASE_URL` automatically). Push to `main` triggers a build.

**Cron is unaffected.** `refresh.yml` commits to the repo; GitHub Pages
rebuilds; Railway never sees it. Two deploy paths, two rates of change,
zero coupling.

**Custom domains (Session 16 decision).** The project is moving off the
default `*.github.io` and `*.up.railway.app` URLs onto user-owned
subdomains:

- `streethard.omarqari.com` → CNAME → `omarqari.github.io` (the static app)
- `api.streethard.omarqari.com` → CNAME → the Railway API service

Steps the user owns (~5 min in three dashboards):

1. **Spaceship DNS panel** — add two CNAME records pointing to the
   targets above. GitHub's CNAME target is literally `omarqari.github.io`.
   Railway prints its CNAME target on the Custom Domain page; paste that
   value verbatim.
2. **GitHub Pages** — repo → Settings → Pages → Custom domain →
   `streethard.omarqari.com`. This writes a `CNAME` file to the repo
   root. Wait for the green "DNS check successful" before moving on.
3. **Railway** — project → API service → Settings → Custom Domain →
   `api.streethard.omarqari.com`. Railway auto-issues a TLS cert once
   the CNAME resolves.

The default `streethard-api-production.up.railway.app` and
`omarqari.github.io/streethard` URLs remain live as fallbacks during
propagation.

Env vars on the Railway service:
- `DATABASE_URL` — auto-injected when Postgres is attached
- `WRITE_API_KEY` — generated locally (see G)
- `ALLOWED_ORIGIN` — `https://streethard.omarqari.com` (canonical)
- `ALLOWED_ORIGIN_FALLBACK` — `https://omarqari.github.io` (set during
  cutover only; remove once the custom domain is verified live on both
  devices)

---

## G. Env vars & secrets

Generate `WRITE_API_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# or
openssl rand -hex 32
```

Paste once into Railway's Variables tab — never commit. On laptop and
phone, open StreetHard, hit the Settings panel, paste:
`localStorage.setItem('streethard_key', '...')`. Two devices, two paste
operations.

Local `.env` for dev mirrors the Railway vars; existing `.gitignore`
already covers `.env`.

---

## H. Migrations

For one table: **`schema.sql` checked in + run at startup.**

```python
@app.on_event("startup")
async def init_db():
    async with pool.acquire() as conn:
        await conn.execute(open("schema.sql").read())
```

DDL uses `CREATE … IF NOT EXISTS`, so idempotent on every cold start.
No Alembic, no Prisma. Adding a column later means appending
`ALTER TABLE … ADD COLUMN IF NOT EXISTS …` to `schema.sql` and
shipping. Trigger to switch to Alembic: ≥3 tables or a non-trivial
backfill.

---

## I. CORS & security posture

```python
allowed = [o for o in (settings.ALLOWED_ORIGIN, settings.ALLOWED_ORIGIN_FALLBACK) if o]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed,
    allow_methods=["GET", "PUT", "POST", "OPTIONS"],
    allow_headers=["X-API-Key", "Content-Type"],
)
```

`ALLOWED_ORIGIN` is `https://streethard.omarqari.com` (canonical).
`ALLOWED_ORIGIN_FALLBACK` is optional and set only during the DNS
cutover to `https://omarqari.github.io` so the old URL keeps working
while propagation completes. Drop it from Railway env vars once both
devices are confirmed loading the app from the custom domain.

**Do not** use `allow_origins=["*"]` — even with key auth, narrow it to
the canonical app origin so a leaked key from a stranger's tab can't
pound the endpoint.

- `401` = missing or wrong key.
- `403` is not used (no role distinctions).
- No rate limiter at v1 — two writers. If ever abused, slap Railway's
  per-service request cap on it.

---

## J. Observability

Railway provides out of the box: live log stream, deploy history,
CPU/RAM graphs, crash auto-restart. **That is enough for v1.** Skip
Sentry / OpenTelemetry / structured logging libraries. `print()` plus
Railway's log tail is faster to debug than a JSON wall. Revisit if a
real bug ever proves un-reproducible from logs.

---

## K. Local dev

Run locally with `uvicorn main:app --reload` against a local Postgres
(`brew install postgresql@16` or `docker run postgres:16`). Worth the
setup — Railway round-trip is 30–60s per push vs. instant locally.
Skip docker-compose; native Postgres is simpler.

For end-to-end testing from the phone, use **Railway Preview
Environments** (auto-spun on PRs, free on Hobby tier) — gives a real
cloud URL without merging.

---

## L. Backup posture

`pg_dump` = Postgres's "export the whole DB to a SQL file" tool. You'd
run it on a schedule and stash the file in S3 or a private gist.
Railway's managed Postgres takes daily snapshots automatically.

**Per Session 14 user decision: skip extra backup work for v1.**

Trigger to revisit: when the dataset represents irreplaceable input
(e.g., months of detailed apartment notes that would hurt to lose),
add a weekly `pg_dump` to S3.

---

## M. Phasing & order of build

Each step is independently shippable. See `TASKS.md` for the checkbox
list — this is the narrative justification for the order.

1. **Skeleton + `/health`.** Validates the deploy path before any
   business logic. ~30 min.
2. **Schema + write endpoints + key auth.** Test with `curl`. ~1 hr.
3. **Settings panel + Test Connection.** Catches "did I paste the key
   right" before any data touches anything. ~30 min.
4. **Status pill + optimistic write.** ~1 hr.
5. **Notes + chips editor.** ~1 hr.
6. **Offline queue.** ~30 min.

Total: a focused weekend.

---

## N. Risks & failure modes (specific, not generic)

| Risk | Mitigation |
|---|---|
| **Hobby-tier sleeping.** Free tier sleeps idle services. Status fetch takes 5–10s while dyno wakes. | Pay $5/mo Hobby plan (the price of one bagel). |
| **Postgres connection limits.** Starter Postgres ≈ 20 connections. asyncpg pool default is 10. | Cap pool at `max_size=5` so a runaway test script can't lock out the live app. |
| **CORS preflight subtlety.** Custom `X-API-Key` header triggers OPTIONS preflight. | `allow_headers` must include `X-API-Key` (case matters in some browsers). |
| **Mobile Safari & `localStorage`.** Private browsing wipes it; iOS 17 evicts site data after 7 days unused. Key vanishes silently. | Settings panel needs a "key not set" empty state, not a crash. |
| **Pages cache.** GitHub Pages aggressively caches `index.html` for ~10 min. | After frontend deploys, add a `?v=N` cachebuster on the status fetch URL. |
| **`db.json` ID drift.** `id` vs `listing_id` field-name mismatch = silent data loss. | Pick one canonical field name, assert on load. |
| **GitHub Actions secret leak.** `WRITE_API_KEY` should NOT live in GitHub Secrets — cron doesn't write status. | Keep it Railway-only to shrink blast radius. |

---

## O. The 30-minute starter

Create `api/main.py`, `api/requirements.txt`, `api/Procfile`. Push.
Connect Railway to the repo, set Root Directory to `api/`, deploy.
Hit `/health` from the laptop. **Stop there for tonight.** Don't write
business logic until that round trip works — every subsequent step is
then one small change inside a known-working deploy loop.

```python
# api/main.py — the 30-minute version
from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True}
```

```
# api/requirements.txt
fastapi==0.115.0
uvicorn[standard]==0.32.0
```

```
# api/Procfile
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

Ship that. Everything else is incremental on a working deploy.
