# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Telegram sales bot: слушает сообщения в заданных группах/каналах, при появлении ключевой фразы пишет автору в личку и ведёт продажу через GPT. При согласии клиента уведомляет администратора. Работает на пользовательском MTProto-аккаунте (не бот).

## Структура проекта

```
services/
  listener/     — Pyrogram singleton: читает Telegram, публикует события в RabbitMQ
  ai-worker/    — потребляет очередь, вызывает GPT+RAG, публикует ответы
  admin/        — FastAPI веб-админка (порт 8082 на хосте) + static/favicon.png
shared/         — общий код: config.py, state.py, mq.py (копируется в каждый образ)
app/            — монолитная версия (сохранена для истории, не используется)
data/knowledge_base/  — txt-файлы для RAG
data/images/    — иконки и изображения (favicon и т.п.)
scripts/        — generate_session.py, ingest.py
tests/          — pytest: test_keywords.py, test_timestamp.py, test_chat_manager.py
k8s/            — Kubernetes манифесты (Фаза 6)
.github/workflows/    — ci.yml (lint+test+build), deploy.yml (push GHCR + SSH деплой)
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

Порты (все привязаны к localhost): `8082` — веб-админка, `15672` — RabbitMQ Management UI (guest/guest), `8000` — ChromaDB, `9090` — Prometheus, `3001` — Grafana.

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

Промпты вынесены из кода в файлы и редактируются через веб-админку без перезапуска:

- `data/prompts/sales_prompt.txt` — инструкция продавцу
- `data/prompts/judge_prompt.txt` — детектор согласия

`services/ai-worker/prompts.py` — загружает файлы с кэшированием по mtime (один `stat()` на вызов, нет I/O если файл не изменился). Если файл отсутствует — использует встроенный дефолт.

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

## CI/CD (Фаза 5)

**Обычный цикл разработки:**
```
git commit + git push origin dev
  → gh pr create --title "..." --body "..."
  → gh pr merge <номер> --merge
  → CI+deploy: ruff · pytest · docker build · push GHCR · SSH на VPS → kubectl apply
```

**GitHub Actions:**
- `ci.yml` — запускается на каждый push/PR: lint, tests, docker build
- `deploy.yml` — только при merge в `main`: пушит образы в GHCR, деплоит на VPS по SSH

**GHCR образы:**
```
ghcr.io/niknik516-1/tg-sales-bot/listener:latest
ghcr.io/niknik516-1/tg-sales-bot/ai-worker:latest
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

**Сервер:** `77.83.87.29` (claude@), директория `/var/develop/tg-sales-bot/`

**Текущий прод работает на k3s** (bootstrap выполнен). Docker-compose на VPS остановлен.

**Обновление — через CI/CD (автоматически):**
Смержить PR в `main` → GitHub Actions задеплоит сам (`kubectl apply -k k8s/ && rollout restart`).

**Обновление — вручную (если CI/CD недоступен):**
```bash
cd /var/develop/tg-sales-bot
git pull origin main
kubectl apply -k k8s/
kubectl rollout restart deployment/listener deployment/ai-worker deployment/admin -n tg-sales-bot
```

**Bootstrap нового сервера с нуля** (редкий случай — см. k8s-раздел ниже + `secret.template.yaml`).

**Nginx:** добавлен location в `/etc/nginx/sites-enabled/antilopa-gnu-ru.conf`:
- `https://antilopa-gnu.ru/tg-sales-bot/adminka/` → `http://127.0.0.1:8082/`
- `https://antilopa-gnu.ru/tg-sales-bot/prometheus/` → `http://127.0.0.1:9090/tg-sales-bot/prometheus/`
- `https://antilopa-gnu.ru/tg-sales-bot/grafana/` → `http://127.0.0.1:3001/tg-sales-bot/grafana/`

## Мониторинг (Фаза 7)

**Prometheus:** `https://antilopa-gnu.ru/tg-sales-bot/prometheus/` (без авторизации)
**Grafana:** `https://antilopa-gnu.ru/tg-sales-bot/grafana/` (анонимный просмотр; логин admin/admin)

Локально (docker-compose): Prometheus — `http://localhost:9090`, Grafana — `http://localhost:3001`.

Метрики приложения: `gpt_response_seconds` (histogram, label `call`), `rabbitmq_queue_messages` (gauge, label `queue`), `ai_worker_messages_processed_total`, `ai_worker_messages_errors_total`.

Provisioning Grafana: datasource и dashboard — через ConfigMap (k8s) или volume-mount (docker-compose). Изменения в UI не сохраняются — редактировать `k8s/14-grafana.yaml` → ConfigMap `grafana-dashboard`.

