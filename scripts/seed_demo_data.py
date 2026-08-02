import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.models import AuditLog
from src.auth.models import RefreshSession
from src.auth.security import hash_refresh_token
from src.common.enums import (
    OrganizationRole,
    OutboxStatus,
    TaskPriority,
    TaskStatus,
    UserRole,
)
from src.common.security import PASSWORD_ALGORITHM, hash_password
from src.database import async_session_maker, dispose_engine
from src.idempotency.models import IdempotencyKey
from src.organizations.models import Organization, OrganizationMember
from src.outbox.models import OutboxEvent
from src.projects.models import Project
from src.tasks.models import Task, TaskComment, TaskStatusHistory
from src.users.models import User
from src.webhooks.models import WebhookDelivery, WebhookSubscription
from src.webhooks.security import encrypt_webhook_secret, hash_webhook_secret

DEMO_PASSWORD = "DemoPass123!"  # nosec B105
DEMO_WEBHOOK_SECRET = "ff_demo_webhook_secret_2026"  # nosec B105
DEMO_REFRESH_TOKEN = "demo-refresh-token-alice-active"  # nosec B105

NAMESPACE = uuid.UUID("2a032fc0-3f96-493f-a979-84226e4da440")


def demo_id(name: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, name)


async def insert_rows(
    session: AsyncSession,
    model: type[Any],
    rows: Sequence[dict[str, Any]],
) -> int:
    if not rows:
        return 0
    statement = insert(model).values(list(rows)).on_conflict_do_nothing()
    result = await session.execute(statement)
    assert isinstance(result, CursorResult)
    return result.rowcount or 0


async def upsert_user_rows(
    session: AsyncSession,
    rows: Sequence[dict[str, Any]],
) -> int:
    if not rows:
        return 0
    excluded = insert(User).excluded
    statement = (
        insert(User)
        .values(list(rows))
        .on_conflict_do_update(
            index_elements=[User.id],
            set_={
                "email": excluded.email,
                "username": excluded.username,
                "hashed_password": excluded.hashed_password,
                "password_algorithm": excluded.password_algorithm,
                "is_active": excluded.is_active,
                "role": excluded.role,
                "updated_at": excluded.updated_at,
            },
        )
    )
    result = await session.execute(statement)
    assert isinstance(result, CursorResult)
    return result.rowcount or 0


async def upsert_webhook_rows(
    session: AsyncSession,
    rows: Sequence[dict[str, Any]],
) -> int:
    if not rows:
        return 0
    excluded = insert(WebhookSubscription).excluded
    statement = (
        insert(WebhookSubscription)
        .values(list(rows))
        .on_conflict_do_update(
            index_elements=[WebhookSubscription.id],
            set_={
                "organization_id": excluded.organization_id,
                "url": excluded.url,
                "secret_hash": excluded.secret_hash,
                "secret_encrypted": excluded.secret_encrypted,
                "event_types": excluded.event_types,
                "is_active": excluded.is_active,
                "updated_at": excluded.updated_at,
            },
        )
    )
    result = await session.execute(statement)
    assert isinstance(result, CursorResult)
    return result.rowcount or 0


