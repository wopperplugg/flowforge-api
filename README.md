# FlowForge API

[![CI/CD](https://github.com/wopperplugg/flowforge-api/actions/workflows/ci.yml/badge.svg)](https://github.com/wopperplugg/flowforge-api/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.13-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.137%2B-009688)
![Docker](https://img.shields.io/badge/docker-GHCR-2496ED)

FlowForge API - демонстрационный backend-проект для портфолио. Его цель -
показать навыки backend-разработчика на Python: проектирование REST API,
работу с PostgreSQL, асинхронный SQLAlchemy, JWT-аутентификацию, доменную
архитектуру, фоновые worker-процессы, надежную доставку webhook, Docker,
миграции, тесты и CI/CD.

Проект сделан как API для командной работы с задачами. В нем есть пользователи,
организации, проекты, задачи, комментарии, история статусов, роли участников и
подписки на webhook-события.

## Текущее состояние

Проект находится в состоянии portfolio-ready demo: основные backend-сценарии
реализованы, покрыты тестами и запускаются локально через Docker Compose.
Код не является коммерческим продуктом, но демонстрирует production-подходы,
которые обычно нужны в реальном backend-сервисе.

Реализовано:

- регистрация, login, refresh и logout через JWT access/refresh tokens;
- ротация refresh-токенов и отзыв сессий;
- пользователи, организации, роли участников и проекты;
- задачи с комментариями, историей статусов и optimistic locking;
- единый формат доменных ошибок;
- PostgreSQL, Alembic migrations и async SQLAlchemy 2.x;
- Redis rate limiting;
- RabbitMQ messaging и outbox pattern для side effects;
- отдельные worker-процессы для outbox и webhook delivery;
- подпись webhook-запросов и хранение секретов;
- health endpoints для live/ready checks;
- Prometheus `/metrics` для HTTP, outbox и webhook worker метрик;
- структурированные JSON-логи через `structlog`;
- Dockerfile, `docker-compose.yml` и `docker-compose.prod.yml`;
- CI/CD pipeline с linting, formatting, typing, tests, coverage, security scan,
  dependency audit и сборкой Docker image.

Осознанные точки роста:

- усилить защиту refresh-token rotation от конкурентных refresh-запросов;
- усилить SSRF-защиту при фактической доставке webhook;
- добавить pagination для list endpoints;
- вынести повторяющуюся authorization logic в отдельный policy layer;
- расширить integration tests для полного auth flow.

Подробный разбор сильных сторон и дальнейших улучшений лежит в
[docs/portfolio-review.md](docs/portfolio-review.md).

## Что проект показывает

- Умение строить backend по доменам, а не складывать всю логику в роутеры.
- Разделение ответственности: routers, services, repositories, schemas,
  models и infrastructure.
- Работу с транзакциями, миграциями, async ORM и PostgreSQL.
- Проектирование API-контракта и стабильного error envelope.
- Практики надежности: optimistic locking, outbox, worker delivery, retries.
- Базовые практики безопасности: password hashing, JWT validation, token
  rotation, webhook signatures, secret checks для production.
- Инженерную дисциплину: типизация, тесты, линтеры, security checks и Docker.

## Стек

- Python 3.13
- FastAPI, Pydantic v2
- SQLAlchemy 2.x async ORM, Alembic
- PostgreSQL
- Redis
- RabbitMQ
- JWT, Argon2 password hashing
- Pytest, Ruff, Mypy, Bandit, pip-audit
- Docker, Docker Compose, GitHub Actions

## Архитектура

Код разделен по бизнес-доменам:

- `src/auth` - authentication, refresh-token rotation, logout, отзыв сессий;
- `src/users` - пользователи и хеширование паролей;
- `src/organizations` - организации, участники и роли;
- `src/projects` - проекты внутри организаций;
- `src/tasks` - задачи, комментарии, история статусов, optimistic locking;
- `src/webhooks` - подписки, секреты, подпись и доставка webhook;
- `src/outbox` - очередь событий для надежных side effects;
- `src/messaging` - RabbitMQ contracts, topology, publisher и retry logic;
- `src/infrastructure` - middleware, Redis, rate limiting, health checks, logs.

Основной принцип: HTTP-слой остается тонким. Роутеры принимают запросы и
вызывают сервисы, сервисы содержат бизнес-правила, репозитории отвечают за
SQLAlchemy-запросы, а Pydantic-схемы фиксируют API-контракт.

## Локальный запуск

```bash
cp .env.example .env
uv sync
docker compose up -d postgres redis rabbitmq
uv run alembic upgrade head
uv run uvicorn src.main:app --reload
```

OpenAPI-документация будет доступна по адресу:

```text
http://localhost:8000/docs
```

Полный запуск API, worker, PostgreSQL, Redis и RabbitMQ:

```bash
docker compose up --build
```

Health endpoints:

- `GET /health/live` - процесс API запущен;
- `GET /health/ready` - PostgreSQL и Redis доступны.
- `GET /metrics` - Prometheus metrics endpoint.

Monitoring endpoints при запуске через Docker Compose:

- `http://localhost:9090` - Prometheus;
- `http://localhost:3000` - Grafana;
- `http://localhost:9101/metrics` - outbox worker metrics;
- `http://localhost:9102/metrics` - webhook worker metrics.

## Демо-данные

После запуска PostgreSQL и миграций можно заполнить базу демонстрационными
данными:

```bash
uv run python -m scripts.seed_demo_data
```

В Docker Compose:

```bash
docker compose exec -T api python -m scripts.seed_demo_data
```

Скрипт идемпотентный и не создает дубликаты при повторном запуске.

Демо-пользователи:

- `admin@flowforge-demo.com`
- `alice.petrov@flowforge-demo.com`
- `boris.ivanov@flowforge-demo.com`
- `clara.smith@flowforge-demo.com`
- `dmitry.qa@flowforge-demo.com`

Пароль для всех demo-аккаунтов:

```text
DemoPass123!
```

## Основной API Flow

1. `POST /api/v1/auth/register` - регистрация пользователя.
2. `POST /api/v1/auth/login` - вход и получение токенов.
3. `POST /api/v1/organizations` - создание организации.
4. `POST /api/v1/organizations/{organization_id}/projects` - создание проекта.
5. `POST /api/v1/projects/{project_id}/tasks` - создание задачи.
6. `PATCH /api/v1/tasks/{task_id}` - обновление задачи.
7. `POST /api/v1/organizations/{organization_id}/webhooks` - подписка на
   события задач.

Обновление задачи требует актуальное поле `version`. Если задача была изменена
другим клиентом раньше, API возвращает `409 task_version_conflict`.

## Проверки

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest --cov=src --cov-fail-under=60
uv run pre-commit run --all-files
```

Тесты покрывают API-контракт, health endpoints, схемы, enum-значения, webhook
security, messaging, workers и ключевые бизнес-сценарии сервисов.

## CI/CD

GitHub Actions запускает quality gate на pull request и push в `main`:

- Ruff linting и проверка форматирования;
- Mypy type checking;
- Pytest с coverage;
- Pre-commit hooks;
- Bandit security scan;
- pip-audit dependency audit;
- Docker image build.

При push в `main` и version tags, например `v1.0.0`, pipeline публикует Docker
image в GitHub Container Registry:

```text
ghcr.io/<owner>/<repo>
```

## Production Notes

Для production-like запуска нужно задать сильные значения:

- `APP_SECRET_KEY`;
- `POSTGRES_PASSWORD`;
- `WEBHOOK_SECRET_ENCRYPTION_KEY`;
- RabbitMQ credentials;
- Redis/PostgreSQL connection settings.

Alembic-миграции запускаются отдельным шагом перед стартом нового API и worker
containers. Webhook delivery вынесен из request path в worker, поэтому ошибки
внешних webhook endpoint не откатывают пользовательские изменения задач.

## Документация

- [Архитектура](docs/ARCHITECTURE.md)
- [Деплой](docs/DEPLOYMENT.md)
- [Portfolio Review](docs/portfolio-review.md)
