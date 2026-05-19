"""
RabbitMQ клиент на aio-pika.

Очереди:
  tg.incoming  — listener → ai-worker: новые/продолжающиеся сообщения из Telegram
  tg.outgoing  — ai-worker → listener: готовые ответы для отправки в Telegram

Формат сообщения tg.incoming (JSON):
  {
    "user_id": 123456789,
    "text": "хочу купить ручку",
    "is_opening": true,          # true = первое сообщение диалога
    "from_user": {
      "username": "...",
      "first_name": "...",
      "last_name": "..."
    }
  }

Формат сообщения tg.outgoing (JSON):
  {
    "user_id": 123456789,
    "text": "Привет! Расскажи подробнее...",
    "notify_admin": false,       # true = уведомить админа (сделка)
    "admin_text": "..."          # текст уведомления если notify_admin=true
  }
"""

import json
import asyncio
import aio_pika
from aio_pika.abc import AbstractRobustConnection, AbstractChannel, AbstractQueue

from config import RABBITMQ_URL

QUEUE_INCOMING = "tg.incoming"
QUEUE_OUTGOING = "tg.outgoing"


async def get_connection() -> AbstractRobustConnection:
    """Устойчивое соединение — автоматически восстанавливается при разрыве."""
    return await aio_pika.connect_robust(RABBITMQ_URL)


async def publish(connection: AbstractRobustConnection, queue_name: str, payload: dict) -> None:
    """Опубликовать JSON-сообщение в очередь."""
    async with connection.channel() as channel:
        await channel.declare_queue(queue_name, durable=True)
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload, ensure_ascii=False).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=queue_name,
        )


async def consume(
    connection: AbstractRobustConnection,
    queue_name: str,
    handler,
    prefetch_count: int = 1,
) -> None:
    """
    Запустить consumer в бесконечном цикле.
    handler(payload: dict) — async-функция обработки сообщения.
    prefetch_count=1 — брать по одному сообщению (важно для ai-worker).
    """
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=prefetch_count)
    queue = await channel.declare_queue(queue_name, durable=True)

    async with queue.iterator() as it:
        async for message in it:
            async with message.process(requeue=True):
                payload = json.loads(message.body.decode())
                await handler(payload)
