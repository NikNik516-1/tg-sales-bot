# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Telegram sales bot: слушает сообщения в заданных группах/каналах, при появлении ключевой фразы (например, "хочу купить ручку") пишет автору в личку и ведёт продажу через GPT. При согласии клиента уведомляет администратора. Работает на пользовательском MTProto-аккаунте (не бот), что позволяет писать в личку без предварительного /start.

## Docker

```bash
# Поднять инфраструктуру (ChromaDB + Redis)
docker-compose up -d chromadb redis

# Собрать и запустить всё
docker-compose up -d --build app

# Пересоздать app без пересборки (после изменения .env)
docker-compose up -d app

# Логи в реальном времени
docker logs clrosreestr-app-1 -f

# Сбросить состояние пользователя в Redis (замените ID)
docker exec clrosreestr-redis-1 redis-cli DEL "state:USER_ID" "history:USER_ID"
```

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
| `MONITORED_CHATS` | ID чатов через запятую. Если пусто — debug-режим: логирует chat_id всех входящих сообщений |
| `KEYWORDS` | Ключевые фразы через запятую, поиск по вхождению подстроки (регистронезависимо) |
| `ADMIN_TG_ID` | TG user_id администратора, которому приходит уведомление о сделке |

## Веб-админка

Доступна на `http://localhost:8080` после запуска контейнера.

- **Диалоги** — активные пользователи, статус (pitching/agreed), превью последнего сообщения, кнопка сброса
- **История** — полный лог переписки с пользователем
- **Группы** — список мониторируемых групп; кнопка убрать/добавить без перезапуска; таблица "замеченных" групп (где аккаунт состоит, но не мониторирует) — нажать "Мониторить" чтобы добавить

Список мониторируемых групп хранится в Redis (`monitored_chats`). При старте загружается из Redis; если Redis пуст — инициализируется из `MONITORED_CHATS` в `.env`.

## Архитектура

```
listener.py      — Pyrogram-обработчики: on_keyword, on_private, on_reset, on_any_group (логирование)
ai_client.py     — два промпта: _SYSTEM_SALES (порядок продажи) и _SYSTEM_JUDGE (детектор согласия)
rag.py           — ChromaDB HttpClient, поиск топ-3 фрагментов по запросу
state.py         — Redis: state:{user_id} и history:{user_id}, TTL 24ч
chat_manager.py  — динамический список групп: in-memory set + Redis set "monitored_chats"
admin_server.py  — FastAPI: /  /history/{id}  /groups  /groups/add  /groups/remove
config.py        — все настройки из .env
```

**Поток сообщения из группы:**
1. `listener.on_keyword` → проверить state в Redis → запросить RAG → GPT → DM пользователю
2. `listener.on_private` → каждый ответ в личке → `is_agreement()` → если yes: уведомить админа, иначе RAG + GPT → ответить

**Pyrogram важно:** обработчики в одной группе (group=0) взаимно исключают друг друга — первый совпавший выигрывает. Не добавлять `filters.all` в ту же группу — перехватит все сообщения.

## Промпты

`app/ai_client.py` — оба промпта правятся напрямую в коде:
- `_SYSTEM_SALES` — инструкция продавцу, включая обязательный порядок этапов (уточнить → предложить модели → выбрать → закрыть)
- `_SYSTEM_JUDGE` — строгий детектор согласия: "любую", "недорогую", "ок" — не считаются согласием

## ChromaDB

Версия образа использует `/api/v2/` (v1 deprecated). Health check через `bash -c "echo > /dev/tcp/localhost/8000"` — curl и python недоступны внутри образа.
