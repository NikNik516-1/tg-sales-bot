# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Telegram sales bot: слушает сообщения в заданных группах/каналах, при появлении ключевой фразы пишет автору в личку и ведёт продажу через GPT. При согласии клиента уведомляет администратора. Работает на пользовательском MTProto-аккаунте (не бот).

## Структура проекта

```
services/
  listener/     — Pyrogram singleton: читает Telegram, публикует события в RabbitMQ
  ai-worker/    — потребляет очередь, вызывает GPT+RAG, публикует ответы
  admin/        — FastAPI веб-админка (порт 8082 на хосте)
shared/         — общий код: config.py, state.py, mq.py (копируется в каждый образ)
app/            — монолитная версия (сохранена для истории, не используется)
data/knowledge_base/  — txt-файлы для RAG
scripts/        — generate_session.py, ingest.py
k8s/            — Kubernetes манифесты (Фаза 6)
.github/workflows/    — CI/CD пайплайны (Фаза 5)
```

## Docker (локальная разработка)

```bash
# Поднять весь стек
docker-compose up -d --build

# Пересобрать один сервис
docker-compose build listener && docker-compose up -d listener

# Логи сервиса в реальном времени
docker compose logs listener -f
docker compose logs ai-worker -f

# Сбросить состояние пользователя в Redis
docker exec clrosreestr-redis-1 redis-cli DEL "state:USER_ID" "history:USER_ID"
```

Порты (все привязаны к localhost): `8082` — веб-админка, `15672` — RabbitMQ Management UI (guest/guest), `8000` — ChromaDB.

## Загрузка базы знаний в ChromaDB

Запускать с хоста после того как ChromaDB уже запущен:

```bash
$env:CHROMA_HOST="localhost"; python scripts/ingest.py
```

Файлы базы знаний: `data/knowledge_base/*.txt`. После добавления/изменения файлов — перезапустить ingest.

## Получение строки сессии (один раз)

```bash
python scripts/generate_session.py
```

Скопировать вывод в `.env` → `TG_SESSION_STRING=`.

## Конфигурация (.env)

| Переменная | Описание |
|---|---|
| `TG_API_ID` / `TG_API_HASH` | MTProto credentials с my.telegram.org |
| `TG_SESSION_STRING` | Строка сессии Pyrogram (генерируется один раз) |
| `MONITORED_CHATS` | ID чатов через запятую. Если пусто — debug-режим |
| `KEYWORDS` | Ключевые фразы через запятую, поиск по вхождению (регистронезависимо) |
| `ADMIN_TG_ID` | TG user_id администратора |
| `RABBITMQ_URL` | По умолчанию `amqp://guest:guest@rabbitmq/` |
| `ROOT_PATH` | Prefix для FastAPI (на VPS: `/tg-sales-bot/adminka`; локально — пусто) |

## Архитектура микросервисов

**Поток сообщения:**
```
Telegram → listener → [RabbitMQ: tg.incoming] → ai-worker → [RabbitMQ: tg.outgoing] → listener → Telegram DM
```

**Очереди RabbitMQ (durable):**
- `tg.incoming` — событие из Telegram: `{user_id, text, is_opening, from_user}`
- `tg.outgoing` — ответ для отправки: `{user_id, text, notify_admin, admin_text}`

**shared/ — общий код для всех сервисов:**
- `config.py` — все переменные из .env, включая `RABBITMQ_URL`
- `state.py` — Redis: `state:{id}`, `history:{id}` (TTL 24ч), `user_info:{id}` (TTL 30д)
- `mq.py` — `get_connection()`, `publish()`, `consume()` на aio-pika

**listener важно:** singleton, нельзя масштабировать — одна Pyrogram-сессия на процесс. `ai-worker` можно запускать в нескольких репликах.

**Pyrogram важно:** обработчики в одной группе (group=0) взаимно исключают друг друга. `group=1` — параллельные обработчики для логирования.

## Промпты

`services/ai-worker/ai_client.py` — оба промпта правятся напрямую в коде:
- `_SYSTEM_SALES` — инструкция продавцу (уточнить → предложить → выбрать → закрыть)
- `_SYSTEM_JUDGE` — детектор согласия: "любую", "недорогую", "ок" — не согласие

## ChromaDB

Версия образа использует `/api/v2/`. Health check: `bash -c "echo > /dev/tcp/localhost/8000"` — curl и python недоступны внутри образа.

## Git-ветки

- `main` — стабильный прод, только через PR
- `dev` — текущая разработка

## Deploy

**Сервер:** `77.83.87.29` (claude@), директория `/var/develop/tg-sales-bot/`

**Первый деплой:**
```bash
# На сервере
git clone -b dev https://github.com/NikNik516-1/tg-sales-bot.git /var/develop/tg-sales-bot
# Создать .env (не в git) с ROOT_PATH=/tg-sales-bot/adminka
cd /var/develop/tg-sales-bot && docker compose up -d --build
# Загрузить базу знаний
CHROMA_HOST=localhost python3 scripts/ingest.py
```

**Обновление:**
```bash
cd /var/develop/tg-sales-bot
git pull origin dev
docker compose up -d --build
```

**Nginx:** добавлен location в `/etc/nginx/sites-enabled/antilopa-gnu-ru.conf`:
- `https://antilopa-gnu.ru/tg-sales-bot/adminka/` → `http://127.0.0.1:8082/`
