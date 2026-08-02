"""use composite key for processed messages

Revision ID: 463c1b611628
Revises: 25ee7457c422
Create Date: 2026-08-02 20:56:56.634933

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "463c1b611628"
down_revision: Union[str, Sequence[str], None] = "25ee7457c422"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Use a composite primary key for processed messages."""
    op.drop_constraint(
        "pk_processed_messages",
        "processed_messages",
        type_="primary",
    )
    op.create_primary_key(
        "pk_processed_messages",
        "processed_messages",
        ["message_id", "consumer_name"],
    )


def downgrade() -> None:
    """Restore the primary key on message_id."""
    op.drop_constraint(
        "pk_processed_messages",
        "processed_messages",
        type_="primary",
    )
    op.create_primary_key(
        "pk_processed_messages",
        "processed_messages",
        ["message_id"],
    )
