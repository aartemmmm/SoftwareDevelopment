from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.cache import flush_product_cache, init_cache, close_cache
from app.database import init_db, seed_products
from app.metrics import metrics_router
from app.strategies.lazy_loading import router as lazy_router
from app.strategies.write_back import router as wb_router, start_flush_task, stop_flush_task
from app.strategies.write_through import router as wt_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await init_cache()
    await start_flush_task()
    yield
    await stop_flush_task()
    await close_cache()


app = FastAPI(
    title="Cache Strategy Comparison",
    description="Lazy Loading vs Write-Through vs Write-Back",
    lifespan=lifespan,
)

app.include_router(lazy_router, prefix="/lazy", tags=["Lazy Loading / Cache-Aside"])
app.include_router(wt_router, prefix="/write-through", tags=["Write-Through"])
app.include_router(wb_router, prefix="/write-back", tags=["Write-Back"])
app.include_router(metrics_router, prefix="/metrics", tags=["Metrics"])


@app.post("/admin/seed", tags=["Admin"])
async def admin_seed(count: int = 1000):
    n = await seed_products(count)
    return {"seeded": n}


@app.post("/admin/reset-cache", tags=["Admin"])
async def admin_reset_cache():
    await flush_product_cache()
    return {"status": "cache cleared"}


@app.get("/", tags=["Root"])
async def root():
    return {
        "strategies": {
            "lazy":          "/lazy/product/{id}",
            "write_through": "/write-through/product/{id}",
            "write_back":    "/write-back/product/{id}",
        },
        "metrics": "/metrics/{strategy}",
        "docs":    "/docs",
    }
