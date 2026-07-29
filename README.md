# FlowForge API

[![CI/CD](https://github.com/wopperplugg/flowforge-api/actions/workflows/ci.yml/badge.svg)](https://github.com/wopperplugg/flowforge-api/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.13-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.137%2B-009688)
![Docker](https://img.shields.io/badge/docker-GHCR-2496ED)

FlowForge API - backend на FastAPI, подготовленный к production, для совместной
работы с задачами. Проект показывает регистрацию и авторизацию, организации,
проекты, задачи, optimistic locking, доставку webhook через outbox, миграции
PostgreSQL, rate limiting на Redis, структурированные логи и Docker-ready
runtime.

## Стек

- Python 3.13, FastAPI, Pydantic v2
- SQLAlchemy 2.x async ORM, Alembic, PostgreSQL
- Redis для rate limiting и runtime-инфраструктуры
- JWT access/refresh tokens с ротацией refresh-токенов
- Outbox worker для надежной доставки webhook
- Pytest, Ruff, Mypy, Bandit и pip-audit для проверки качества

## Архитектура

Код разделен по бизнес-доменам:

- `src/auth` - login, token refresh, logout, отзыв сессий
- `src/users` - регистрация пользователей и хеширование паролей
- `src/organizations` - организации и роли участников
- `src/projects` - проекты внутри организаций
- `src/tasks` - CRUD задач, комментарии, история статусов, optimistic locking
- `src/webhooks` - подписки, секреты, подпись и доставка webhook
- `src/outbox` - надежная очередь событий для side effects
- `src/infrastructure` - логирование, health checks, Redis, middleware

Роутеры остаются тонкими: они принимают HTTP-запросы и вызывают сервисы.
Сервисы содержат бизнес-правила, репозитории отвечают за SQLAlchemy-запросы,
а схемы Pydantic задают HTTP-контракт.

## Локальный запуск

```bash
cp .env.example .env
uv sync
docker compose up -d postgres redis
uv run alembic upgrade head
uv run uvicorn src.main:app --reload
```

OpenAPI-документация доступна по адресу:

```text
http://localhost:8000/docs
```

## Docker

Запуск API, worker, PostgreSQL и Redis:

```bash
docker compose up --build
```

Health endpoints:

- `GET /health/live` - проверка, что процесс API запущен
- `GET /health/ready` - проверка готовности PostgreSQL и Redis

## Проверки

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest --cov=src --cov-fail-under=60
uv run pre-commit run --all-files
```

Текущие тесты покрывают публичный API-контракт, health endpoint, нормализацию
схем, стабильность enum-значений, безопасность webhook URL и основные
бизнес-сценарии сервисов.

## CI/CD

GitHub Actions запускает quality gate на каждый pull request и push в `main`:

- Ruff linting и проверка форматирования
- Проверка типов через Mypy
- Pytest с coverage
- Coverage gate с минимальным порогом
- Pre-commit hooks
- Security scan через Bandit
- Аудит Python-зависимостей через pip-audit
- Сборка Docker image

При push в `main` и при version tags, например `v1.0.0`, pipeline публикует
Docker image в GitHub Container Registry:

```text
ghcr.io/<owner>/<repo>
```

Images тегируются по branch, git tag и commit SHA. Production deployment должен
забрать опубликованный image, выполнить `alembic upgrade head`, затем запустить
API и worker containers с production environment variables.

## API Flow

1. Регистрация через `POST /api/v1/auth/register`.
2. Login через `POST /api/v1/auth/login`.
3. Создание организации через `POST /api/v1/organizations`.
4. Создание проекта через
   `POST /api/v1/organizations/{organization_id}/projects`.
5. Создание и обновление задач через `/api/v1/projects/{project_id}/tasks` и
   `/api/v1/tasks/{task_id}`.
6. Подписка на события задач через
   `POST /api/v1/organizations/{organization_id}/webhooks`.

Обновление задачи требует актуальное поле `version`. Если другой клиент успел
изменить задачу раньше, API вернет `409 task_version_conflict`.

## Production Notes

- В production нужно задать сильные `APP_SECRET_KEY`, `POSTGRES_PASSWORD` и
  `WEBHOOK_SECRET_ENCRYPTION_KEY`.
- Alembic-миграции запускаются явно перед выкладкой нового кода.
- В production webhook targets должны использовать HTTPS.
- Worker обрабатывает outbox events отдельно от request handling, поэтому
  ошибки доставки webhook не откатывают пользовательские изменения задач.

Подробнее:

- [Архитектура](docs/ARCHITECTURE.md)
- [Деплой](docs/DEPLOYMENT.md)
