# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Telegram sales bot: слушает сообщения в заданных группах/каналах, при появлении ключевой фразы пишет автору в личку и ведёт продажу через GPT. При согласии клиента уведомляет администратора. Работает на пользовательском MTProto-аккаунте (не бот).

## Структура проекта

```
services/
  bot/          — основной сервис: Pyrogram + GPT + RAG (listener + ai-worker в одном процессе)
  admin/        — FastAPI веб-админка (порт 8082 на хосте) + static/favicon.png
shared/         — общий код: config.py, state.py, logger.py (копируется в каждый образ)
app/            — монолитная версия (сохранена для истории, не используется)
data/knowledge_base/  — txt-файлы для RAG
data/images/    — иконки и изображения (favicon и т.п.)
scripts/        — generate_session.py, ingest.py
tests/          — pytest: test_keywords.py, test_timestamp.py, test_chat_manager.py
.github/workflows/    — ci.yml (lint+test+build), deploy.yml (push GHCR + SSH деплой)
```

## Docker (локальная разработка)

```bash
# Поднять весь стек
docker-compose up -d --build

# Пересобрать один сервис
docker-compose build bot && docker-compose up -d bot

# Логи сервиса в реальном времени
docker compose logs bot -f
docker compose logs admin -f

# Сбросить состояние пользователя в Redis
docker exec cl_tg-sales-bot-redis-1 redis-cli DEL "state:USER_ID" "history:USER_ID"
```

Порты (все привязаны к localhost): `8082` — веб-админка, `8000` — ChromaDB.

## Загрузка базы знаний в ChromaDB

Актуальный способ — кнопка «Переиндексировать» на странице **База знаний** веб-админки (или `POST /knowledge/reindex`). Реализация — `_run_ingest()` в `services/admin/admin_server.py`: удаляет и заново создаёт коллекцию `sales_knowledge` через `DefaultEmbeddingFunction` (локальная ONNX-модель, без внешних API), режет `data/knowledge_base/*.txt` по параграфам (кроме `users.txt` и `sales_scripts.txt`). После реиндекса нужно перезапустить `bot`-контейнер (`docker restart cl_tg-sales-bot-bot-1`) — иначе `rag.py` держит ссылку на старый (уже удалённый) ID коллекции и падает с `Collection ... does not exist.`

`scripts/ingest.py` — устаревший скрипт (использует `OpenAIEmbeddingFunction`, требует `OPENAI_API_KEY`, не совпадает по embedding-функции с `rag.py`). Не использовать, конфликтует с коллекцией, созданной через reindex.

Файлы базы знаний: `data/knowledge_base/*.txt`. После добавления/изменения файлов — переиндексировать через админку.

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
| `ROOT_PATH` | Prefix для FastAPI (на VPS: `/tg-sales-bot/adminka`; локально — пусто) |

## Архитектура

**Поток сообщения:**
```
Telegram → bot (listener.py) → ai_handler.process_message() → bot (handle_outgoing) → Telegram DM
```

**bot — единый сервис (`services/bot/`):**
- `listener.py` — Pyrogram-обработчики, при триггере запускает `asyncio.create_task(_process_and_send(...))`
- `ai_handler.py` — вызывает GPT+RAG, возвращает dict с ответом
- `ai_client.py` — OpenAI API
- `rag.py` — ChromaDB поиск
- `prompts.py` — загрузка промптов с кэшем по mtime
- `user_profile.py` — профили клиентов из users.txt
- `chat_manager.py` — список мониторируемых чатов из Redis

**shared/ — общий код для всех сервисов:**
- `config.py` — все переменные из .env
- `state.py` — Redis: `state:{id}`, `history:{id}`, `user_info:{id}` (TTL 30д)
- `logger.py` — structlog конфигурация

**Pyrogram важно:** обработчики в одной группе (group=0) взаимно исключают друг друга. `group=1` — параллельные обработчики для логирования.

## Промпты

Промпты вынесены из кода в файлы и редактируются через веб-админку без перезапуска:

- `data/prompts/sales_prompt.txt` — инструкция продавцу
- `data/prompts/judge_prompt.txt` — детектор согласия

`services/bot/prompts.py` — загружает файлы с кэшированием по mtime (один `stat()` на вызов, нет I/O если файл не изменился). Если файл отсутствует — использует встроенный дефолт.

Веб-админка: страница **Промпты** (`/prompts`) — два таба, изменения применяются без деплоя.

## Профили клиентов

`data/knowledge_base/users.txt` — не в git (личные данные), копировать вручную.

Форматы идентификаторов (первая строка блока, блоки разделены пустой строкой):
```
@username
Имя Отчество
Факты через запятую или произвольно

mobile: +79001234567
Имя Отчество
Факты

id: 7593958387
Имя Отчество
Факты
```

Приоритет поиска в `user_profile.lookup()`: `id:` → `@username` → `mobile:`.

Профиль передаётся в системный промпт GPT на **каждом** сообщении (не только при открытии диалога).

## ChromaDB

Версия образа использует `/api/v2/`. Health check: `bash -c "echo > /dev/tcp/localhost/8000"` — curl и python недоступны внутри образа.

## Git-ветки

