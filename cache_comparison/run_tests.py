"""
Runs the full cache strategy comparison test suite:
    3 strategies × 3 workloads = 9 test scenarios

Between each scenario:
  - DB products are re-seeded (so every strategy starts with identical data)
  - Redis cache is fully cleared
  - Metrics counters are reset

Results are saved to results/results_<timestamp>.json
A markdown report is printed to stdout and saved to results/report_<timestamp>.md
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime

import aiohttp

sys.path.insert(0, os.path.dirname(__file__))
from load_generator import STRATEGY_PREFIX, WORKLOADS, run_test, result_to_dict

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
NUM_PRODUCTS = int(os.getenv("NUM_PRODUCTS", "1000"))
DURATION = int(os.getenv("DURATION", "60"))
CONCURRENCY = int(os.getenv("CONCURRENCY", "50"))

STRATEGIES = list(STRATEGY_PREFIX.keys())


async def prepare_environment(session: aiohttp.ClientSession) -> None:
    """Re-seed DB and clear all caches to guarantee identical starting conditions."""
    r = await session.post(f"{BASE_URL}/admin/seed?count={NUM_PRODUCTS}")
    r.raise_for_status()
    r = await session.post(f"{BASE_URL}/admin/reset-cache")
    r.raise_for_status()
    r = await session.post(f"{BASE_URL}/metrics/reset")
    r.raise_for_status()
    # Brief warm-up pause
    await asyncio.sleep(1)


def build_markdown_table(results: list[dict]) -> str:
    header = (
        "| Стратегия | Нагрузка | Throughput (req/s) | "
        "Avg Latency (ms) | P95 Latency (ms) | Cache Hit Rate | DB Reads | DB Writes |"
    )
    separator = "|---|---|---|---|---|---|---|---|"
    rows = []
    for r in results:
        strategy_display = {
            "lazy": "Lazy Loading",
            "write_through": "Write-Through",
            "write_back": "Write-Back",
        }.get(r["strategy"], r["strategy"])

        workload_display = {
            "read-heavy":  "Read-Heavy (80/20)",
            "balanced":    "Balanced (50/50)",
            "write-heavy": "Write-Heavy (20/80)",
        }.get(r["workload"], r["workload"])

        row = (
            f"| {strategy_display} | {workload_display} "
            f"| {r['throughput_rps']} "
            f"| {r['avg_latency_ms']} "
            f"| {r['p95_latency_ms']} "
            f"| {r['cache_hit_rate_pct']}% "
            f"| {r['db_reads']} "
            f"| {r['db_writes']} |"
        )
        rows.append(row)

    return "\n".join([header, separator] + rows)


def build_report(results: list[dict], duration: int, concurrency: int) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    table = build_markdown_table(results)

    # Separate tables by workload for easier reading
    workload_sections = []
    for wl in WORKLOADS:
        subset = [r for r in results if r["workload"] == wl]
        if subset:
            workload_sections.append(f"### {wl.capitalize()}\n\n{build_markdown_table(subset)}")

    # Write-back dirty key accumulation
    wb_write_heavy = next(
        (r for r in results if r["strategy"] == "write_back" and r["workload"] == "write-heavy"),
        None,
    )
    wb_note = ""
    if wb_write_heavy and wb_write_heavy["dirty_keys_mid"]:
        wb_note = (
            f"\n**Write-Back — накопление dirty-записей (write-heavy тест):**\n\n"
            f"- Dirty keys в середине теста: **{wb_write_heavy['dirty_keys_mid']}**\n"
            f"- DB Writes за весь тест (flush-ами): **{wb_write_heavy['db_writes']}**\n"
            f"- Cache Writes за весь тест: **{wb_write_heavy['successful_requests']}** "
            f"({int((1 - wb_write_heavy['read_ratio']) * 100)}% нагрузки)\n"
        )

    report = f"""# ОТЧЕТ: СРАВНЕНИЕ СТРАТЕГИЙ КЕШИРОВАНИЯ

Дата: {timestamp}

---

## 1. УСЛОВИЯ ТЕСТИРОВАНИЯ

| Параметр | Значение |
|---|---|
| Инфраструктура | Docker: PostgreSQL 16 + Redis 7 + FastAPI app |
| Продуктов в БД | {NUM_PRODUCTS} |
| Длительность каждого теста | {duration} сек |
| Конкурентность (воркеры) | {concurrency} |
| Нагрузочные сценарии | Read-Heavy (80/20), Balanced (50/50), Write-Heavy (20/80) |

