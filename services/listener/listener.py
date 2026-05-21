import json
import asyncio
from datetime import datetime, timezone

import structlog
import redis.asyncio as aioredis
from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.types import Message
from pyrogram.errors import UserIsBlocked, InputUserDeactivated, PeerIdInvalid

from config import ADMIN_TG_ID, REDIS_HOST, REDIS_PORT
from state import get_state, set_state, clear_user
from mq import publish, QUEUE_INCOMING, QUEUE_OUTGOING
import chat_manager

log = structlog.get_logger()

_mq_connection = None


def set_mq_connection(conn) -> None:
    global _mq_connection
    _mq_connection = conn


async def _send_safe(client: Client, user_id: int, text: str, parse_mode=None) -> bool:
    try:
        await client.send_message(user_id, text, parse_mode=parse_mode)
        return True
    except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid) as e:
        log.warning("не удалось отправить DM", user_id=user_id, error=str(e))
        return False


async def _log_seen_channel(client: Client, message: Message) -> None:
    channel_id = str(message.chat.id)
    r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    if await r.hexists("seen_channels", channel_id):
        await r.aclose()
        return

    linked_group_id = None
    try:
        chat = await client.get_chat(message.chat.id)
        if chat.linked_chat:
            linked_group_id = str(chat.linked_chat.id)
    except Exception as e:
        log.warning("не удалось получить linked_chat", channel_id=channel_id, error=str(e))

    info = json.dumps({
        "title": message.chat.title or "",
        "username": message.chat.username or "",
        "linked_group_id": linked_group_id,
        "first_seen": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }, ensure_ascii=False)
    await r.hsetnx("seen_channels", channel_id, info)
    await r.aclose()


_CHAT_TYPE_DISPLAY = {
    ChatType.CHANNEL: "Канал",
    ChatType.SUPERGROUP: "Супергруппа",
    ChatType.GROUP: "Группа",
}


async def _log_seen_chat(message: Message) -> None:
    chat_id = str(message.chat.id)
    if chat_id in chat_manager.get():
        return
    r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    info = json.dumps({
        "title": message.chat.title or "",
        "username": message.chat.username or "",
        "type": _CHAT_TYPE_DISPLAY.get(message.chat.type, ""),
        "first_seen": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }, ensure_ascii=False)
    await r.hsetnx("seen_chats", chat_id, info)
    await r.aclose()


async def _log_seen_user(message: Message) -> None:
    if not message.from_user:
        return
    user_id = str(message.from_user.id)
    r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    try:
        if await r.hexists("seen_users", user_id):
            return
        info = json.dumps({
            "username": message.from_user.username or "",
            "first_name": message.from_user.first_name or "",
            "last_name": message.from_user.last_name or "",
            "phone": message.from_user.phone_number or "",
            "chat_id": str(message.chat.id),
            "chat_title": message.chat.title or "",
            "first_seen": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }, ensure_ascii=False)
        await r.hsetnx("seen_users", user_id, info)
    finally:
        await r.aclose()


def _in_monitored_chat(_, __, message: Message) -> bool:
    chats = chat_manager.get()
    if not chats:
        log.debug("debug chat", chat_id=message.chat.id, username=message.chat.username)
        return False
    chat_id = str(message.chat.id)
    username = message.chat.username or ""
    return chat_id in chats or username in chats


def _has_keyword(_, __, message: Message) -> bool:
    from config import KEYWORDS
    if not message.text:
        return False
    text = message.text.lower()
    return any(kw in text for kw in KEYWORDS)


monitored_chat = filters.create(_in_monitored_chat)
has_keyword = filters.create(_has_keyword)


