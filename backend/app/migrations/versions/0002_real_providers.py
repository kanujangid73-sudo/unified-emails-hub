"""real providers: credentials, scheduled sync, reply headers, full-text search

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22 12:08:03.009781
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Postgres keeps a weighted search document for every message, maintained by the database
# itself (a generated column), with a GIN index for fast matching. The 'simple' configuration
# doesn't stem words, which suits mixed-language mail (English, Hindi, Hinglish) better than
# an English stemmer. Dots and @ in addresses are split so "zestro" finds no-reply@zestro.example.
SEARCH_VECTOR = """
    setweight(to_tsvector('simple', coalesce(subject, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(from_name, '') || ' ' ||
              regexp_replace(coalesce(from_email, ''), '[@.]', ' ', 'g')), 'B') ||
    setweight(to_tsvector('simple', left(coalesce(body_text, ''), 100000)), 'C')
"""


def upgrade() -> None:
    with op.batch_alter_table("mailaccount", schema=None) as batch_op:
        batch_op.add_column(sa.Column("credentials", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("needs_reauth", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.alter_column("sync_cursor", existing_type=sa.VARCHAR(length=2048), type_=sa.Text(), existing_nullable=True)
        batch_op.create_index(batch_op.f("ix_mailaccount_next_sync_at"), ["next_sync_at"], unique=False)

    with op.batch_alter_table("message", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cc", sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("message_id_header", sqlmodel.sql.sqltypes.AutoString(length=998), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("references_header", sa.Text(), server_default="", nullable=False))

    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"ALTER TABLE message ADD COLUMN search_vector tsvector GENERATED ALWAYS AS ({SEARCH_VECTOR}) STORED")
        op.execute("CREATE INDEX ix_message_search ON message USING gin (search_vector)")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_message_search")
        op.execute("ALTER TABLE message DROP COLUMN IF EXISTS search_vector")

    with op.batch_alter_table("message", schema=None) as batch_op:
        batch_op.drop_column("references_header")
        batch_op.drop_column("message_id_header")
        batch_op.drop_column("cc")

    with op.batch_alter_table("mailaccount", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_mailaccount_next_sync_at"))
        batch_op.alter_column("sync_cursor", existing_type=sa.Text(), type_=sa.VARCHAR(length=2048), existing_nullable=True)
        batch_op.drop_column("needs_reauth")
        batch_op.drop_column("failure_count")
        batch_op.drop_column("next_sync_at")
        batch_op.drop_column("credentials")
