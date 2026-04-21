import redis
import json

STREAM_NAME = "load_test"
CONSUMER_GROUP = "load_test_group"
CONSUMER_NAME = "consumer-1"


class RedisProducer:
    def __init__(self, host: str = "localhost", port: int = 6379):
        self.client = redis.Redis(host=host, port=port, decode_responses=True)

    def send(self, message: dict) -> None:
        self.client.xadd(STREAM_NAME, {"data": json.dumps(message)})

    def close(self) -> None:
        self.client.close()


class RedisConsumer:
    def __init__(self, host: str = "localhost", port: int = 6379):
        self.client = redis.Redis(host=host, port=port, decode_responses=True)
        self._running = False
        self._ensure_group()

    def _ensure_group(self) -> None:
        try:
            self.client.xgroup_create(STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True)
        except redis.exceptions.ResponseError:
            pass

    def consume(self, callback) -> None:
        self._running = True
        while self._running:
            entries = self.client.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                {STREAM_NAME: ">"},
                count=500,
                block=100,
            )
            if not entries:
                continue
            for _, messages in entries:
                for msg_id, fields in messages:
                    message = json.loads(fields["data"])
                    callback(message)
                    self.client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)

    def stop(self) -> None:
        self._running = False

    def close(self) -> None:
        self.client.close()

    def purge(self) -> None:
        self.client.delete(STREAM_NAME)
        self._ensure_group()
