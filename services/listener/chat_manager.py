import redis.asyncio as aioredis
from config import REDIS_HOST, REDIS_PORT, MONITORED_CHATS

_CHATS_KEY = "monitored_chats"
_INIT_FLAG = "monitored_chats:initialized"
_chats: set[str] = set()


async def load() -> None:
    r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    initialized = await r.exists(_INIT_FLAG)
    if initialized:
        stored = await r.smembers(_CHATS_KEY)
        _chats.update(stored)
    else:
        # Первый запуск — засеять из .env и выставить флаг
        _chats.update(MONITORED_CHATS)
        if MONITORED_CHATS:
            await r.sadd(_CHATS_KEY, *MONITORED_CHATS)
        await r.set(_INIT_FLAG, "1")
    await r.aclose()
    print(f"[CHATS] Мониторинг: {_chats or 'debug-режим'}")


def get() -> set[str]:
    return _chats


async def add(chat_id: str) -> None:
    _chats.add(chat_id)
    r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    await r.sadd(_CHATS_KEY, chat_id)
    await r.aclose()


async def remove(chat_id: str) -> None:
    _chats.discard(chat_id)
    r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    await r.srem(_CHATS_KEY, chat_id)
    await r.aclose()


async def reload() -> None:
    print("[CHATS] reload tick")
    r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    stored = await r.smembers(_CHATS_KEY)
    await r.aclose()
    if stored != _chats:
        _chats.clear()
        _chats.update(stored)
        print(f"[CHATS] Обновлён список: {_chats or 'пусто (debug-режим)'}")
