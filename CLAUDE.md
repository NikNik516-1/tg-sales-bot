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

## CI/CD (Фаза 5)

**Обычный цикл разработки:**
```
git commit + git push origin dev
  → CI (ci.yml): ruff check · pytest · docker build ×3
  → создать PR dev→main → смержить
  → deploy.yml: build+push образов в GHCR → SSH на VPS → docker compose pull + up -d
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

**Первый деплой (bootstrap нового сервера):**
```bash
# На сервере
git clone https://github.com/NikNik516-1/tg-sales-bot.git /var/develop/tg-sales-bot
cd /var/develop/tg-sales-bot
# Создать .env (не в git) с ROOT_PATH=/tg-sales-bot/adminka
docker compose pull && docker compose up -d
# Загрузить базу знаний
CHROMA_HOST=localhost python3 scripts/ingest.py
```

**Обновление — через CI/CD (автоматически):**
Смержить PR в `main` → GitHub Actions задеплоит сам.

**Обновление — вручную (если CI/CD недоступен):**
```bash
cd /var/develop/tg-sales-bot
git pull origin main
docker compose pull listener ai-worker admin
docker compose up -d
```

**Nginx:** добавлен location в `/etc/nginx/sites-enabled/antilopa-gnu-ru.conf`:
- `https://antilopa-gnu.ru/tg-sales-bot/adminka/` → `http://127.0.0.1:8082/`

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

**Загрузка базы знаний после миграции на k3s:**
```bash
# data/ монтируется как hostPath — ingest запускается так же
CHROMA_HOST=localhost python3 /var/develop/tg-sales-bot/scripts/ingest.py
```

**Полезные команды kubectl:**
```bash
kubectl get pods -n tg-sales-bot
kubectl logs -f deployment/ai-worker -n tg-sales-bot
kubectl rollout restart deployment/ai-worker -n tg-sales-bot
kubectl get hpa -n tg-sales-bot       # HorizontalPodAutoscaler для ai-worker
kubectl describe pod -n tg-sales-bot   # диагностика
```

**Ingress + TLS (Фаза 6.3, пока не активирован):**
Файл `k8s/20-ingress.yaml` — cert-manager + Let's Encrypt + Traefik.
Перед применением: установить cert-manager и убрать nginx с портов 80/443.
Когда готово — добавить `20-ingress.yaml` в `k8s/kustomization.yaml`.
