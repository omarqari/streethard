"""StreetHard Status API — FastAPI + asyncpg + Railway Postgres.

Three-bucket triage system: inbox / shortlist / archive.
OQ/RQ rankings cleared server-side on exit from shortlist.
"""

import os
import json
import hmac
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
    if not x_api_key or not WRITE_API_KEY or not hmac.compare_digest(x_api_key, WRITE_API_KEY):
        raise HTTPException(status_code=401, detail="bad or missing X-API-Key")


# --- Pydantic models ---

class StatusPatch(BaseModel):
    bucket: str | None = None
    bucket_changed_at: str | None = None
    price_at_archive: int | None = None
    oq_notes: str | None = None
    rq_notes: str | None = None
    oq_rank: int | None = None
    rq_rank: int | None = None
    chips: list[str] | None = None


class BatchItem(BaseModel):
    listing_id: str
    bucket: str | None = None
    bucket_changed_at: str | None = None
    price_at_archive: int | None = None
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
    try:
        async with pool.acquire() as conn:
            with open(schema_path) as f:
                await conn.execute(f.read())
        print("Schema migration completed successfully")
    except Exception as e:
        print(f"Schema migration error (non-fatal): {e}")
        # Log but don't crash — allows the service to start so we can debug
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
        (listing_id, bucket, bucket_changed_at, price_at_archive,
         oq_notes, rq_notes, oq_rank, rq_rank, chips, updated_at)
    VALUES ($1,
            COALESCE($2, 'inbox'),
            $3,
            $4,
            COALESCE($5, ''),
            COALESCE($6, ''),
            $7,
            $8,
            COALESCE($9::jsonb, '[]'::jsonb),
            NOW())
    ON CONFLICT (listing_id) DO UPDATE SET
        bucket            = COALESCE($2, listing_status.bucket),
        bucket_changed_at = COALESCE($3, listing_status.bucket_changed_at),
        price_at_archive  = CASE WHEN $4 IS NOT NULL THEN $4 ELSE listing_status.price_at_archive END,
        oq_notes          = COALESCE($5, listing_status.oq_notes),
        rq_notes          = COALESCE($6, listing_status.rq_notes),
        oq_rank           = CASE WHEN $7 IS NOT NULL THEN $7 ELSE listing_status.oq_rank END,
        rq_rank           = CASE WHEN $8 IS NOT NULL THEN $8 ELSE listing_status.rq_rank END,
        chips             = COALESCE($9::jsonb, listing_status.chips),
        updated_at        = NOW()
    RETURNING listing_id, bucket, bucket_changed_at, price_at_archive,
              oq_notes, rq_notes, oq_rank, rq_rank, chips, updated_at
"""

# When transitioning OUT of shortlist, clear rankings
UPSERT_WITH_RANK_CLEAR_SQL = """
    INSERT INTO listing_status
        (listing_id, bucket, bucket_changed_at, price_at_archive,
         oq_notes, rq_notes, oq_rank, rq_rank, chips, updated_at)
    VALUES ($1,
            COALESCE($2, 'inbox'),
            $3,
            $4,
            COALESCE($5, ''),
            COALESCE($6, ''),
            NULL,
            NULL,
            COALESCE($9::jsonb, '[]'::jsonb),
            NOW())
    ON CONFLICT (listing_id) DO UPDATE SET
        bucket            = COALESCE($2, listing_status.bucket),
        bucket_changed_at = COALESCE($3, listing_status.bucket_changed_at),
        price_at_archive  = CASE WHEN $4 IS NOT NULL THEN $4 ELSE listing_status.price_at_archive END,
        oq_notes          = COALESCE($5, listing_status.oq_notes),
        rq_notes          = COALESCE($6, listing_status.rq_notes),
        oq_rank           = NULL,
        rq_rank           = NULL,
        chips             = COALESCE($9::jsonb, listing_status.chips),
        updated_at        = NOW()
    RETURNING listing_id, bucket, bucket_changed_at, price_at_archive,
              oq_notes, rq_notes, oq_rank, rq_rank, chips, updated_at