async def handle_outgoing(client: Client, payload: dict) -> None:
    """Обработчик сообщений из очереди tg.outgoing (ответы от ai-worker)."""
    user_id = payload["user_id"]
    text = payload.get("text", "")

    if payload.get("notify_admin"):
        _PM_MAP = {"html": ParseMode.HTML, "markdown": ParseMode.MARKDOWN}
        admin_pm = _PM_MAP.get(payload.get("admin_parse_mode", ""))
        await _send_safe(client, ADMIN_TG_ID, payload.get("admin_text", ""), parse_mode=admin_pm)

    if text:
        await _send_safe(client, user_id, text)


def _from_user_info(from_user) -> dict:
    return {
        "username": from_user.username or "",
        "first_name": from_user.first_name or "",
        "last_name": from_user.last_name or "",
        "phone": from_user.phone_number or "",
    }


def register(app: Client):

    @app.on_message(monitored_chat & has_keyword & ~filters.me)
    async def on_keyword(client: Client, message: Message):
        if not message.from_user:
            return
        user_id = message.from_user.id
        state = await get_state(user_id)

        if state == "pitching":
            log.info("продолжение диалога", user_id=user_id)
            await publish(_mq_connection, QUEUE_INCOMING, {
                "user_id": user_id,
                "text": f"[Группа] {message.text}",
                "is_opening": False,
                "is_returning": False,
                "from_user": _from_user_info(message.from_user),
            })
            return

        if state == "agreed":
            log.info("клиент вернулся", user_id=user_id)
            await clear_user(user_id)
            await set_state(user_id, "pitching")
            await publish(_mq_connection, QUEUE_INCOMING, {
                "user_id": user_id,
                "text": message.text,
                "is_opening": True,
                "is_returning": True,
                "from_user": _from_user_info(message.from_user),
            })
            return

        if state:
            return

        log.info("новый диалог", user_id=user_id)
        await set_state(user_id, "pitching")
        await publish(_mq_connection, QUEUE_INCOMING, {
            "user_id": user_id,
            "text": message.text,
            "is_opening": True,
            "is_returning": False,
            "from_user": _from_user_info(message.from_user),
        })

    @app.on_message(filters.private & filters.command("reset") & ~filters.me)
    async def on_reset(client: Client, message: Message):
        user_id = message.from_user.id
        await clear_user(user_id)
        await message.reply("Диалог сброшен. Можете начать заново.")
        log.info("диалог сброшен", user_id=user_id)

    @app.on_message(filters.private & ~filters.me)
    async def on_private(client: Client, message: Message):
        if not message.text or not message.from_user:
            return
        user_id = message.from_user.id
        state = await get_state(user_id)

        if state == "pitching":
            await publish(_mq_connection, QUEUE_INCOMING, {
                "user_id": user_id,
                "text": message.text,
                "is_opening": False,
                "is_returning": False,
                "from_user": _from_user_info(message.from_user),
            })
        elif state == "agreed":
            log.info("клиент вернулся в личку", user_id=user_id)
            await clear_user(user_id)
            await set_state(user_id, "pitching")
            await publish(_mq_connection, QUEUE_INCOMING, {
                "user_id": user_id,
                "text": message.text,
                "is_opening": True,
                "is_returning": True,
                "is_direct_dm": True,
                "from_user": _from_user_info(message.from_user),
            })
        elif not state:
            log.info("новый диалог из лички", user_id=user_id)
            await set_state(user_id, "pitching")
            await publish(_mq_connection, QUEUE_INCOMING, {
                "user_id": user_id,
                "text": message.text,
                "is_opening": True,
                "is_returning": False,
                "is_direct_dm": True,
                "from_user": _from_user_info(message.from_user),
            })

    @app.on_message(monitored_chat & ~filters.me, group=1)
    async def on_monitored_user(client: Client, message: Message):
        asyncio.create_task(_log_seen_user(message))

    @app.on_message(filters.group & ~filters.me, group=1)
    async def on_any_group(client: Client, message: Message):
        asyncio.create_task(_log_seen_chat(message))

    @app.on_message(filters.channel & ~filters.me, group=1)
    async def on_any_channel(client: Client, message: Message):
        asyncio.create_task(_log_seen_channel(client, message))