def user_rows(now: datetime) -> list[dict[str, Any]]:
    password_hash = hash_password(DEMO_PASSWORD)
    return [
        {
            "id": demo_id("user-admin"),
            "email": "admin@flowforge-demo.com",
            "username": "admin",
            "hashed_password": password_hash,
            "password_algorithm": PASSWORD_ALGORITHM,
            "is_active": True,
            "role": UserRole.ADMIN,
            "created_at": now - timedelta(days=60),
            "updated_at": now - timedelta(days=2),
        },
        {
            "id": demo_id("user-alice"),
            "email": "alice.petrov@flowforge-demo.com",
            "username": "alice.petrov",
            "hashed_password": password_hash,
            "password_algorithm": PASSWORD_ALGORITHM,
            "is_active": True,
            "role": UserRole.USER,
            "created_at": now - timedelta(days=45),
            "updated_at": now - timedelta(hours=5),
        },
        {
            "id": demo_id("user-boris"),
            "email": "boris.ivanov@flowforge-demo.com",
            "username": "boris.ivanov",
            "hashed_password": password_hash,
            "password_algorithm": PASSWORD_ALGORITHM,
            "is_active": True,
            "role": UserRole.MODERATOR,
            "created_at": now - timedelta(days=43),
            "updated_at": now - timedelta(days=1),
        },
        {
            "id": demo_id("user-clara"),
            "email": "clara.smith@flowforge-demo.com",
            "username": "clara.smith",
            "hashed_password": password_hash,
            "password_algorithm": PASSWORD_ALGORITHM,
            "is_active": True,
            "role": UserRole.USER,
            "created_at": now - timedelta(days=38),
            "updated_at": now - timedelta(hours=9),
        },
        {
            "id": demo_id("user-dmitry"),
            "email": "dmitry.qa@flowforge-demo.com",
            "username": "dmitry.qa",
            "hashed_password": password_hash,
            "password_algorithm": PASSWORD_ALGORITHM,
            "is_active": True,
            "role": UserRole.USER,
            "created_at": now - timedelta(days=30),
            "updated_at": now - timedelta(days=3),
        },
        {
            "id": demo_id("user-eva"),
            "email": "eva.viewer@flowforge-demo.com",
            "username": "eva.viewer",
            "hashed_password": password_hash,
            "password_algorithm": PASSWORD_ALGORITHM,
            "is_active": False,
            "role": UserRole.USER,
            "created_at": now - timedelta(days=25),
            "updated_at": now - timedelta(days=10),
        },
    ]


def organization_rows(now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "id": demo_id("org-northstar"),
            "name": "Northstar Logistics",
            "slug": "northstar-logistics",
            "created_at": now - timedelta(days=44),
            "updated_at": now - timedelta(days=1),
        },
        {
            "id": demo_id("org-medpulse"),
            "name": "MedPulse Clinics",
            "slug": "medpulse-clinics",
            "created_at": now - timedelta(days=32),
            "updated_at": now - timedelta(hours=8),
        },
    ]


def member_rows(now: datetime) -> list[dict[str, Any]]:
    northstar = demo_id("org-northstar")
    medpulse = demo_id("org-medpulse")
    return [
        {
            "id": demo_id("member-northstar-alice"),
            "organization_id": northstar,
            "user_id": demo_id("user-alice"),
            "role": OrganizationRole.OWNER,
            "created_at": now - timedelta(days=44),
            "updated_at": now - timedelta(days=44),
        },
        {
            "id": demo_id("member-northstar-boris"),
            "organization_id": northstar,
            "user_id": demo_id("user-boris"),
            "role": OrganizationRole.ADMIN,
            "created_at": now - timedelta(days=42),
            "updated_at": now - timedelta(days=5),
        },
        {
            "id": demo_id("member-northstar-clara"),
            "organization_id": northstar,
            "user_id": demo_id("user-clara"),
            "role": OrganizationRole.MEMBER,
            "created_at": now - timedelta(days=37),
            "updated_at": now - timedelta(days=2),
        },
        {
            "id": demo_id("member-northstar-eva"),
            "organization_id": northstar,
            "user_id": demo_id("user-eva"),
            "role": OrganizationRole.VIEWER,
            "created_at": now - timedelta(days=20),
            "updated_at": now - timedelta(days=20),
        },
        {
            "id": demo_id("member-medpulse-admin"),
            "organization_id": medpulse,
            "user_id": demo_id("user-admin"),
            "role": OrganizationRole.OWNER,
            "created_at": now - timedelta(days=32),
            "updated_at": now - timedelta(days=32),
        },
        {
            "id": demo_id("member-medpulse-dmitry"),
            "organization_id": medpulse,
            "user_id": demo_id("user-dmitry"),
            "role": OrganizationRole.MEMBER,
            "created_at": now - timedelta(days=29),
            "updated_at": now - timedelta(days=3),
        },
    ]


