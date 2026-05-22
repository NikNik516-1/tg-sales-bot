import json
from datetime import datetime, timezone
import redis.asyncio as aioredis
from config import REDIS_HOST, REDIS_PORT

_redis: aioredis.Redis | None = None

def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    return _redis

async def get_state(user_id: int) -> str | None:
    return await get_redis().get(f"state:{user_id}")


async def set_state(user_id: int, state: str) -> None:
    await get_redis().set(f"state:{user_id}", state)


async def get_history(user_id: int) -> list[dict]:
    data = await get_redis().get(f"history:{user_id}")
    return json.loads(data) if data else []


async def append_history(user_id: int, role: str, content: str) -> None:
    history = await get_history(user_id)
    history.append({
        "role": role,
        "content": content,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    await get_redis().set(f"history:{user_id}", json.dumps(history, ensure_ascii=False))


USER_INFO_TTL = 86400 * 30  # 30 дней


async def save_user_info(user_id: int, username: str, first_name: str, last_name: str) -> None:
    info = json.dumps({
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
    }, ensure_ascii=False)
    await get_redis().setex(f"user_info:{user_id}", USER_INFO_TTL, info)


async def get_user_info(user_id: int) -> dict:
    data = await get_redis().get(f"user_info:{user_id}")
    return json.loads(data) if data else {}


async def clear_user(user_id: int) -> None:
    await get_redis().delete(f"state:{user_id}", f"history:{user_id}")


async def get_all_active_users() -> list[dict]:
    r = get_redis()
    result = []
    async for key in r.scan_iter("state:*"):
        state = await r.get(key)
        if state:
            user_id = key.split(":", 1)[1]
            result.append({"user_id": user_id, "state": state})
    return result
