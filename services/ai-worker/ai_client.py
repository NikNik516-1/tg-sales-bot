import time
from openai import AsyncOpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL
import metrics
import prompts

_client = AsyncOpenAI(api_key=OPENAI_API_KEY)


async def generate_reply(
    user_message: str,
    history: list[dict],
    rag_context: str,
    is_opening: bool = False,
    is_returning: bool = False,
    user_profile: str = "",
) -> str:
    context_block = f"\n\nБаза знаний:\n{rag_context}" if rag_context else ""
    profile_block = f"\n\nПрофиль клиента:\n{user_profile}" if user_profile else ""
    messages = [{"role": "system", "content": prompts.get_sales() + context_block + profile_block}]
    messages.extend({"role": m["role"], "content": m["content"]} for m in history[-12:])

    if is_opening:
        if is_returning:
            content = (
                f"Пользователь снова написал в группе: «{user_message}».{profile_block}\n"
                "Он уже был клиентом — ты с ним уже работал и он делал покупку. "
                "Напиши радостное приветственное сообщение в личку: порадуйся возвращению, "
                "можно с лёгким юмором. Затем предложи помочь с выбором."
            )
        else:
            if user_profile:
                content = (
                    f"Пользователь написал в группе: «{user_message}».\n\n"
                    f"Профиль клиента:\n{user_profile}\n\n"
                    "Напиши первое сообщение в личку. Правила:\n"
                    "1. Обращайся по имени-отчеству (если оба есть в профиле) — не просто по имени.\n"
                    "2. ОБЯЗАТЕЛЬНО сделай одну юмористическую фразу, обыгрывающую конкретный факт из профиля. "
                    "Фраза должна быть связана с ручками или покупкой — это твой крючок.\n"
                    "3. После шутки представься как «Фёдор, менеджер по продажам» и предложи помочь с выбором ручки.\n"
                    "Не перегружай — всё сообщение 3–4 предложения."
                )
            else:
                content = (
                    f"Пользователь написал в группе: «{user_message}».\n"
                    "Это твой шанс начать продажу — напиши первое сообщение в личку. "
                    "Представься как «Фёдор, менеджер по продажам» и предложи помочь с выбором ручки."
                )
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": user_message})

    t0 = time.monotonic()
    try:
        response = await _client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
        )
        return response.choices[0].message.content.strip()
    finally:
        metrics.gpt_response_seconds.labels(call="reply").observe(time.monotonic() - t0)


async def is_agreement(user_message: str, history: list[dict]) -> bool:
    messages = [{"role": "system", "content": prompts.get_judge()}]
    messages.extend({"role": m["role"], "content": m["content"]} for m in history[-8:])
    messages.append({
        "role": "user",
        "content": f"Последнее сообщение: «{user_message}». Пользователь согласился купить?",
    })

    t0 = time.monotonic()
    try:
        response = await _client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
        )
        return response.choices[0].message.content.strip().lower().startswith("yes")
    finally:
        metrics.gpt_response_seconds.labels(call="judge").observe(time.monotonic() - t0)
