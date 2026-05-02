"""StreetHard Status API — FastAPI + asyncpg + Railway Postgres."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from db import pool_startup, pool_shutdown, get_pool


# --- Config ---

WRITE_API_KEY = os.environ.get("WRITE_API_KEY", "")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "https://streethard.omarqari.com")
ALLOWED_ORIGIN_FALLBACK = os.environ.get("ALLOWED_ORIGIN_FALLBACK", "")


# --- Auth dependency ---

async def require_write_key(x_api_key: str | None = Header(None)):
    import hmac
    if not x_api_key or not WRITE_API_KEY or not hmac.compare_digest(x_api_key, WRITE_API_KEY):
        raise HTTPException(status_code=401, detail="bad or missing X-API-Key")


# --- Pydantic models ---

class StatusPatch(BaseModel):
    status: str | None = None
    watch: bool | None = None
    oq_notes: str | None = None
    rq_notes: str | None = None
    oq_rank: int | None = None
    rq_rank: int | None = None
    chips: list[str] | None = None


class BatchItem(BaseModel):
    listing_id: str
    status: str | None = None
    watch: bool | None = None
    oq_notes: str | None = None
    rq_notes: str | None = None
    oq_rank: int | None = None
    rq_rank: int | None = None
    chips: list[str] | None = None


class BatchRequest(BaseModel):
    items: list[BatchItem] = Field(..., max_length=200)


# --- App lifecycle ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool_startup()
    # Run schema migration
    pool = get_pool()
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    async with pool.acquire() as conn:
        with open(schema_path) as f:
            await conn.execute(f.read())
    yield
    await pool_shutdown()


app = FastAPI(title="StreetHard Status API", lifespan=lifespan)

# --- CORS ---

allowed_origins = [o for o in (ALLOWED_ORIGIN, ALLOWED_ORIGIN_FALLBACK) if o]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "PUT", "POST", "OPTIONS"],
    allow_headers=["X-API-Key", "Content-Type"],
)


# --- Helpers ---

UPSERT_SQL = """
    INSERT INTO listing_status
        (listing_id, status, watch, oq_notes, rq_notes, oq_rank, rq_rank, chips, updated_at)
    VALUES ($1,
            COALESCE($2, 'none'),
            COALESCE($3, FALSE),
            COALESCE($4, ''),
            COALESCE($5, ''),
            $6,
            $7,
            COALESCE($8::jsonb, '[]'::jsonb),
            NOW())
    ON CONFLICT (listing_id) DO UPDATE SET
        status     = COALESCE($2, listing_status.status),
        watch      = COALESCE($3, listing_status.watch),
        oq_notes   = COALESCE($4, listing_status.oq_notes),
        rq_notes   = COALESCE($5, listing_status.rq_notes),
        oq_rank    = CASE WHEN $6 IS NOT NULL THEN $6 ELSE listing_status.oq_rank END,
        rq_rank    = CASE WHEN $7 IS NOT NULL THEN $7 ELSE listing_status.rq_rank END,
        chips      = COALESCE($8::jsonb, listing_status.chips),
        updated_at = NOW()
    RETURNING listing_id, status, watch, oq_notes, rq_notes, oq_rank, rq_rank, chips, updated_at
"""

SELECT_ALL_SQL = """
    SELECT listing_id, status, watch, oq_notes, rq_notes, oq_rank, rq_rank, chips, updated_at
    FROM listing_status ORDER BY updated_at DESC
"""


def row_to_dict(r):
    return {
        "listing_id": r["listing_id"],
        "status": r["status"],
        "watch": r["watch"],
        "oq_notes": r["oq_notes"],
        "rq_notes": r["rq_notes"],
        "oq_rank": r["oq_rank"],
        "rq_rank": r["rq_rank"],
        "chips": r["chips"],
        "updated_at": r["updated_at"].isoformat(),
    }


# --- Routes ---

@app.get("/health")
async def health():
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"ok": True, "db": "connected"}
    except Exception as e:
        return Response(
            content=f'{{"ok": false, "db": "error", "detail": "{str(e)}"}}',
            status_code=503,
            media_type="application/json",
        )


@app.get("/status")
async def get_all_status(response: Response):
    response.headers["Cache-Control"] = "no-store"
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(SELECT_ALL_SQL)
    return {"items": [row_to_dict(r) for r in rows]}


@app.put("/status/{listing_id}", dependencies=[Depends(require_write_key)])
async def put_status(listing_id: str, patch: StatusPatch):
    pool = get_pool()
    import json
    chips_json = json.dumps(patch.chips) if patch.chips is not None else None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            UPSERT_SQL,
            listing_id,
            patch.status,
            patch.watch,
            patch.oq_notes,
            patch.rq_notes,
            patch.oq_rank,
            patch.rq_rank,
            chips_json,
        )

    return row_to_dict(row)


@app.post("/status/batch", dependencies=[Depends(require_write_key)])
async def post_batch(body: BatchRequest):
    pool = get_pool()
    import json
    results = []
    errors = []

    async with pool.acquire() as conn:
        async with conn.transaction():
            for item in body.items:
                chips_json = json.dumps(item.chips) if item.chips is not None else None
                try:
                    row = await conn.fetchrow(
                        UPSERT_SQL,
                        item.listing_id,
                        item.status,
                        item.watch,
                        item.oq_notes,
                        item.rq_notes,
                        item.oq_rank,
                        item.rq_rank,
                        chips_json,
                    )
                    results.append(row_to_dict(row))
                except Exception as e:
                    errors.append({"listing_id": item.listing_id, "error": str(e)})

    if errors:
        return Response(
            content=json.dumps({"items": results, "errors": errors}),
            status_code=207,
            media_type="application/json",
        )
    return {"items": results}
