"""asyncpg connection pool management."""

import os
import asyncpg

_pool: asyncpg.Pool | None = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call pool_startup() first.")
    return _pool


async def pool_startup():
    global _pool
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required")
    _pool = await asyncpg.create_pool(
        database_url,
        min_size=1,
        max_size=5,
        command_timeout=10,
    )


async def pool_shutdown():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
