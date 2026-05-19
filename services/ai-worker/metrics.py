import asyncio
import structlog
from prometheus_client import Counter, Histogram, Gauge, start_http_server

log = structlog.get_logger()

gpt_response_seconds = Histogram(
    "gpt_response_seconds",
    "GPT API call latency in seconds",
    ["call"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

messages_processed_total = Counter(
    "ai_worker_messages_processed_total",
    "Total messages successfully processed by ai-worker",
)

messages_errors_total = Counter(
    "ai_worker_messages_errors_total",
    "Total messages that failed processing in ai-worker",
)

queue_messages = Gauge(
    "rabbitmq_queue_messages",
    "Number of messages waiting in RabbitMQ queue",
    ["queue"],
)


def start(port: int = 9090) -> None:
    start_http_server(port)
    log.info("prometheus metrics server started", port=port)


async def poll_queue_lengths(connection, queues: list[str], interval: int = 15) -> None:
    """Background task: poll RabbitMQ queue depths every interval seconds."""
    while True:
        try:
            async with connection.channel() as channel:
                for q in queues:
                    declared = await channel.declare_queue(q, durable=True, passive=True)
                    queue_messages.labels(queue=q).set(
                        declared.declaration_result.message_count
                    )
        except Exception as e:
            log.warning("queue length poll failed", error=str(e))
        await asyncio.sleep(interval)
