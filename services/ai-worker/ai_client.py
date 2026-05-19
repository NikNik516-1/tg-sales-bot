import time
from openai import AsyncOpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL
import metrics

_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

_SYSTEM_SALES = """Ты — дружелюбный менеджер по продажам магазина ручек "ПенШоп".
Твоя цель — провести клиента через все этапы и закрыть конкретную сделку.

Обязательный порядок этапов:
1. Уточни потребность: для кого (себе/подарок), тип (шариковая/гелевая/перьевая), бюджет.
2. Предложи 2–3 конкретные модели из каталога с ценами. Дай краткое описание каждой.
3. Помоги выбрать одну модель, работай с возражениями.
4. Только после того как клиент остановился на конкретной модели — закрывай сделку ("Оформляем?").

Правила:
- Не переходи к закрытию, пока клиент не выбрал конкретную модель.
- Общие фразы ("любую", "недорогую") — повод уточнить и назвать конкретные варианты с ценами.
- Отвечай кратко — не более 4 предложений. Будь живым, не роботом."""

_SYSTEM_JUDGE = """Определи, дал ли пользователь явное согласие на покупку КОНКРЕТНОГО товара.

Это НЕ согласие (ответь no):
- выражение предпочтений: "любую", "недорогую", "что-нибудь попроще"
- общие положительные реакции без конкретики: "ок", "хорошо", "понятно", "интересно"
- вопросы об ассортименте или характеристиках

Это согласие (ответь yes):
- явное "беру [модель]", "оформляй", "давай [модель]", "согласен", "договорились"
- запрос реквизитов или способа оплаты: "как оплатить", "куда переводить", "пришли счёт"
- вопрос о доставке конкретного заказа: "когда привезут", "как получить"
- фразы типа "уговорил", "убедил", "с тобой не поспоришь" после презентации конкретной модели

Ответь строго одним словом: yes или no."""


async def generate_reply(
    user_message: str,
    history: list[dict],
    rag_context: str,
    is_opening: bool = False,
    is_returning: bool = False,
    user_profile: str = "",
) -> str:
    context_block = f"\n\nБаза знаний:\n{rag_context}" if rag_context else ""
    messages = [{"role": "system", "content": _SYSTEM_SALES + context_block}]
    messages.extend({"role": m["role"], "content": m["content"]} for m in history[-12:])

    if is_opening:
        profile_block = f"\n\nПрофиль клиента:\n{user_profile}" if user_profile else ""
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
                    "3. После шутки представься как «личный помощник Николая» и предложи помочь с выбором ручки.\n"
                    "Не перегружай — всё сообщение 3–4 предложения."
                )
            else:
                content = (
                    f"Пользователь написал в группе: «{user_message}».\n"
                    "Это твой шанс начать продажу — напиши первое сообщение в личку. "
                    "Представься как «личный помощник Николая» и предложи помочь с выбором ручки."
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
    messages = [{"role": "system", "content": _SYSTEM_JUDGE}]
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