def project_rows(now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "id": demo_id("project-dispatch"),
            "organization_id": demo_id("org-northstar"),
            "name": "Dispatch Control",
            "key": "DSP",
            "description": "Operational board for vehicle routing and live dispatch.",
            "created_at": now - timedelta(days=40),
            "updated_at": now - timedelta(hours=6),
        },
        {
            "id": demo_id("project-billing"),
            "organization_id": demo_id("org-northstar"),
            "name": "Customer Billing Portal",
            "key": "BILL",
            "description": "Invoices, payment status, and customer account workflows.",
            "created_at": now - timedelta(days=35),
            "updated_at": now - timedelta(days=1),
        },
        {
            "id": demo_id("project-patient-intake"),
            "organization_id": demo_id("org-medpulse"),
            "name": "Patient Intake",
            "key": "INTAKE",
            "description": "Digital intake flow for clinics and front desk teams.",
            "created_at": now - timedelta(days=30),
            "updated_at": now - timedelta(hours=7),
        },
    ]


def task_rows(now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "id": demo_id("task-route-map"),
            "project_id": demo_id("project-dispatch"),
            "created_by_id": demo_id("user-alice"),
            "assigned_to_id": demo_id("user-clara"),
            "title": "Add route map filters",
            "description": (
                "Filter active vehicles by depot, driver shift, and SLA risk."
            ),
            "status": TaskStatus.IN_PROGRESS,
            "priority": TaskPriority.HIGH,
            "position": 10,
            "due_date": date(2026, 8, 8),
            "version": 3,
            "created_at": now - timedelta(days=8),
            "updated_at": now - timedelta(hours=4),
        },
        {
            "id": demo_id("task-driver-import"),
            "project_id": demo_id("project-dispatch"),
            "created_by_id": demo_id("user-boris"),
            "assigned_to_id": demo_id("user-boris"),
            "title": "Validate nightly driver import",
            "description": "Reject duplicate license numbers and report failed rows.",
            "status": TaskStatus.REVIEW,
            "priority": TaskPriority.CRITICAL,
            "position": 20,
            "due_date": date(2026, 8, 5),
            "version": 5,
            "created_at": now - timedelta(days=12),
            "updated_at": now - timedelta(hours=2),
        },
        {
            "id": demo_id("task-billing-export"),
            "project_id": demo_id("project-billing"),
            "created_by_id": demo_id("user-alice"),
            "assigned_to_id": None,
            "title": "Export paid invoices to CSV",
            "description": "Finance needs filtered exports by billing period.",
            "status": TaskStatus.TODO,
            "priority": TaskPriority.MEDIUM,
            "position": 30,
            "due_date": date(2026, 8, 15),
            "version": 1,
            "created_at": now - timedelta(days=5),
            "updated_at": now - timedelta(days=5),
        },
        {
            "id": demo_id("task-intake-signature"),
            "project_id": demo_id("project-patient-intake"),
            "created_by_id": demo_id("user-admin"),
            "assigned_to_id": demo_id("user-dmitry"),
            "title": "Collect consent signature",
            "description": "Store signed consent metadata and audit the patient flow.",
            "status": TaskStatus.DONE,
            "priority": TaskPriority.HIGH,
            "position": 40,
            "due_date": date(2026, 7, 28),
            "version": 4,
            "created_at": now - timedelta(days=18),
            "updated_at": now - timedelta(days=3),
        },
        {
            "id": demo_id("task-intake-kiosk"),
            "project_id": demo_id("project-patient-intake"),
            "created_by_id": demo_id("user-dmitry"),
            "assigned_to_id": demo_id("user-dmitry"),
            "title": "Retire legacy kiosk sync",
            "description": "Feature was replaced by the tablet check-in flow.",
            "status": TaskStatus.CANCELED,
            "priority": TaskPriority.LOW,
            "position": 50,
            "due_date": None,
            "version": 2,
            "created_at": now - timedelta(days=14),
            "updated_at": now - timedelta(days=4),
        },
    ]