## SSH-реквизиты

Пароль, plink-команды и параметры сервера — в `C:\delete\claudedevops\CLAUDE.md`.
Не хранить credentials в этом репозитории.

## Kubernetes (k3s) — Фаза 6

Манифесты в `k8s/`. Deploy workflow автоматически переключается на k3s если namespace `tg-sales-bot` существует, иначе падает в docker-compose fallback.

**Bootstrap k3s на VPS (один раз, вручную):**
```bash
# 1. Установить k3s (Traefik отключён — nginx остаётся фронтом)
curl -sfL https://get.k3s.io | sh -s - --disable=traefik

# 2. Настроить kubectl для пользователя claude
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown claude:claude ~/.kube/config

# 3. Создать namespace
kubectl apply -f /var/develop/tg-sales-bot/k8s/00-namespace.yaml

# 4. Создать Secret из значений .env (один раз, не в git!)
cp /var/develop/tg-sales-bot/k8s/secret.template.yaml /var/develop/tg-sales-bot/k8s/secret.yaml
# Заполнить значения в secret.yaml из /var/develop/tg-sales-bot/.env
kubectl apply -f /var/develop/tg-sales-bot/k8s/secret.yaml

# 5. Остановить docker-compose (k3s берёт порт 8082 через hostPort)
cd /var/develop/tg-sales-bot && docker compose down

# 6. Следующий деплой (merge в main) автоматически применит k8s/
```

**Загрузка базы знаний (ChromaDB) на k3s:**

`users.txt` не в git (личные данные) — копировать на сервер вручную:
```bash
# С локальной машины
"/c/Program Files/PuTTY/pscp" -pw '...' data/knowledge_base/users.txt claude@77.83.87.29:/var/develop/tg-sales-bot/data/knowledge_base/users.txt
```

Запустить ingest внутри ai-worker пода (там есть chromadb + openai):
```bash
# На сервере
POD=$(KUBECONFIG=~/.kube/config kubectl get pod -n tg-sales-bot -l app=ai-worker -o jsonpath='{.items[0].metadata.name}')
KUBECONFIG=~/.kube/config kubectl cp /tmp/ingest.py tg-sales-bot/$POD:/tmp/ingest.py
KUBECONFIG=~/.kube/config kubectl exec -n tg-sales-bot $POD -- sh -c 'mkdir -p /app/scripts && cp /tmp/ingest.py /app/scripts/ && cd /app && python scripts/ingest.py'
```

**Полезные команды kubectl:**
```bash
kubectl get pods -n tg-sales-bot
kubectl logs -f deployment/ai-worker -n tg-sales-bot
kubectl rollout restart deployment/ai-worker -n tg-sales-bot
kubectl get hpa -n tg-sales-bot       # HorizontalPodAutoscaler для ai-worker
kubectl describe pod -n tg-sales-bot   # диагностика
```

**Важно:** nginx остаётся единственным фронтом для всего сервера (antilopa-gnu.ru и другие домены). Traefik отключён при установке k3s. SSL-сертификаты управляются certbot на уровне nginx — не трогать.

## imagePullPolicy — ВАЖНО, не менять

Во всех k8s-манифестах стоит `imagePullPolicy: IfNotPresent`. **Не менять на `Always`.**

Причина: `GITHUB_TOKEN`, который записывается в `ghcr-secret` при каждом деплое, живёт только во время выполнения Actions job. После завершения job токен истекает. Если под упадёт и k3s попытается перезапустить его с `Always`, он пойдёт в GHCR с просроченным токеном и получит 403 — под не поднимется совсем.

Схема обновления образов (уже реализована в `deploy.yml`):
1. `crictl pull --creds ...` — принудительно тянет свежий образ в containerd-кэш узла **пока токен ещё жив**
2. `kubectl rollout restart` — пересоздаёт поды; `IfNotPresent` видит образ в кэше и использует его

Итог: образы всегда актуальны после деплоя, а при аварийном рестарте под поднимается из кэша без обращения в реестр.

## Сбор пользователей из мониторируемых групп

listener логирует всех авторов сообщений из мониторируемых групп в Redis-хэш `seen_users` (один раз на пользователя, через `hsetnx`). Хранит: `user_id`, `username`, `first_name`, `last_name`, `chat_id`, `chat_title`, `first_seen`.

Веб-админка: страница **Пользователи** (`/seen-users`) — таблица с поиском и экспортом CSV. Использовать для пополнения `users.txt`.
