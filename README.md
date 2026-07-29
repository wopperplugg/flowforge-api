# FlowForge API

FlowForge API is a production-oriented FastAPI backend for collaborative task
management. It demonstrates authentication, organizations, projects, tasks,
optimistic locking, outbox-based webhook delivery, PostgreSQL migrations,
Redis-backed rate limiting, structured logging, and Dockerized runtime.

## Tech Stack

- Python 3.13, FastAPI, Pydantic v2
- SQLAlchemy 2.x async ORM, Alembic, PostgreSQL
- Redis for rate limiting and runtime infrastructure
- JWT access/refresh tokens with refresh-token rotation
- Outbox worker for reliable webhook dispatch
- Pytest and Ruff for verification

## Architecture

The codebase is split by business domain:

- `src/auth` - login, token refresh, logout, session revocation
- `src/users` - user registration and password hashing
- `src/organizations` - organizations and membership roles
- `src/projects` - projects scoped to organizations
- `src/tasks` - task CRUD, comments, status history, optimistic locking
- `src/webhooks` - subscriptions, secret handling, signed delivery
- `src/outbox` - durable event queue for async side effects
- `src/infrastructure` - logging, health checks, Redis, middleware

Routers stay thin, services own business rules, repositories own database
queries, and schemas define the HTTP contract.

## Local Setup

```bash
cp .env.example .env
uv sync
docker compose up -d postgres redis
uv run alembic upgrade head
uv run uvicorn src.main:app --reload
```

OpenAPI docs are available at:

```text
http://localhost:8000/docs
```

## Docker

Run the API, worker, PostgreSQL, and Redis:

```bash
docker compose up --build
```

The API exposes:

- `GET /health/live` - process liveness
- `GET /health/ready` - PostgreSQL and Redis readiness

## Verification

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest --cov=src
uv run pre-commit run --all-files
```

Current test coverage focuses on the public API contract, health endpoint,
schema normalization, enum stability, and webhook URL safety checks.

## CI/CD

GitHub Actions runs a quality gate on every pull request and push to `main`:

- Ruff linting and format checks
- Mypy static type checking
- Pytest with coverage
- Pre-commit hooks
- Docker image build

On pushes to `main` and version tags such as `v1.0.0`, the pipeline publishes
the Docker image to GitHub Container Registry:

```text
ghcr.io/<owner>/<repo>
```

Images are tagged by branch, git tag, and commit SHA. Production deployments
should pull a published image, run `alembic upgrade head`, then start the API
and worker containers with production environment variables.

## API Flow

1. Register with `POST /api/v1/auth/register`.
2. Login with `POST /api/v1/auth/login`.
3. Create an organization with `POST /api/v1/organizations`.
4. Create a project with `POST /api/v1/organizations/{organization_id}/projects`.
5. Create and update tasks with `/api/v1/projects/{project_id}/tasks` and
   `/api/v1/tasks/{task_id}`.
6. Subscribe to task events with
   `POST /api/v1/organizations/{organization_id}/webhooks`.

Task updates require the current `version` field. If another client updates the
task first, the API returns `409 task_version_conflict`.

## Production Notes

- Set strong `APP_SECRET_KEY`, `POSTGRES_PASSWORD`, and
  `WEBHOOK_SECRET_ENCRYPTION_KEY` in production.
- Run Alembic migrations explicitly before deploying new application code.
- Keep webhook targets HTTPS-only in production.
- The worker processes outbox events independently from request handling, so
  webhook failures do not roll back user-facing task operations.
