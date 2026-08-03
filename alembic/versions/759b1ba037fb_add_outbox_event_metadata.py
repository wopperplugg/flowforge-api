"""add outbox event metadata

Revision ID: 759b1ba037fb
Revises: 463c1b611628
Create Date: 2026-08-03 22:01:39.379670
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "759b1ba037fb"
down_revision: str | Sequence[str] | None = "463c1b611628"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add metadata fields to outbox events."""

    # Временно используем server_default, чтобы заполнить существующие строки.
    op.add_column(
        "outbox_events",
        sa.Column(
            "event_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )

    # Сначала nullable=True: существующие строки ещё не имеют значения.
    op.add_column(
        "outbox_events",
        sa.Column(
            "correlation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    op.add_column(
        "outbox_events",
        sa.Column(
            "causation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    op.add_column(
        "outbox_events",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    # Для старых событий используем ID самого события как correlation_id.
    op.execute(
        """
        UPDATE outbox_events
        SET correlation_id = id
        WHERE correlation_id IS NULL
        """
    )

    # После заполнения можно установить NOT NULL.
    op.alter_column(
        "outbox_events",
        "correlation_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )

    # Убираем временный server default.
    # Новые значения будет задавать SQLAlchemy-модель.
    op.alter_column(
        "outbox_events",
        "event_version",
        existing_type=sa.Integer(),
        server_default=None,
    )

    op.create_index(
        "ix_outbox_events_correlation_id",
        "outbox_events",
        ["correlation_id"],
        unique=False,
    )

    op.create_index(
        "ix_outbox_events_organization_id",
        "outbox_events",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove metadata fields from outbox events."""

    op.drop_index(
        "ix_outbox_events_organization_id",
        table_name="outbox_events",
    )
    op.drop_index(
        "ix_outbox_events_correlation_id",
        table_name="outbox_events",
    )

    op.drop_column("outbox_events", "organization_id")
    op.drop_column("outbox_events", "causation_id")
    op.drop_column("outbox_events", "correlation_id")
    op.drop_column("outbox_events", "event_version")
