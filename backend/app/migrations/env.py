"""Alembic environment.

The app runs migrations on startup (database.run_migrations), passing its own connection.
From the command line, run Alembic in the backend folder, e.g.:
    alembic revision --autogenerate -m "add column"
    alembic upgrade head
"""

from alembic import context
from sqlmodel import SQLModel

from app import models  # noqa: F401  (registers the tables on SQLModel.metadata)
from app.config import settings
from app.database import make_engine

config = context.config
target_metadata = SQLModel.metadata


def run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite can't alter columns in place; batch mode recreates the table instead.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    with make_engine(settings.database_url).connect() as conn:
        run(conn)
        conn.commit()
