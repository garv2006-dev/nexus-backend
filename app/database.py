import asyncpg
from typing import Any, List, Optional, Dict
from .config import get_settings

settings = get_settings()

_pool: Optional[asyncpg.Pool] = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        db_url = settings.database_url
        if not db_url:
            raise RuntimeError("DATABASE_URL is not set in environment variables.")
        
        _pool = await asyncpg.create_pool(
            dsn=db_url,
            min_size=1,
            max_size=10,
            command_timeout=60,
            ssl=False,
        )
        print("Connected to Supabase PostgreSQL asyncpg connection pool.")
    return _pool


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        await init_pool()
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        print("Closed Supabase PostgreSQL connection pool.")


async def fetch_one(query: str, *args) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await conn.fetchrow(query, *args)
        return dict(record) if record else None


async def fetch_all(query: str, *args) -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        records = await conn.fetch(query, *args)
        return [dict(r) for r in records]


async def fetch_val(query: str, *args) -> Any:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(query, *args)


async def execute(query: str, *args) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)
