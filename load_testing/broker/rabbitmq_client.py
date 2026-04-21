import pika
import json


QUEUE_NAME = "load_test"


def get_connection(host: str = "localhost") -> pika.BlockingConnection:
    params = pika.ConnectionParameters(
        host=host,
        heartbeat=600,
        blocked_connection_timeout=300,
    )
    return pika.BlockingConnection(params)


class RabbitMQProducer:
    def __init__(self, host: str = "localhost"):
        self.connection = get_connection(host)
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=QUEUE_NAME, durable=False)

    def send(self, message: dict) -> None:
        self.channel.basic_publish(
            exchange="",
            routing_key=QUEUE_NAME,
            body=json.dumps(message),
            properties=pika.BasicProperties(delivery_mode=1),
        )

    def close(self) -> None:
        self.connection.close()


class RabbitMQConsumer:
    def __init__(self, host: str = "localhost"):
        self.connection = get_connection(host)
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=QUEUE_NAME, durable=False)
        self.channel.basic_qos(prefetch_count=500)

    def consume(self, callback) -> None:
        def _on_message(ch, method, properties, body):
            message = json.loads(body)
            callback(message)
            ch.basic_ack(delivery_tag=method.delivery_tag)

        self.channel.basic_consume(queue=QUEUE_NAME, on_message_callback=_on_message)
        self.channel.start_consuming()

    def stop(self) -> None:
        # add_callback_threadsafe is the only thread-safe way to stop pika from another thread
        self.connection.add_callback_threadsafe(self.channel.stop_consuming)

    def close(self) -> None:
        try:
            if self.connection.is_open:
                self.connection.close()
        except Exception:
            pass

    def purge(self) -> None:
        self.channel.queue_purge(QUEUE_NAME)
