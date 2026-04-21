import time
import uuid
import threading

from metrics import ProducerMetrics


def _build_message(payload_size: int) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "payload": "x" * payload_size,
    }


def run_producer(
    broker_client,
    message_size: int,
    rate: int,
    duration: int,
    metrics: ProducerMetrics,
    stop_event: threading.Event,
) -> None:
    interval = 1.0 / rate
    metrics.start_time = time.time()
    deadline = metrics.start_time + duration

    while time.time() < deadline and not stop_event.is_set():
        loop_start = time.time()

        message = _build_message(message_size)
        try:
            broker_client.send(message)
            metrics.sent += 1
        except Exception as e:
            metrics.errors += 1

        elapsed = time.time() - loop_start
        sleep_for = interval - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)

    metrics.end_time = time.time()
    stop_event.set()
