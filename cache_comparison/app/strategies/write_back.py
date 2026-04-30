"""
Write-Back (Write-Behind)

READ:  check cache → on miss fetch from DB and populate cache
WRITE: write to cache only, mark key as dirty; background task flushes dirty keys to DB
"""

import asyncio
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.cache import cache_get, cache_set, get_redis
from app.database import get_product, update_product
from app.metrics import inc

router = APIRouter()
STRATEGY = "write_back"
DIRTY_SET = "write_back:dirty_keys"
FLUSH_INTERVAL = float(os.getenv("FLUSH_INTERVAL", "5.0"))

_flush_task: Optional[asyncio.Task] = None
_running = False


class ProductUpdate(BaseModel):
    name: str
    price: float
    stock: int


@router.get("/product/{product_id}")
async def read_product(product_id: int):
    key = f"product:{product_id}"

    cached = await cache_get(key)
    if cached:
        await inc(STRATEGY, "cache_hits")
        await inc(STRATEGY, "total_reads")
        return cached

    await inc(STRATEGY, "cache_misses")
    await inc(STRATEGY, "db_reads")

    product = await get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    await cache_set(key, product)
    await inc(STRATEGY, "total_reads")
    return product


@router.put("/product/{product_id}")
async def write_product(product_id: int, body: ProductUpdate):
    key = f"product:{product_id}"
    product_data = {"id": product_id, **body.model_dump()}

    await cache_set(key, product_data)
    await get_redis().sadd(DIRTY_SET, str(product_id))

    await inc(STRATEGY, "total_writes")
    return product_data


@router.get("/dirty-count")
async def dirty_count():
    count = await get_redis().scard(DIRTY_SET)
    return {"dirty_keys": count}


@router.post("/flush")
async def manual_flush():
    flushed = await _flush_dirty_keys()
    return {"flushed": flushed}


async def _flush_dirty_keys() -> int:
    r = get_redis()
    dirty_ids = await r.smembers(DIRTY_SET)
    if not dirty_ids:
        return 0

    flushed = 0
    for pid_str in dirty_ids:
        product_id = int(pid_str)
        cached = await cache_get(f"product:{product_id}")
        if cached:
            try:
                await update_product(product_id, cached)
                await inc(STRATEGY, "db_writes")
                flushed += 1
            except Exception:
                pass
        await r.srem(DIRTY_SET, pid_str)

    return flushed


async def _flush_loop() -> None:
    while _running:
        await asyncio.sleep(FLUSH_INTERVAL)
        await _flush_dirty_keys()


async def start_flush_task() -> None:
    global _flush_task, _running
    _running = True
    _flush_task = asyncio.create_task(_flush_loop())


async def stop_flush_task() -> None:
    global _flush_task, _running
    _running = False
    if _flush_task:
        _flush_task.cancel()
        try:
            await _flush_task
        except asyncio.CancelledError:
            pass
    await _flush_dirty_keys()