"""

SELECT_ALL_SQL = """
    SELECT listing_id, bucket, bucket_changed_at, price_at_archive,
           oq_notes, rq_notes, oq_rank, rq_rank, chips, updated_at
    FROM listing_status ORDER BY updated_at DESC
"""

# Fallback if migration hasn't run yet
SELECT_ALL_LEGACY_SQL = """
    SELECT listing_id,
           CASE WHEN watch THEN 'shortlist' ELSE 'inbox' END as bucket,
           updated_at as bucket_changed_at,
           NULL::integer as price_at_archive,
           oq_notes, rq_notes, oq_rank, rq_rank, chips, updated_at
    FROM listing_status ORDER BY updated_at DESC
"""


def row_to_dict(r):
    return {
        "listing_id": r["listing_id"],
        "bucket": r["bucket"],
        "bucket_changed_at": r["bucket_changed_at"].isoformat() if r["bucket_changed_at"] else None,
        "price_at_archive": r["price_at_archive"],
        "oq_notes": r["oq_notes"],
        "rq_notes": r["rq_notes"],
        "oq_rank": r["oq_rank"],
        "rq_rank": r["rq_rank"],
        "chips": r["chips"],
        "updated_at": r["updated_at"].isoformat(),
    }


async def should_clear_ranks(conn, listing_id: str, new_bucket: str | None) -> bool:
    """Check if this transition exits shortlist (requires rank clearing)."""
    if new_bucket is None or new_bucket == 'shortlist':
        return False
    # Check current bucket
    current = await conn.fetchval(
        "SELECT bucket FROM listing_status WHERE listing_id = $1", listing_id
    )
    return current == 'shortlist'


async def do_upsert(conn, listing_id: str, patch, clear_ranks: bool):
    """Execute the upsert with or without rank clearing."""
    from datetime import datetime, timezone

    chips_json = json.dumps(patch.chips) if patch.chips is not None else None

    # Convert bucket_changed_at string to datetime for asyncpg
    bucket_changed_at = None
    if patch.bucket_changed_at:
        try:
            bucket_changed_at = datetime.fromisoformat(patch.bucket_changed_at.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            bucket_changed_at = datetime.now(timezone.utc)

    sql = UPSERT_WITH_RANK_CLEAR_SQL if clear_ranks else UPSERT_SQL
    row = await conn.fetchrow(
        sql,
        listing_id,
        patch.bucket,
        bucket_changed_at,
        patch.price_at_archive,
        patch.oq_notes,
        patch.rq_notes,
        patch.oq_rank,
        patch.rq_rank,
        chips_json,
    )
    return row


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
        try:
            rows = await conn.fetch(SELECT_ALL_SQL)
        except Exception:
            # Migration hasn't run yet — use legacy query
            rows = await conn.fetch(SELECT_ALL_LEGACY_SQL)
    return {"items": [row_to_dict(r) for r in rows]}


@app.put("/status/{listing_id}", dependencies=[Depends(require_write_key)])
async def put_status(listing_id: str, patch: StatusPatch):
    pool = get_pool()

    try:
        async with pool.acquire() as conn:
            clear_ranks = await should_clear_ranks(conn, listing_id, patch.bucket)
            row = await do_upsert(conn, listing_id, patch, clear_ranks)
        return row_to_dict(row)
    except Exception as e:
        import traceback
        return Response(
            content=json.dumps({"error": str(e), "trace": traceback.format_exc()}),
            status_code=500,
            media_type="application/json",
        )


@app.post("/status/batch", dependencies=[Depends(require_write_key)])
async def post_batch(body: BatchRequest):
    pool = get_pool()
    results = []
    errors = []

    async with pool.acquire() as conn:
        async with conn.transaction():
            for item in body.items:
                try:
                    clear_ranks = await should_clear_ranks(conn, item.listing_id, item.bucket)
                    row = await do_upsert(conn, item.listing_id, item, clear_ranks)
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
