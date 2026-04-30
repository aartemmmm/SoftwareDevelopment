"""
Load generator for cache strategy comparison.

Usage:
    python load_generator.py --strategy lazy --workload read-heavy
    python load_generator.py --strategy write_through --workload balanced --duration 60
    python load_generator.py --strategy write_back --workload write-heavy --concurrency 50
"""

import argparse
import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from statistics import mean
from typing import Optional

import aiohttp

BASE_URL = "http://localhost:8000"
NUM_PRODUCTS = 1000

WORKLOADS = {
    "read-heavy":   0.80,
    "balanced":     0.50,
    "write-heavy":  0.20,
}

STRATEGY_PREFIX = {
    "lazy":          "lazy",
    "write_through": "write-through",
    "write_back":    "write-back",
}


@dataclass
class TestResult:
    strategy: str
    workload: str
    read_ratio: float
    duration: float
    total_requests: int
    successful_requests: int
    latencies: list = field(default_factory=list)
    app_metrics: dict = field(default_factory=dict)
    dirty_keys_mid: int = 0

    @property
    def throughput(self) -> float:
        return round(self.successful_requests / self.duration, 2) if self.duration > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return round(mean(self.latencies) * 1000, 3) if self.latencies else 0.0

    @property
    def p95_latency_ms(self) -> float:
        if not self.latencies:
            return 0.0
        s = sorted(self.latencies)
        idx = min(int(0.95 * len(s)), len(s) - 1)
        return round(s[idx] * 1000, 3)

    @property
    def cache_hit_rate(self) -> float:
        return self.app_metrics.get("hit_rate", 0.0)

    @property
    def db_reads(self) -> int:
        return int(self.app_metrics.get("db_reads", 0))

    @property
    def db_writes(self) -> int:
        return int(self.app_metrics.get("db_writes", 0))


async def run_test(
    strategy: str,
    workload: str,
    duration_sec: int = 60,
    concurrency: int = 50,
    base_url: str = BASE_URL,
    num_products: int = NUM_PRODUCTS,
    verbose: bool = True,
) -> TestResult:
    read_ratio = WORKLOADS[workload]
    prefix = STRATEGY_PREFIX[strategy]

    connector = aiohttp.TCPConnector(limit=concurrency + 10)
    timeout = aiohttp.ClientTimeout(total=10)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        # Reset metrics before the run
        await session.post(f"{base_url}/metrics/reset")

        latencies: list[float] = []
        counters = {"total": 0, "ok": 0}
        stop_event = asyncio.Event()
        lock = asyncio.Lock()

        async def worker():
            while not stop_event.is_set():
                is_read = random.random() < read_ratio
                product_id = random.randint(1, num_products)

                t0 = time.monotonic()
                try:
                    if is_read:
                        url = f"{base_url}/{prefix}/product/{product_id}"
                        async with session.get(url) as resp:
                            await resp.read()
                            elapsed = time.monotonic() - t0
                            async with lock:
                                counters["total"] += 1
                                if resp.status == 200:
                                    counters["ok"] += 1
                                    latencies.append(elapsed)
                    else:
                        url = f"{base_url}/{prefix}/product/{product_id}"
                        payload = {
                            "name": f"Product {product_id}",
                            "price": round(random.uniform(5.0, 200.0), 2),
                            "stock": random.randint(0, 999),
                        }
                        async with session.put(url, json=payload) as resp:
                            await resp.read()
                            elapsed = time.monotonic() - t0
                            async with lock:
                                counters["total"] += 1
                                if resp.status == 200:
                                    counters["ok"] += 1
                                    latencies.append(elapsed)
                except Exception:
                    pass

        if verbose:
            print(f"  [{strategy}] [{workload}] starting {concurrency} workers for {duration_sec}s ...")

        workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
        start_time = time.monotonic()

        # Mid-point snapshot for write-back dirty keys
        dirty_mid = 0
        await asyncio.sleep(duration_sec / 2)
        if strategy == "write_back":
            try:
                async with session.get(f"{base_url}/write-back/dirty-count") as r:
                    dirty_mid = (await r.json()).get("dirty_keys", 0)
                    if verbose:
                        print(f"  [write_back] dirty keys at mid-point: {dirty_mid}")
            except Exception:
                pass
        await asyncio.sleep(duration_sec / 2)

        actual_duration = time.monotonic() - start_time
        stop_event.set()
        await asyncio.gather(*workers, return_exceptions=True)

        # Fetch app-side metrics
        app_metrics: dict = {}
        try:
            async with session.get(f"{base_url}/metrics/{strategy}") as r:
                app_metrics = await r.json()
        except Exception:
            pass

    result = TestResult(
        strategy=strategy,
        workload=workload,
        read_ratio=read_ratio,
        duration=actual_duration,
        total_requests=counters["total"],
        successful_requests=counters["ok"],
        latencies=latencies,
        app_metrics=app_metrics,
        dirty_keys_mid=dirty_mid,
    )

    if verbose:
        _print_result(result)

    return result


def _print_result(r: TestResult) -> None:
    print(
        f"\n  Strategy  : {r.strategy}\n"
        f"  Workload  : {r.workload} ({int(r.read_ratio * 100)}% read / {int((1 - r.read_ratio) * 100)}% write)\n"
        f"  Duration  : {r.duration:.1f}s\n"
        f"  Requests  : {r.total_requests} total / {r.successful_requests} ok\n"
        f"  Throughput: {r.throughput} req/s\n"
        f"  Avg lat.  : {r.avg_latency_ms} ms\n"
        f"  P95 lat.  : {r.p95_latency_ms} ms\n"
        f"  Cache hits: {r.cache_hit_rate}%\n"
        f"  DB reads  : {r.db_reads}\n"
        f"  DB writes : {r.db_writes}"
    )
    if r.strategy == "write_back" and r.dirty_keys_mid:
        print(f"  Dirty keys (mid): {r.dirty_keys_mid}")


def result_to_dict(r: TestResult) -> dict:
    return {
        "strategy": r.strategy,
        "workload": r.workload,
        "read_ratio": r.read_ratio,
        "duration_sec": round(r.duration, 2),
        "total_requests": r.total_requests,
        "successful_requests": r.successful_requests,
        "throughput_rps": r.throughput,
        "avg_latency_ms": r.avg_latency_ms,
        "p95_latency_ms": r.p95_latency_ms,
        "cache_hit_rate_pct": r.cache_hit_rate,
        "db_reads": r.db_reads,
        "db_writes": r.db_writes,
        "dirty_keys_mid": r.dirty_keys_mid,
    }


async def _main():
    parser = argparse.ArgumentParser(description="Cache strategy load generator")
    parser.add_argument("--strategy", choices=list(STRATEGY_PREFIX), required=True)
    parser.add_argument("--workload", choices=list(WORKLOADS), required=True)
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--num-products", type=int, default=NUM_PRODUCTS)
    args = parser.parse_args()

    result = await run_test(
        strategy=args.strategy,
        workload=args.workload,
        duration_sec=args.duration,
        concurrency=args.concurrency,
        base_url=args.base_url,
        num_products=args.num_products,
    )
    print("\nJSON result:")
    print(json.dumps(result_to_dict(result), indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
