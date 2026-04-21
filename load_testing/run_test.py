#!/usr/bin/env python3
"""
Entry point for load testing RabbitMQ vs Redis.

Usage:
    python run_test.py --broker rabbitmq --size 1024 --rate 1000 --duration 60
    python run_test.py --broker redis    --size 128  --rate 5000 --duration 30
"""

import argparse
import csv
import json
import os
import threading
import time

from metrics import ProducerMetrics, ConsumerMetrics, build_report, print_report
from producer import run_producer
from consumer import run_consumer

RESULTS_DIR = "results"

SIZE_PRESETS = {
    "128B": 128,
    "1KB": 1024,
    "10KB": 10 * 1024,
    "100KB": 100 * 1024,
}


def _parse_size(value: str) -> int:
    if value in SIZE_PRESETS:
        return SIZE_PRESETS[value]
    try:
        return int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid size '{value}'. Use one of {list(SIZE_PRESETS)} or a plain integer."
        )


def _build_broker_clients(broker: str, host: str):
    if broker == "rabbitmq":
        from broker.rabbitmq_client import RabbitMQProducer, RabbitMQConsumer
        producer_client = RabbitMQProducer(host=host)
        consumer_client = RabbitMQConsumer(host=host)
        consumer_client.purge()
        return producer_client, consumer_client

    if broker == "redis":
        from broker.redis_client import RedisProducer, RedisConsumer
        producer_client = RedisProducer(host=host)
        consumer_client = RedisConsumer(host=host)
        consumer_client.purge()
        return producer_client, consumer_client

    raise ValueError(f"Unknown broker: {broker}")


def _save_results(report: dict) -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    base = f"{RESULTS_DIR}/{report['broker']}_{report['message_size_bytes']}B_{report['target_rate_msg_per_sec']}rps_{timestamp}"

    json_path = base + ".json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)

    csv_path = base + ".csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=report.keys())
        writer.writeheader()
        writer.writerow(report)

    print(f"  Results saved → {json_path}")
    print(f"                  {csv_path}")


def run_test(broker: str, message_size: int, rate: int, duration: int, host: str) -> dict:
    print(f"\nInitialising broker clients ({broker} @ {host}) ...")
    producer_client, consumer_client = _build_broker_clients(broker, host)

    producer_metrics = ProducerMetrics()
    consumer_metrics = ConsumerMetrics()
    stop_event = threading.Event()

    consumer_thread = threading.Thread(
        target=run_consumer,
        args=(consumer_client, consumer_metrics, stop_event),
        daemon=True,
    )
    producer_thread = threading.Thread(
        target=run_producer,
        args=(producer_client, message_size, rate, duration, producer_metrics, stop_event),
    )

    print(f"Starting consumer ...")
    consumer_thread.start()
    time.sleep(0.3)

    print(f"Starting producer  (size={message_size}B, rate={rate} msg/s, duration={duration}s) ...")
    producer_thread.start()
    producer_thread.join()

    print("Producer finished. Waiting for consumer to drain ...")
    drain_timeout = min(30, duration)
    deadline = time.time() + drain_timeout
    while time.time() < deadline:
        if consumer_metrics.received >= producer_metrics.sent:
            break
        time.sleep(0.5)

    consumer_client.stop()
    consumer_thread.join(timeout=5)

    producer_client.close()
    consumer_client.close()

    report = build_report(broker, message_size, rate, duration, producer_metrics, consumer_metrics)
    print_report(report)
    _save_results(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Message broker load tester")
    parser.add_argument("--broker", choices=["rabbitmq", "redis"], required=True)
    parser.add_argument(
        "--size",
        type=_parse_size,
        default="1KB",
        help="Message size: 128B | 1KB | 10KB | 100KB | <bytes>",
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=1000,
        choices=[1000, 5000, 10000],
        help="Target send rate in msg/sec",
    )
    parser.add_argument("--duration", type=int, default=60, help="Test duration in seconds")
    parser.add_argument("--host", type=str, default="localhost", help="Broker host")
    args = parser.parse_args()

    run_test(
        broker=args.broker,
        message_size=args.size,
        rate=args.rate,
        duration=args.duration,
        host=args.host,
    )


if __name__ == "__main__":
    main()
