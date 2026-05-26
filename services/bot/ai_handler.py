import structlog
from state import get_state, set_state, get_history, append_history, save_user_info
from ai_client import generate_reply, is_agreement
import rag
import user_profile

log = structlog.get_logger()


async def process_message(payload: dict) -> dict:
    """Обработать входящее сообщение и вернуть ответ."""
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
                log.info("сделка закрыта", user_id=user_id)
                return {
                    "user_id": user_id,
                    "text": "Отлично! Наш менеджер свяжется с вами в ближайшее время. Спасибо!",
                    "notify_admin": True,
                    "admin_text": admin_text,
                    "admin_parse_mode": "html",
                }

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
        log.info("ответ сгенерирован", user_id=user_id, is_opening=is_opening)
        return {
            "user_id": user_id,
            "text": reply,
            "notify_admin": False,
            "admin_text": "",
            "admin_parse_mode": "",
        }

    except Exception as e:
        log.error("ошибка обработки сообщения", user_id=user_id, error=str(e))
        return {
            "user_id": user_id,
            "text": "Я чуть-чуть сломался и не могу ответить прямо сейчас. Напишите ещё раз — попробую снова.",
            "notify_admin": False,
            "admin_text": "",
            "admin_parse_mode": "",
        }
