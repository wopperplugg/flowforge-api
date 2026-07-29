# Деплой

Проект подготовлен к деплою в контейнерах через GitHub Actions и GitHub
Container Registry.

## CI/CD Flow

1. Pull requests и pushes в `main` запускают linting, format checks, mypy,
   тесты, pre-commit hooks, security scans и Docker image build.
2. Pushes в `main` и version tags, например `v0.1.0`, публикуют Docker image в
   GitHub Container Registry.
3. Production host забирает опубликованный image, запускает миграции базы
   данных и после этого стартует API и worker.

## Production Environment

Создайте `.env.production` на сервере. Не коммитьте этот файл.

```env
APP_NAME=FlowForge API
APP_ENV=production
APP_DEBUG=false
APP_SECRET_KEY=replace-with-a-strong-secret
WEBHOOK_SECRET_ENCRYPTION_KEY=replace-with-a-strong-secret

POSTGRES_DB=flowforge
POSTGRES_USER=flowforge
POSTGRES_PASSWORD=replace-with-a-strong-password

REDIS_DB=0
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=30
```

## Production Compose

Забрать свежий image:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml pull
```

Запустить миграции явно:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml \
  --profile migration run --rm migrate
```

Запустить API и worker:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d api worker
```

Проверить readiness:

```bash
curl http://localhost:8000/health/ready
```

## Release Tags

Создать versioned release image:

```bash
git tag v0.1.0
git push origin v0.1.0
```
