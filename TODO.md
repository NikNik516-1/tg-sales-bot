# Production Roadmap

Переход от docker-compose monolith → микросервисы + RabbitMQ + Kubernetes + CI/CD.

---

## Фаза 1: GitHub и репозиторий ✅

- [x] 1.1 `git init` в корне проекта, создать `.gitignore`
- [x] 1.2 Создать репозиторий на GitHub (NikNik516-1/tg-sales-bot)
- [x] 1.3 Первый коммит и push в `main`
- [x] 1.4 Создать ветку `dev` — разработка ведётся в `dev`, в `main` только через PR

---

## Фаза 2: Разбивка на микросервисы ✅

- [x] 2.1 Создать структуру директорий `services/` и `shared/`
- [x] 2.2 Перенести `config.py` и `state.py` в `shared/`
- [x] 2.3 Написать `shared/mq.py` — connect, publish, consume (aio-pika)
- [x] 2.4 Переписать `listener`: вместо вызова `ai_client` напрямую → publish в RabbitMQ
- [x] 2.5 Написать `ai-worker`: consume → GPT+RAG → publish ответ обратно
- [x] 2.6 Добавить в `listener` consumer очереди ответов → отправить в Telegram
- [x] 2.7 Перенести `admin_server.py` + шаблоны в `services/admin/`
- [x] 2.8 Написать отдельный `Dockerfile` для каждого сервиса

**Схема очередей RabbitMQ:**
```
listener → [tg.incoming] → ai-worker → [tg.outgoing] → listener → Telegram DM
```

---

## Фаза 3: Docker Compose (локальная разработка) ✅

- [x] 3.1 Обновить `docker-compose.yml` — добавить RabbitMQ, три сервиса
- [x] 3.2 `shared/` копируется в каждый образ через Dockerfile
- [x] 3.3 Health check для RabbitMQ (`rabbitmq-diagnostics ping`)
- [x] 3.4 Весь стек поднимается: `docker-compose up -d`
- [ ] 3.5 Сквозной тест: сообщение в группу → очередь → ответ в личку

---

## Фаза 4: VPS и окружение

- [ ] 4.1 Арендовать VPS (минимум 2 CPU / 4 GB RAM): Hetzner / DigitalOcean / Timeweb
- [ ] 4.2 Установить на VPS: Docker, Docker Compose
- [ ] 4.3 Сгенерировать SSH-ключ для GitHub Actions, добавить в `~/.ssh/authorized_keys` на VPS
- [ ] 4.4 В GitHub Settings → Secrets добавить:
  - `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`
  - `TG_API_ID`, `TG_API_HASH`, `TG_SESSION_STRING`
  - `OPENAI_API_KEY`
  - `GHCR_TOKEN` (Personal Access Token → packages: write)
- [ ] 4.5 Создать `.env` на VPS вручную (один раз, не в git)

---

## Фаза 5: GitHub Actions CI/CD

**`.github/workflows/ci.yml`** — на каждый push/PR:
- [ ] 5.1 Lint: `ruff check .`
- [ ] 5.2 Tests: `pytest` (написать 2-3 базовых теста)
- [ ] 5.3 Build Docker images (проверка что собирается)

**`.github/workflows/deploy.yml`** — только при merge в `main`:
- [ ] 5.4 Build & push образов в `ghcr.io/niknik516-1/...`
- [ ] 5.5 SSH на VPS → `docker compose pull && docker compose up -d`
- [ ] 5.6 Telegram-уведомление об успешном деплое (опционально)

---

## Фаза 6: Kubernetes (k3s)

- [ ] 6.1 Установить k3s на VPS
- [ ] 6.2 Написать Kubernetes manifests (`k8s/`):
  - `namespace.yaml`, `configmap.yaml`, `secret.yaml` (не в git)
  - `rabbitmq.yaml`, `redis.yaml`, `chromadb.yaml` — StatefulSet + PVC + Service
  - `listener.yaml` — Deployment (replicas: **1**, строго singleton!)
  - `ai-worker.yaml` — Deployment (replicas: 2+)
  - `admin.yaml` — Deployment + Service
  - `ingress.yaml` — Ingress + TLS (cert-manager + Let's Encrypt)
- [ ] 6.3 Установить cert-manager → автоматический TLS
- [ ] 6.4 HorizontalPodAutoscaler для `ai-worker`
- [ ] 6.5 Обновить deploy workflow: `kubectl set image`
- [ ] 6.6 Проверить rolling update без даунтайма для `admin` и `ai-worker`

---

## Фаза 7: Observability (опционально)

- [ ] 7.1 Структурированные логи (JSON) через `structlog`
- [ ] 7.2 Prometheus метрики: длина очереди RabbitMQ, время ответа GPT
- [ ] 7.3 Grafana dashboard
- [ ] 7.4 Alertmanager — уведомление если `ai-worker` упал или очередь переполнена

---

## Порядок выполнения

```
✅ Фаза 1 → ✅ Фаза 2 → ✅ Фаза 3 → Фаза 4 → Фаза 5 → Фаза 6 → Фаза 7
```

Текущий статус: **Фаза 4 — VPS**.
