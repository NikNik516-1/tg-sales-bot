import asyncio
import structlog
from logger import setup
from state import get_state, set_state, get_history, append_history, save_user_info
from ai_client import generate_reply, is_agreement
from mq import get_connection, publish, consume, QUEUE_INCOMING, QUEUE_OUTGOING
from config import ADMIN_TG_ID
import rag

log = setup("ai-worker")


async def process_message(payload: dict) -> None:
    user_id = payload["user_id"]
    text = payload["text"]
    is_opening = payload.get("is_opening", False)
    from_user = payload.get("from_user", {})

    try:
        history = await get_history(user_id)

        if not is_opening:
            agreed = await is_agreement(text, history)
            if agreed:
                await append_history(user_id, "user", text)
                await set_state(user_id, "agreed")
                name = f"{from_user.get('first_name', '')} {from_user.get('last_name', '')}".strip()
                admin_text = (
                    f"✅ Покупатель согласился!\n\n"
                    f"Имя: {name}\n"
                    f"Username: @{from_user.get('username') or '—'}\n"
                    f"ID: {user_id}"
                )
                await _publish_response(user_id, "Отлично! Наш менеджер свяжется с вами в ближайшее время. Спасибо!", notify_admin=True, admin_text=admin_text)
                log.info("сделка закрыта", user_id=user_id)
                return

        rag_docs = rag.search(text)
        rag_context = "\n---\n".join(rag_docs)
        reply = await generate_reply(
            user_message=text,
            history=history,
            rag_context=rag_context,
            is_opening=is_opening,
        )

        if is_opening:
            await save_user_info(
                user_id,
                username=from_user.get("username", ""),
                first_name=from_user.get("first_name", ""),
                last_name=from_user.get("last_name", ""),
            )
            await append_history(user_id, "user", f"[Группа] {text}")
        else:
            await append_history(user_id, "user", text)

        await append_history(user_id, "assistant", reply)
        await _publish_response(user_id, reply)
        log.info("ответ сгенерирован", user_id=user_id, is_opening=is_opening)

    except Exception as e:
        log.error("ошибка обработки сообщения", user_id=user_id, error=str(e))
        await _publish_response(user_id, "Я чуть-чуть сломался и не могу ответить прямо сейчас. Напишите ещё раз — попробую снова.")


_mq_connection = None


async def _publish_response(user_id: int, text: str, notify_admin: bool = False, admin_text: str = "") -> None:
    await publish(_mq_connection, QUEUE_OUTGOING, {
        "user_id": user_id,
        "text": text,
        "notify_admin": notify_admin,
        "admin_text": admin_text,
    })


async def main():
    global _mq_connection

    log.info("инициализация RAG")
    rag.init()

    log.info("подключение к RabbitMQ")
    _mq_connection = await get_connection()

    log.info("ai-worker готов")
    await consume(_mq_connection, QUEUE_INCOMING, process_message)


if __name__ == "__main__":
    asyncio.run(main())
