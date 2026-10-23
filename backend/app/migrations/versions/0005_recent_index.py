"""index for newest-first lists without the archive filter (found by scripts/benchmark.py)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-23 10:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("thread", schema=None) as batch_op:
        batch_op.create_index("ix_thread_user_recent", ["user_id", "last_message_at", "id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("thread", schema=None) as batch_op:
        batch_op.drop_index("ix_thread_user_recent")
