# Production Roadmap

Переход от docker-compose monolith → микросервисы + RabbitMQ + Kubernetes + CI/CD.

---

## Фаза 1: GitHub и репозиторий

- [ ] 1.1 `git init` в корне проекта, создать `.gitignore`
- [ ] 1.2 Создать репозиторий на GitHub (NikNik516-1)
- [ ] 1.3 Первый коммит и push в `main`
- [ ] 1.4 Создать ветку `dev` — разработка ведётся в `dev`, в `main` только через PR

---

## Фаза 2: Разбивка на микросервисы

Текущий `app/` → три отдельных сервиса + общий модуль `shared/`.

```
services/
  listener/          ← Pyrogram singleton: читает Telegram, публикует в RabbitMQ
    main.py
    listener.py
    chat_manager.py
    Dockerfile
    requirements.txt

  ai-worker/         ← потребляет очередь, вызывает GPT+RAG, публикует ответы
    main.py
    ai_client.py
    rag.py
    Dockerfile
    requirements.txt

  admin/             ← FastAPI веб-админка (без изменений логики)
    main.py
    admin_server.py
    templates/
    Dockerfile
    requirements.txt

shared/              ← общий код, монтируется в каждый контейнер
  state.py           ← Redis: state, history, user_info
  config.py          ← все переменные из .env
  mq.py              ← обёртка над aio-pika (RabbitMQ клиент)
```

- [ ] 2.1 Создать структуру директорий
- [ ] 2.2 Перенести `config.py` и `state.py` в `shared/`
- [ ] 2.3 Написать `shared/mq.py` — connect, publish, consume (aio-pika)
- [ ] 2.4 Переписать `listener`: вместо вызова `ai_client` напрямую → publish в RabbitMQ
- [ ] 2.5 Написать `ai-worker`: consume → GPT+RAG → publish ответ обратно
- [ ] 2.6 Добавить в `listener` consumer очереди ответов → отправить в Telegram
- [ ] 2.7 Перенести `admin_server.py` + шаблоны в `services/admin/`
- [ ] 2.8 Написать отдельный `Dockerfile` для каждого сервиса

**Схема очередей RabbitMQ:**
```
listener → [tg.incoming] → ai-worker → [tg.outgoing] → listener → Telegram DM
```

Формат сообщения (JSON):
```json
{
  "user_id": 123456789,
  "text": "хочу купить ручку",
  "is_opening": true,
  "from_user": {"username": "...", "first_name": "...", "last_name": "..."}
}
```

---

## Фаза 3: Docker Compose (локальная разработка)

- [ ] 3.1 Обновить `docker-compose.yml` — добавить RabbitMQ, три сервиса
- [ ] 3.2 `shared/` монтировать как volume во все сервисы (или копировать в образ)
- [ ] 3.3 Добавить health check для RabbitMQ (depends_on с condition)
- [ ] 3.4 Проверить что весь стек поднимается: `docker-compose up -d`
- [ ] 3.5 Сквозной тест: сообщение в группу → очередь → ответ в личку

---

## Фаза 4: VPS и окружение

- [ ] 4.1 Арендовать VPS (минимум 2 CPU / 4 GB RAM): Hetzner / DigitalOcean / Timeweb
- [ ] 4.2 Установить на VPS: Docker, Docker Compose, k3s
- [ ] 4.3 Добавить SSH-ключ для GitHub Actions в `~/.ssh/authorized_keys` на VPS
- [ ] 4.4 В GitHub Settings → Secrets добавить:
  - `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`
  - `TG_API_ID`, `TG_API_HASH`, `TG_SESSION_STRING`
  - `OPENAI_API_KEY`
  - `GHCR_TOKEN` (Personal Access Token для push образов)
- [ ] 4.5 Создать `.env.production` на VPS вручную (один раз, не в git)

---

## Фаза 5: GitHub Actions CI/CD

Два пайплайна:

**`.github/workflows/ci.yml`** — запускается на каждый push/PR в любую ветку:
- [ ] 5.1 Lint: `ruff check .`
- [ ] 5.2 Tests: `pytest` (написать хотя бы 2-3 базовых теста)
- [ ] 5.3 Build Docker images (проверка что собирается)

**`.github/workflows/deploy.yml`** — запускается только при merge в `main`:
- [ ] 5.4 Build & push образов в `ghcr.io/niknik516-1/...`
- [ ] 5.5 SSH на VPS → `docker-compose pull && docker-compose up -d`
  (или kubectl rollout restart, когда перейдём на k8s)
- [ ] 5.6 Slack/Telegram уведомление об успешном деплое (опционально)

---

## Фаза 6: Kubernetes (k3s)

- [ ] 6.1 Установить k3s на VPS (`curl -sfL https://get.k3s.io | sh -`)
- [ ] 6.2 Написать Kubernetes manifests:
  - `k8s/namespace.yaml`
  - `k8s/configmap.yaml` — незасекреченные переменные
  - `k8s/secret.yaml` — API-ключи (создаётся вручную, не в git)
  - `k8s/rabbitmq.yaml` — Deployment + Service
  - `k8s/redis.yaml` — StatefulSet + PersistentVolumeClaim + Service
  - `k8s/chromadb.yaml` — Deployment + PVC + Service
  - `k8s/listener.yaml` — Deployment (replicas: 1, строго singleton!)
  - `k8s/ai-worker.yaml` — Deployment (replicas: 2+)
  - `k8s/admin.yaml` — Deployment + Service
  - `k8s/ingress.yaml` — Ingress для admin (с TLS через cert-manager)
- [ ] 6.3 Установить cert-manager → автоматический TLS (Let's Encrypt)
- [ ] 6.4 HorizontalPodAutoscaler для `ai-worker` (scale по CPU или длине очереди)
- [ ] 6.5 Обновить deploy workflow: `kubectl set image` вместо docker-compose
- [ ] 6.6 Проверить rolling update без даунтайма для `admin` и `ai-worker`

---

## Фаза 7: Observability (опционально, но полезно)

- [ ] 7.1 Структурированные логи (JSON) через `structlog`
- [ ] 7.2 Prometheus метрики: длина очереди RabbitMQ, время ответа GPT, кол-во диалогов
- [ ] 7.3 Grafana dashboard
- [ ] 7.4 Alertmanager — уведомление если ai-worker упал или очередь переполнена

---

## Порядок выполнения

```
Фаза 1 → Фаза 2 → Фаза 3 (тест локально) → Фаза 4 → Фаза 5 → Фаза 6 → Фаза 7
```

Каждая фаза завершается рабочим и протестированным состоянием.
Переход к следующей — только после того как текущая стабильно работает.
