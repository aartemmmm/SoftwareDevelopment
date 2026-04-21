import time
import threading
from dataclasses import dataclass, field
from typing import List


@dataclass
class ProducerMetrics:
    sent: int = 0
    errors: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0

    def throughput(self) -> float:
        elapsed = (self.end_time or time.time()) - self.start_time
        return self.sent / elapsed if elapsed > 0 else 0.0


@dataclass
class ConsumerMetrics:
    received: int = 0
    processed: int = 0
    errors: int = 0
    latencies: List[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0

    def record(self, latency_ms: float, success: bool = True) -> None:
        with self._lock:
            self.received += 1
            if success:
                self.processed += 1
            self.latencies.append(latency_ms)

    def avg_latency(self) -> float:
        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies)

    def p95_latency(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_lat = sorted(self.latencies)
        idx = int(len(sorted_lat) * 0.95)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]

    def max_latency(self) -> float:
        return max(self.latencies) if self.latencies else 0.0

    def throughput(self) -> float:
        elapsed = (self.end_time or time.time()) - self.start_time
        return self.received / elapsed if elapsed > 0 else 0.0


def build_report(
    broker: str,
    message_size: int,
    rate: int,
    duration: int,
    producer: ProducerMetrics,
    consumer: ConsumerMetrics,
) -> dict:
    lost = max(0, producer.sent - consumer.received)
    return {
        "broker": broker,
        "message_size_bytes": message_size,
        "target_rate_msg_per_sec": rate,
        "duration_sec": duration,
        "sent": producer.sent,
        "received": consumer.received,
        "processed": consumer.processed,
        "lost": lost,
        "producer_errors": producer.errors,
        "consumer_errors": consumer.errors,
        "producer_throughput_msg_per_sec": round(producer.throughput(), 2),
        "consumer_throughput_msg_per_sec": round(consumer.throughput(), 2),
        "latency_avg_ms": round(consumer.avg_latency(), 3),
        "latency_p95_ms": round(consumer.p95_latency(), 3),
        "latency_max_ms": round(consumer.max_latency(), 3),
    }


def print_report(report: dict) -> None:
    print("\n" + "=" * 55)
    print(f"  Broker          : {report['broker']}")
    print(f"  Message size    : {report['message_size_bytes']} bytes")
    print(f"  Target rate     : {report['target_rate_msg_per_sec']} msg/s")
    print(f"  Duration        : {report['duration_sec']} s")
    print("-" * 55)
    print(f"  Sent            : {report['sent']}")
    print(f"  Received        : {report['received']}")
    print(f"  Lost            : {report['lost']}")
    print(f"  Producer errors : {report['producer_errors']}")
    print(f"  Consumer errors : {report['consumer_errors']}")
    print("-" * 55)
    print(f"  Prod throughput : {report['producer_throughput_msg_per_sec']} msg/s")
    print(f"  Cons throughput : {report['consumer_throughput_msg_per_sec']} msg/s")
    print("-" * 55)
    print(f"  Latency avg     : {report['latency_avg_ms']} ms")
    print(f"  Latency p95     : {report['latency_p95_ms']} ms")
    print(f"  Latency max     : {report['latency_max_ms']} ms")
    print("=" * 55 + "\n")
