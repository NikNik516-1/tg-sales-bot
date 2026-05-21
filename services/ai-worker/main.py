import asyncio
import structlog
from logger import setup
from state import get_state, set_state, get_history, append_history, save_user_info
from ai_client import generate_reply, is_agreement
from mq import get_connection, publish, consume, QUEUE_INCOMING, QUEUE_OUTGOING
from config import ADMIN_TG_ID
import rag
import metrics
import user_profile

log = setup("ai-worker")


async def process_message(payload: dict) -> None:
    user_id = payload["user_id"]
    text = payload["text"]
    is_opening = payload.get("is_opening", False)
    is_returning = payload.get("is_returning", False)
    is_direct_dm = payload.get("is_direct_dm", False)
    from_user = payload.get("from_user", {})

    try:
        history = await get_history(user_id)

        if not is_opening:
            agreed = await is_agreement(text, history)
            if agreed:
                await append_history(user_id, "user", text)
                await set_state(user_id, "agreed")
                name = f"{from_user.get('first_name', '')} {from_user.get('last_name', '')}".strip()
                username = from_user.get("username") or ""
                phone = from_user.get("phone") or ""
                admin_text = (
                    f"✅ Покупатель согласился!\n\n"
                    f"Имя: <a href=\"tg://user?id={user_id}\">{name or str(user_id)}</a>\n"
                    f"Username: @{username or '—'}\n"
                    f"ID: <code>{user_id}</code>"
                )
                if phone:
                    admin_text += f"\nТелефон: {phone}"
                await _publish_response(
                    user_id,
                    "Отлично! Наш менеджер свяжется с вами в ближайшее время. Спасибо!",
                    notify_admin=True,
                    admin_text=admin_text,
                    admin_parse_mode="html",
                )
                log.info("сделка закрыта", user_id=user_id)
                return

        profile = user_profile.lookup(
            username=from_user.get("username", ""),
            phone=from_user.get("phone", ""),
            user_id=user_id,
        )

        rag_docs = rag.search(text)
        rag_context = "\n---\n".join(rag_docs)
        reply = await generate_reply(
            user_message=text,
            history=history,
            rag_context=rag_context,
            is_opening=is_opening,
            is_returning=is_returning,
            user_profile=profile,
        )

        if is_opening:
            await save_user_info(
                user_id,
                username=from_user.get("username", ""),
                first_name=from_user.get("first_name", ""),
                last_name=from_user.get("last_name", ""),
            )
            if is_direct_dm:
                await append_history(user_id, "user", text)
            else:
                await append_history(user_id, "user", f"[Группа] {text}")
                trigger_preview = text[:200] + ("…" if len(text) > 200 else "")
                reply = f"Увидел, что вы писали: «{trigger_preview}»\n\n{reply}"
        else:
            await append_history(user_id, "user", text)

        await append_history(user_id, "assistant", reply)
        await _publish_response(user_id, reply)
        log.info("ответ сгенерирован", user_id=user_id, is_opening=is_opening)

    except Exception as e:
        log.error("ошибка обработки сообщения", user_id=user_id, error=str(e))
        metrics.messages_errors_total.inc()
        await _publish_response(user_id, "Я чуть-чуть сломался и не могу ответить прямо сейчас. Напишите ещё раз — попробую снова.")
        return

    metrics.messages_processed_total.inc()


_mq_connection = None


async def _publish_response(user_id: int, text: str, notify_admin: bool = False, admin_text: str = "", admin_parse_mode: str = "") -> None:
    await publish(_mq_connection, QUEUE_OUTGOING, {
        "user_id": user_id,
        "text": text,
        "notify_admin": notify_admin,
        "admin_text": admin_text,
        "admin_parse_mode": admin_parse_mode,
    })


async def main():
    global _mq_connection

    metrics.start(9090)

    log.info("инициализация RAG")
    rag.init()
    user_profile.load()

    log.info("подключение к RabbitMQ")
    _mq_connection = await get_connection()

    asyncio.create_task(
        metrics.poll_queue_lengths(_mq_connection, [QUEUE_INCOMING, QUEUE_OUTGOING])
    )

    log.info("ai-worker готов")
    await consume(_mq_connection, QUEUE_INCOMING, process_message)


if __name__ == "__main__":
    asyncio.run(main())