Перед каждым тестом: полная пересейдка БД + очистка кеша + сброс счётчиков метрик.

---

## 2. СВОДНАЯ ТАБЛИЦА РЕЗУЛЬТАТОВ

{table}

---

## 3. РЕЗУЛЬТАТЫ ПО СЦЕНАРИЯМ

{chr(10).join(workload_sections)}

---

## 4. НАКОПЛЕНИЕ ЗАПИСЕЙ В WRITE-BACK
{wb_note if wb_note else "_Данные по dirty-ключам недоступны._"}

---

## 5. ВЫВОДЫ

### Для READ-нагрузки (80% чтение)
- **Lazy Loading** даёт наименьшую нагрузку на БД после прогрева кеша. Первый запрос к каждому ключу — cache miss и DB read, последующие — cache hit.
- **Write-Through** аналогичен Lazy Loading по чтению. Кеш всегда актуален, поэтому cache hit rate выше при смешанной нагрузке.
- **Write-Back** аналогичен по read-пути всем остальным.

### Для WRITE-нагрузки (80% запись)
- **Lazy Loading (Write-Around)** каждую запись отправляет напрямую в БД — максимальная нагрузка на DB.
- **Write-Through** — то же: каждая запись идёт в БД + кеш.
- **Write-Back** — записи оседают в кеше, в БД попадают батчами при flush. Минимальное число DB writes, минимальная задержка записи. Риск: потеря данных при сбое до flush.

### Для BALANCED-нагрузки (50/50)
- **Write-Through** лучший баланс: кеш всегда свеж, одновременное обновление DB и cache.
- **Lazy Loading** — немного выше cache miss rate из-за инвалидации при записи.
- **Write-Back** — lowest write latency, но DB может отставать от кеша на FLUSH_INTERVAL секунд.

### Итоговая рекомендация

| Сценарий | Рекомендуемая стратегия | Причина |
|---|---|---|
| Чтение-доминирующее | **Lazy Loading** | Простота + низкая нагрузка на DB после прогрева |
| Смешанная нагрузка | **Write-Through** | Кеш всегда актуален, предсказуемая задержка |
| Запись-доминирующее | **Write-Back** | Батчевая запись в DB, минимальная задержка write |
| Критичность данных | **Write-Through** | Гарантия консистентности кеш ↔ DB |
"""
    return report


async def main():
    print("=" * 60)
    print("  CACHE STRATEGY COMPARISON — FULL TEST SUITE")
    print("=" * 60)
    print(f"  Base URL    : {BASE_URL}")
    print(f"  Products    : {NUM_PRODUCTS}")
    print(f"  Duration    : {DURATION}s per test")
    print(f"  Concurrency : {CONCURRENCY} workers")
    print(f"  Total tests : {len(STRATEGIES) * len(WORKLOADS)}")
    print("=" * 60)

    # Quick connectivity check
    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            async with session.get(f"{BASE_URL}/") as r:
                r.raise_for_status()
        except Exception as e:
            print(f"\n[ERROR] Cannot reach {BASE_URL}: {e}")
            print("Make sure the app is running: docker compose up -d")
            sys.exit(1)

        print("\n[OK] App is reachable. Starting tests...\n")

        all_results = []
        total_start = time.monotonic()

        for strategy in STRATEGIES:
            for workload in WORKLOADS:
                print(f"\n{'─' * 50}")
                print(f"  Test: [{strategy}] [{workload}]")
                print(f"{'─' * 50}")

                await prepare_environment(session)
                result = await run_test(
                    strategy=strategy,
                    workload=workload,
                    duration_sec=DURATION,
                    concurrency=CONCURRENCY,
                    base_url=BASE_URL,
                    num_products=NUM_PRODUCTS,
                )
                all_results.append(result_to_dict(result))

    total_elapsed = time.monotonic() - total_start
    print(f"\n\n{'=' * 60}")
    print(f"  All {len(all_results)} tests completed in {total_elapsed:.0f}s")
    print(f"{'=' * 60}\n")

    # Save results
    os.makedirs("results", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = f"results/results_{ts}.json"
    md_path = f"results/report_{ts}.md"

    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=2)

    report = build_report(all_results, DURATION, CONCURRENCY)
    with open(md_path, "w") as f:
        f.write(report)

    print(report)
    print(f"\nResults saved:")
    print(f"  JSON   : {json_path}")
    print(f"  Report : {md_path}")


if __name__ == "__main__":
    asyncio.run(main())
