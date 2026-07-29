# Архитектура

FlowForge API - backend на FastAPI с разделением по бизнес-доменам. HTTP-слой
находится в роутерах, бизнес-правила - в сервисах, доступ к базе данных - в
репозиториях.

## Runtime Components

- API process: обслуживает FastAPI routes и health endpoints.
- Worker process: читает outbox events и доставляет webhook.
- PostgreSQL: основное реляционное хранилище.
- Redis: rate limiting и runtime-инфраструктура.
- Alembic: явные миграции схемы базы данных.

## Структура модулей

- `src/auth`: authentication, refresh-token rotation, отзыв сессий.
- `src/users`: пользователи и хеширование паролей.
- `src/organizations`: организации, роли участников, правила авторизации.
- `src/projects`: проекты внутри организаций.
- `src/tasks`: CRUD задач, комментарии, история статусов, optimistic locking.
- `src/webhooks`: подписки, секреты, подписи и доставка webhook.
- `src/outbox`: надежная очередь событий для side effects.
- `src/infrastructure`: логирование, Redis, health checks, middleware.

## Надежность

Запись задачи и создание outbox event выполняются вместе в request path.
Доставка webhook вынесена в worker, поэтому ошибка внешнего webhook endpoint не
откатывает пользовательское изменение задачи.

Миграции запускаются отдельным шагом деплоя перед стартом новых API и worker
containers.