def history_rows(now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "id": demo_id("history-route-map-created"),
            "task_id": demo_id("task-route-map"),
            "changed_by_id": demo_id("user-alice"),
            "old_status": None,
            "new_status": TaskStatus.TODO,
            "created_at": now - timedelta(days=8),
        },
        {
            "id": demo_id("history-route-map-progress"),
            "task_id": demo_id("task-route-map"),
            "changed_by_id": demo_id("user-clara"),
            "old_status": TaskStatus.TODO,
            "new_status": TaskStatus.IN_PROGRESS,
            "created_at": now - timedelta(days=6),
        },
        {
            "id": demo_id("history-driver-import-review"),
            "task_id": demo_id("task-driver-import"),
            "changed_by_id": demo_id("user-boris"),
            "old_status": TaskStatus.IN_PROGRESS,
            "new_status": TaskStatus.REVIEW,
            "created_at": now - timedelta(days=1),
        },
        {
            "id": demo_id("history-signature-done"),
            "task_id": demo_id("task-intake-signature"),
            "changed_by_id": demo_id("user-dmitry"),
            "old_status": TaskStatus.REVIEW,
            "new_status": TaskStatus.DONE,
            "created_at": now - timedelta(days=3),
        },
        {
            "id": demo_id("history-kiosk-canceled"),
            "task_id": demo_id("task-intake-kiosk"),
            "changed_by_id": demo_id("user-admin"),
            "old_status": TaskStatus.TODO,
            "new_status": TaskStatus.CANCELED,
            "created_at": now - timedelta(days=4),
        },
    ]


def comment_rows(now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "id": demo_id("comment-route-map-1"),
            "task_id": demo_id("task-route-map"),
            "author_id": demo_id("user-alice"),
            "text": "Use depot codes from the operations dictionary, not free text.",
            "created_at": now - timedelta(days=7, hours=4),
            "updated_at": now - timedelta(days=7, hours=4),
        },
        {
            "id": demo_id("comment-route-map-2"),
            "task_id": demo_id("task-route-map"),
            "author_id": demo_id("user-clara"),
            "text": "Implemented depot and shift filters; SLA risk is still pending.",
            "created_at": now - timedelta(hours=9),
            "updated_at": now - timedelta(hours=9),
        },
        {
            "id": demo_id("comment-driver-import"),
            "task_id": demo_id("task-driver-import"),
            "author_id": demo_id("user-boris"),
            "text": "Review data includes one duplicate license scenario.",
            "created_at": now - timedelta(hours=5),
            "updated_at": now - timedelta(hours=5),
        },
        {
            "id": demo_id("comment-signature"),
            "task_id": demo_id("task-intake-signature"),
            "author_id": demo_id("user-dmitry"),
            "text": "QA passed on tablet and desktop intake forms.",
            "created_at": now - timedelta(days=3),
            "updated_at": now - timedelta(days=3),
        },
    ]


def webhook_rows(now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "id": demo_id("webhook-northstar"),
            "organization_id": demo_id("org-northstar"),
            "url": "https://httpbin.org/post",
            "secret_hash": hash_webhook_secret(DEMO_WEBHOOK_SECRET),
            "secret_encrypted": encrypt_webhook_secret(DEMO_WEBHOOK_SECRET),
            "event_types": ["task.created", "task.status_changed"],
            "is_active": True,
            "created_at": now - timedelta(days=21),
            "updated_at": now - timedelta(hours=12),
        },
        {
            "id": demo_id("webhook-medpulse"),
            "organization_id": demo_id("org-medpulse"),
            "url": "https://webhook.site/flowforge-medpulse-demo",
            "secret_hash": hash_webhook_secret(f"{DEMO_WEBHOOK_SECRET}_medpulse"),
            "secret_encrypted": encrypt_webhook_secret(
                f"{DEMO_WEBHOOK_SECRET}_medpulse"
            ),
            "event_types": ["task.created"],
            "is_active": False,
            "created_at": now - timedelta(days=17),
            "updated_at": now - timedelta(days=2),
        },
    ]


