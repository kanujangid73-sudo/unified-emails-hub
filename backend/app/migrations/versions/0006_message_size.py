"""message sizes, for the clean-up view

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-26 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("message", schema=None) as batch_op:
        batch_op.add_column(sa.Column("size", sa.Integer(), nullable=False, server_default="0"))
    # Mail synced before this has no size: estimate it the way sync.estimate_size does.
    op.execute(
        "UPDATE message SET size = length(body_text) + length(body_html)"
        " + coalesce((SELECT sum(a.size) FROM attachment a WHERE a.message_id = message.id), 0) * 4 / 3"
    )


def downgrade() -> None:
    with op.batch_alter_table("message", schema=None) as batch_op:
        batch_op.drop_column("size")