- `main` — стабильный прод, только через PR
- `dev` — текущая разработка

## Создание и мержинг PR

`gh` CLI установлен (`winget install GitHub.cli`), путь: `C:\Program Files\GitHub CLI\gh.exe`.
В PowerShell доступен как `gh` после рестарта VS Code (PATH обновляется из реестра).
В Git Bash PATH не подхватывается автоматически — использовать полный путь:
`"/c/Program Files/GitHub CLI/gh.exe"`.

Первый раз — авторизация:
```bash
gh auth login   # выбрать GitHub.com → HTTPS → Login with a web browser
```

После авторизации создание PR и мерж в одну команду:
```bash
# Создать PR (dev → main)
gh pr create --title "feat: ..." --body "## Summary\n..."

# Смержить (объединить dev в main → запустится деплой)
gh pr merge <номер> --merge

# Или сразу после создания:
gh pr create --title "..." --body "..." && gh pr merge --merge
```

**Смержить** = слить ветку `dev` в `main`. После этого GitHub Actions автоматически собирает образы и деплоит на VPS.

## CI/CD

**Обычный цикл разработки:**
```
git commit + git push origin dev
  → gh pr create --title "..." --body "..."
  → gh pr merge <номер> --merge
  → CI+deploy: ruff · pytest · docker build · push GHCR · SSH на VPS → docker compose up
```

**GitHub Actions:**
- `ci.yml` — запускается на каждый push/PR: lint, tests, docker build
- `deploy.yml` — только при merge в `main`: пушит образы в GHCR, деплоит на VPS по SSH

**GHCR образы:**
```
ghcr.io/niknik516-1/tg-sales-bot/bot:latest
ghcr.io/niknik516-1/tg-sales-bot/admin:latest
```

**Секреты GitHub** (уже настроены):
- `DEPLOY_SSH_KEY` — Ed25519 приватный ключ для SSH на VPS (публичная часть в `~/.ssh/authorized_keys`)
- `GITHUB_TOKEN` — автоматически, для push в GHCR

**Запуск тестов локально:**
```bash
pip install -r requirements-dev.txt
pytest -v
```

## Deploy

**Сервер:** `81.177.166.233` (сервер 6, claude@), директория `/var/develop/tg-sales-bot/`. **Перенесено с сервера 2 (`178.212.13.182`) 2026-07-16** — старое место на сервере 2 остановлено (`docker compose down`, nginx-сайт снят), но пока не удалено (наблюдение перед полной очисткой).

**Обновление — через CI/CD (автоматически):**
Смержить PR в `main` → GitHub Actions задеплоит сам (`DEPLOY_SSH_KEY` указывает на сервер 6).

**Обновление — вручную:**
```bash
cd /var/develop/tg-sales-bot
git pull origin main
docker compose pull
docker compose up -d
```

**Nginx:** сервер 6 использует SNI-split (`stream` на публичном 443 → внутренний nginx `127.0.0.1:8081`, порт 80 напрямую). Конфиг `/etc/nginx/sites-enabled/begindialog.conf`:
- `https://begindialog.ru/adminka/` → `http://127.0.0.1:8082/`
- `https://begindialog.ru/api/v1/contact` (форма лендинга) → `https://www.radar-novostroek.ru/api/v1/contact` (проксируется на сервер 2, где остаётся `nedvizbot-api` — та же схема, что у `bot_max`)

**ROOT_PATH:** `/adminka` (в .env на сервере)

**SOCKS5-прокси (Telegram + OpenAI):** провайдер сервера 6 блокирует прямой доступ к Telegram и OpenAI, тоннель через сервер 4 (Amsterdam):
- systemd: `autossh-socks5.service` (active на сервере 6), слушает `0.0.0.0:1080` (расширено с `127.0.0.1:1080` при переезде — этот же туннель используется и парсером ObligationRating)
- из Docker-контейнера: `host.docker.internal:1080`
- env (в .env на сервере):
  - `TG_PROXY_HOST=host.docker.internal`, `TG_PROXY_PORT=1080` — для Pyrogram
  - `HTTPS_PROXY=socks5h://host.docker.internal:1080` — для OpenAI SDK (httpx)
- UFW: `allow from 172.16.0.0/12 to any port 1080` (Docker → хост)
- `docker-compose.yml`: `extra_hosts: host.docker.internal:host-gateway` для сервиса bot

## Сбор пользователей из мониторируемых групп

bot логирует всех авторов сообщений из мониторируемых групп в Redis-хэш `seen_users` (один раз на пользователя, через `hsetnx`). Хранит: `user_id`, `username`, `first_name`, `last_name`, `chat_id`, `chat_title`, `first_seen`.

Веб-админка: страница **Пользователи** (`/seen-users`) — таблица с поиском и экспортом CSV. Использовать для пополнения `users.txt`.

## Лендинг

Проект посадочной страницы находится в `C:\Delete\cl_tg-sales-landing\` (отдельный репозиторий).
Концепция и текстовый контент лендинга — `LANDING.md` в этом репозитории.

## SSH-реквизиты

Пароль, plink-команды и параметры сервера — в `C:\delete\claudedevops\CLAUDE.md`.
Не хранить credentials в этом репозитории.
