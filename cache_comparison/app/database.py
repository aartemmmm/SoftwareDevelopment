import asyncio
import os
from typing import Optional

import asyncpg

_pool: Optional[asyncpg.Pool] = None

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/cachedb")


async def init_db() -> None:
    global _pool
    for attempt in range(15):
        try:
            _pool = await asyncpg.create_pool(DATABASE_URL, min_size=5, max_size=30)
            await _create_schema()
            return
        except Exception as exc:
            if attempt == 14:
                raise RuntimeError(f"Cannot connect to DB after 15 attempts: {exc}") from exc
            await asyncio.sleep(2)


async def _create_schema() -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id      SERIAL PRIMARY KEY,
                name    VARCHAR(100) NOT NULL,
                price   NUMERIC(10, 2) NOT NULL,
                stock   INTEGER NOT NULL
            )
            """
        )


async def close_db() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def _row_to_dict(row: asyncpg.Record) -> dict:
    return {"id": row["id"], "name": row["name"], "price": float(row["price"]), "stock": row["stock"]}


async def get_product(product_id: int) -> Optional[dict]:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM products WHERE id = $1", product_id)
    return _row_to_dict(row) if row else None


async def update_product(product_id: int, data: dict) -> Optional[dict]:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE products SET name=$1, price=$2, stock=$3 WHERE id=$4 RETURNING *",
            data["name"],
            float(data["price"]),
            int(data["stock"]),
            product_id,
        )
    return _row_to_dict(row) if row else None


async def seed_products(count: int) -> int:
    async with _pool.acquire() as conn:
        await conn.execute("TRUNCATE products RESTART IDENTITY")
        records = [(f"Product {i}", round(10.0 + i * 0.5, 2), 100 + i) for i in range(1, count + 1)]
        await conn.executemany(
            "INSERT INTO products (name, price, stock) VALUES ($1, $2, $3)",
            records,
        )
    return count