def outbox_rows(now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "id": demo_id("outbox-route-map-created"),
            "aggregate_type": "task",
            "aggregate_id": demo_id("task-route-map"),
            "event_type": "task.created",
            "payload": {
                "task_id": str(demo_id("task-route-map")),
                "project_id": str(demo_id("project-dispatch")),
            },
            "status": OutboxStatus.PROCESSED,
            "attempts": 1,
            "next_attempt_at": None,
            "last_error": None,
            "processed_at": now - timedelta(days=8, minutes=-2),
            "created_at": now - timedelta(days=8),
            "updated_at": now - timedelta(days=8, minutes=-2),
        },
        {
            "id": demo_id("outbox-driver-import-status"),
            "aggregate_type": "task",
            "aggregate_id": demo_id("task-driver-import"),
            "event_type": "task.status_changed",
            "payload": {
                "task_id": str(demo_id("task-driver-import")),
                "project_id": str(demo_id("project-dispatch")),
                "old_status": TaskStatus.IN_PROGRESS.value,
                "new_status": TaskStatus.REVIEW.value,
            },
            "status": OutboxStatus.PENDING,
            "attempts": 0,
            "next_attempt_at": now + timedelta(minutes=5),
            "last_error": None,
            "processed_at": None,
            "created_at": now - timedelta(hours=2),
            "updated_at": now - timedelta(hours=2),
        },
        {
            "id": demo_id("outbox-signature-done"),
            "aggregate_type": "task",
            "aggregate_id": demo_id("task-intake-signature"),
            "event_type": "task.status_changed",
            "payload": {
                "task_id": str(demo_id("task-intake-signature")),
                "project_id": str(demo_id("project-patient-intake")),
                "old_status": TaskStatus.REVIEW.value,
                "new_status": TaskStatus.DONE.value,
            },
            "status": OutboxStatus.FAILED,
            "attempts": 5,
            "next_attempt_at": None,
            "last_error": "Webhook endpoint returned 503 during demo replay.",
            "processed_at": None,
            "created_at": now - timedelta(days=3),
            "updated_at": now - timedelta(days=2),
        },
    ]


def webhook_delivery_rows(now: datetime) -> list[dict[str, Any]]:
    event_id = demo_id("outbox-route-map-created")
    return [
        {
            "id": demo_id("delivery-northstar-success"),
            "webhook_id": demo_id("webhook-northstar"),
            "event_id": event_id,
            "payload": {
                "event_id": str(event_id),
                "event_type": "task.created",
                "task_id": str(demo_id("task-route-map")),
            },
            "status_code": 200,
            "response_body": '{"received":true}',
            "attempts": 1,
            "created_at": now - timedelta(days=8, minutes=-3),
        },
        {
            "id": demo_id("delivery-northstar-failed"),
            "webhook_id": demo_id("webhook-northstar"),
            "event_id": demo_id("outbox-driver-import-status"),
            "payload": {
                "event_id": str(demo_id("outbox-driver-import-status")),
                "event_type": "task.status_changed",
                "task_id": str(demo_id("task-driver-import")),
            },
            "status_code": 503,
            "response_body": "service temporarily unavailable",
            "attempts": 2,
            "created_at": now - timedelta(hours=1),
        },
    ]


def refresh_session_rows(now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "id": demo_id("refresh-alice-active"),
            "user_id": demo_id("user-alice"),
            "family_id": demo_id("refresh-family-alice"),
            "jti": demo_id("refresh-jti-alice-active"),
            "token_hash": hash_refresh_token(DEMO_REFRESH_TOKEN),
            "expires_at": now + timedelta(days=30),
            "revoked_at": None,
            "replaced_by_jti": None,
            "created_at": now - timedelta(hours=5),
            "last_used_at": now - timedelta(hours=1),
            "user_agent": "Mozilla/5.0 FlowForge Demo Browser",
            "ip_address": "203.0.113.10",
        },
        {
            "id": demo_id("refresh-boris-revoked"),
            "user_id": demo_id("user-boris"),
            "family_id": demo_id("refresh-family-boris"),
            "jti": demo_id("refresh-jti-boris-revoked"),
            "token_hash": hash_refresh_token("demo-refresh-token-boris-revoked"),
            "expires_at": now + timedelta(days=20),
            "revoked_at": now - timedelta(days=1),
            "replaced_by_jti": demo_id("refresh-jti-boris-replacement"),
            "created_at": now - timedelta(days=7),
            "last_used_at": now - timedelta(days=1),
            "user_agent": "FlowForge Mobile Demo",
            "ip_address": "198.51.100.25",
        },
    ]


