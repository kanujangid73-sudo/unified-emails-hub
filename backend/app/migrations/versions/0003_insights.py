"""insights: thread categories, phishing warnings, cached summaries, List-Unsubscribe

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-22 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("thread", schema=None) as batch_op:
        # NULL means "not analysed yet": existing threads are filled in at startup (insights.backfill).
        batch_op.add_column(sa.Column("category", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True))
        batch_op.add_column(sa.Column("suspicious_reasons", sa.Text(), server_default="", nullable=False))
        batch_op.add_column(sa.Column("summary", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("summary_for", sa.Integer(), nullable=True))
        batch_op.create_index("ix_thread_user_category", ["user_id", "category", "is_archived", "last_message_at"], unique=False)

    with op.batch_alter_table("message", schema=None) as batch_op:
        batch_op.add_column(sa.Column("list_unsubscribe", sa.Text(), server_default="", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("message", schema=None) as batch_op:
        batch_op.drop_column("list_unsubscribe")

    with op.batch_alter_table("thread", schema=None) as batch_op:
        batch_op.drop_index("ix_thread_user_category")
        batch_op.drop_column("summary_for")
        batch_op.drop_column("summary")
        batch_op.drop_column("suspicious_reasons")
        batch_op.drop_column("category")
