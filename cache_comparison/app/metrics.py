from fastapi import APIRouter

from app.cache import get_redis

metrics_router = APIRouter()

STRATEGIES = ("lazy", "write_through", "write_back")
COUNTERS = ("total_reads", "total_writes", "cache_hits", "cache_misses", "db_reads", "db_writes")


def _key(strategy: str, counter: str) -> str:
    return f"m:{strategy}:{counter}"


async def inc(strategy: str, counter: str, amount: int = 1) -> None:
    await get_redis().incr(_key(strategy, counter), amount)


async def get_metrics_data(strategy: str) -> dict:
    r = get_redis()
    values = await r.mget([_key(strategy, c) for c in COUNTERS])
    data = {c: int(v or 0) for c, v in zip(COUNTERS, values)}
    total_cache = data["cache_hits"] + data["cache_misses"]
    data["hit_rate"] = round(data["cache_hits"] / total_cache * 100, 2) if total_cache else 0.0
    return data


@metrics_router.get("/{strategy}")
async def get_metrics(strategy: str):
    return await get_metrics_data(strategy)


@metrics_router.post("/reset")
async def reset_metrics():
    r = get_redis()
    keys = [_key(s, c) for s in STRATEGIES for c in COUNTERS]
    if keys:
        await r.delete(*keys)
    return {"status": "ok"}
