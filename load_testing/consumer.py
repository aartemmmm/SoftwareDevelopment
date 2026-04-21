import time
import threading

from metrics import ConsumerMetrics


def _process_message(message: dict, metrics: ConsumerMetrics) -> None:
    try:
        sent_at = float(message["timestamp"])
        latency_ms = (time.time() - sent_at) * 1000
        metrics.record(latency_ms, success=True)
    except Exception:
        metrics.errors += 1
        metrics.record(0.0, success=False)


def run_consumer(
    broker_client,
    metrics: ConsumerMetrics,
    stop_event: threading.Event,
) -> None:
    metrics.start_time = time.time()

    def callback(message: dict) -> None:
        if stop_event.is_set():
            broker_client.stop()
            return
        _process_message(message, metrics)

    try:
        broker_client.consume(callback)
    except Exception:
        pass

    metrics.end_time = time.time()
