import json
from datetime import datetime, timezone
import asyncio

import redis.asyncio as aioredis
from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import Message
from pyrogram.errors import UserIsBlocked, InputUserDeactivated, PeerIdInvalid

from config import ADMIN_TG_ID, REDIS_HOST, REDIS_PORT
from state import get_state, set_state, get_history, append_history, clear_user, save_user_info
from rag import search
from ai_client import generate_reply, is_agreement
import chat_manager


def _in_monitored_chat(_, __, message: Message) -> bool:
    chats = chat_manager.get()
    if not chats:
        print(f"[DEBUG] chat_id={message.chat.id}  username={message.chat.username}")
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


async def _send_safe(client: Client, user_id: int, text: str) -> bool:
    try:
        await client.send_message(user_id, text)
        return True
    except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid) as e:
        print(f"[DM] Не удалось отправить {user_id}: {e}")
        return False


async def _continue_dialog(client: Client, user_id: int, text: str, from_user) -> None:
    """Обрабатывает сообщение от пользователя, который уже в диалоге."""
    try:
        history = await get_history(user_id)
        # Сохраняем в историю только после успешного ответа,
        # чтобы ошибка не оставляла сиротское сообщение без пары.

        agreed = await is_agreement(text, history)
        if agreed:
            await append_history(user_id, "user", text)
            await set_state(user_id, "agreed")
            name = f"{from_user.first_name or ''} {from_user.last_name or ''}".strip()
            admin_text = (
                f"✅ Покупатель согласился!\n\n"
                f"Имя: {name}\n"
                f"Username: @{from_user.username or '—'}\n"
                f"ID: {from_user.id}"
            )
            await _send_safe(client, ADMIN_TG_ID, admin_text)
            await _send_safe(client, user_id, "Отлично! Наш менеджер свяжется с вами в ближайшее время. Спасибо!")
            print(f"[SALE] Сделка с user_id={user_id}")
            return

        rag_docs = search(text)
        rag_context = "\n---\n".join(rag_docs)
        reply = await generate_reply(
            user_message=text,
            history=history,
            rag_context=rag_context,
        )
        # Оба сообщения сохраняем только после успешной генерации
        await append_history(user_id, "user", text)
        await append_history(user_id, "assistant", reply)
        await _send_safe(client, user_id, reply)
    except Exception as e:
        print(f"[ERROR] _continue_dialog user_id={user_id}: {e}")
        await _send_safe(client, user_id, "Я чуть-чуть сломался и не могу ответить прямо сейчас. Напишите ещё раз — попробую снова.")


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
        print(f"[CHANNEL] Не удалось получить linked_chat для {channel_id}: {e}")

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


def register(app: Client):

    @app.on_message(monitored_chat & has_keyword & ~filters.me)
    async def on_keyword(client: Client, message: Message):
        user_id = message.from_user.id
        state = await get_state(user_id)

        if state == "pitching":
            # Уже в диалоге — продолжаем разговор вместо игнорирования
            print(f"[KEYWORD] продолжение диалога user_id={user_id} текст={repr(message.text)}")
            await _continue_dialog(client, user_id, f"[Группа] {message.text}", message.from_user)
            return

        if state:
            # agreed или другое финальное состояние — молчим
            return

        # Новый пользователь — открываем диалог
        print(f"[KEYWORD] новый user_id={user_id} текст={repr(message.text)}")
        try:
            rag_docs = search(message.text)
            rag_context = "\n---\n".join(rag_docs)
            opening = await generate_reply(
                user_message=message.text,
                history=[],
                rag_context=rag_context,
                is_opening=True,
            )
        except Exception as e:
            print(f"[ERROR] on_keyword генерация user_id={user_id}: {e}")
            return

        ok = await _send_safe(client, user_id, opening)
        if not ok:
            return

        await set_state(user_id, "pitching")
        await save_user_info(
            user_id,
            username=message.from_user.username or "",
            first_name=message.from_user.first_name or "",
            last_name=message.from_user.last_name or "",
        )
        await append_history(user_id, "user", f"[Группа] {message.text}")
        await append_history(user_id, "assistant", opening)
        print(f"[SALE] Начат диалог с user_id={user_id}")

    @app.on_message(filters.private & filters.command("reset") & ~filters.me)
    async def on_reset(client: Client, message: Message):
        user_id = message.from_user.id
        await clear_user(user_id)
        await message.reply("Диалог сброшен. Можете начать заново.")
        print(f"[RESET] user_id={user_id}")

    @app.on_message(filters.private & ~filters.me)
    async def on_private(client: Client, message: Message):
        if not message.text:
            return
        user_id = message.from_user.id
        state = await get_state(user_id)
        if state != "pitching":
            return
        await _continue_dialog(client, user_id, message.text, message.from_user)

    # Логируем все группы где есть аккаунт (group=1 — не мешает основным обработчикам)
    @app.on_message(filters.group & ~filters.me, group=1)
    async def on_any_group(client: Client, message: Message):
        asyncio.create_task(_log_seen_chat(message))

    # Логируем все каналы где состоит аккаунт
    @app.on_message(filters.channel & ~filters.me, group=1)
    async def on_any_channel(client: Client, message: Message):
        asyncio.create_task(_log_seen_channel(client, message))