def idempotency_rows(now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "id": demo_id("idempotency-task-create-alice"),
            "user_id": demo_id("user-alice"),
            "key": "demo-create-task-route-map",
            "request_hash": "a" * 64,
            "response_body": {
                "id": str(demo_id("task-route-map")),
                "title": "Add route map filters",
            },
            "status_code": 201,
            "expires_at": now + timedelta(hours=24),
            "created_at": now - timedelta(hours=6),
            "updated_at": now - timedelta(hours=6),
        }
    ]


def audit_rows(now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "id": demo_id("audit-org-created"),
            "actor_id": demo_id("user-alice"),
            "organization_id": demo_id("org-northstar"),
            "action": "organization.created",
            "entity_type": "organization",
            "entity_id": demo_id("org-northstar"),
            "old_data": None,
            "new_data": {"name": "Northstar Logistics", "slug": "northstar-logistics"},
            "request_id": "req_demo_org_created",
            "created_at": now - timedelta(days=44),
        },
        {
            "id": demo_id("audit-task-status"),
            "actor_id": demo_id("user-boris"),
            "organization_id": demo_id("org-northstar"),
            "action": "task.status_changed",
            "entity_type": "task",
            "entity_id": demo_id("task-driver-import"),
            "old_data": {"status": TaskStatus.IN_PROGRESS.value},
            "new_data": {"status": TaskStatus.REVIEW.value},
            "request_id": "req_demo_task_status",
            "created_at": now - timedelta(days=1),
        },
        {
            "id": demo_id("audit-webhook-created"),
            "actor_id": demo_id("user-admin"),
            "organization_id": demo_id("org-medpulse"),
            "action": "webhook.created",
            "entity_type": "webhook_subscription",
            "entity_id": demo_id("webhook-medpulse"),
            "old_data": None,
            "new_data": {
                "url": "https://webhook.site/flowforge-medpulse-demo",
                "event_types": ["task.created"],
                "is_active": False,
            },
            "request_id": "req_demo_webhook_created",
            "created_at": now - timedelta(days=17),
        },
    ]


async def seed_existing_active_users_access(
    session: AsyncSession,
    now: datetime,
) -> int:
    result = await session.execute(
        select(User.id, User.role)
        .where(User.is_active.is_(True))
        .order_by(User.created_at.asc())
    )
    rows = [
        {
            "id": demo_id(f"member-northstar-existing-{user_id}"),
            "organization_id": demo_id("org-northstar"),
            "user_id": user_id,
            "role": (
                OrganizationRole.ADMIN
                if user_role == UserRole.ADMIN
                else OrganizationRole.MEMBER
            ),
            "created_at": now,
            "updated_at": now,
        }
        for user_id, user_role in result.all()
    ]
    return await insert_rows(session, OrganizationMember, rows)


async def seed() -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    table_rows: list[tuple[type[Any], Sequence[dict[str, Any]]]] = [
        (Organization, organization_rows(now)),
        (OrganizationMember, member_rows(now)),
        (Project, project_rows(now)),
        (Task, task_rows(now)),
        (TaskStatusHistory, history_rows(now)),
        (TaskComment, comment_rows(now)),
        (OutboxEvent, outbox_rows(now)),
        (WebhookDelivery, webhook_delivery_rows(now)),
        (RefreshSession, refresh_session_rows(now)),
        (IdempotencyKey, idempotency_rows(now)),
        (AuditLog, audit_rows(now)),
    ]

    async with async_session_maker() as session:
        async with session.begin():
            inserted = {"users": await upsert_user_rows(session, user_rows(now))}
            inserted.update(
                {
                    model.__tablename__: await insert_rows(session, model, rows)
                    for model, rows in table_rows
                }
            )
            inserted["webhook_subscriptions"] = await upsert_webhook_rows(
                session, webhook_rows(now)
            )
            inserted[
                "existing_users_demo_memberships"
            ] = await seed_existing_active_users_access(session, now)

    for table_name, row_count in inserted.items():
        print(f"{table_name}: inserted {row_count}")
    print("Demo users password: DemoPass123!")


async def main() -> None:
    try:
        await seed()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
