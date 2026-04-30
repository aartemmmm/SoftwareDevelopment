"""
Write-Through

READ:  check cache → on miss fetch from DB and populate cache
WRITE: write to DB, then immediately update cache with new value
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.cache import cache_get, cache_set
from app.database import get_product, update_product
from app.metrics import inc

router = APIRouter()
STRATEGY = "write_through"


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
    product = await update_product(product_id, body.model_dump())
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    await inc(STRATEGY, "db_writes")
    await cache_set(f"product:{product_id}", product)
    await inc(STRATEGY, "total_writes")
    return product
