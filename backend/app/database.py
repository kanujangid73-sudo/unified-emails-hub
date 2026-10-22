from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection
from sqlmodel import Session, create_engine

from .config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def make_engine(url: str):
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # Hosted Postgres (Neon, Supabase) closes idle connections and limits how many are open,
    # so check connections before use and keep the pool small. Store times in UTC.
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=5,
        connect_args={"options": "-c timezone=UTC"},
    )


engine = make_engine(settings.database_url)


def alembic_config(connection: Connection | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def _recover_sqlite_batch(conn: Connection) -> None:
    """Finish or undo a schema change that was interrupted on SQLite.

    SQLite can't alter most columns, so Alembic copies the table to _alembic_tmp_<name>, drops
    the original and renames the copy. That isn't transactional on SQLite: if the process dies
    (or the file is locked, e.g. by a sync tool) half way, the copy is left behind and every
    later upgrade fails. If the original still exists the copy is redundant; otherwise the
    copy holds the data and takes the original's place.
    """
    tables = {name for (name,) in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for tmp in (t for t in tables if t.startswith("_alembic_tmp_")):
        original = tmp.removeprefix("_alembic_tmp_")
        if original in tables:
            conn.exec_driver_sql(f'DROP TABLE "{tmp}"')
        else:
            conn.exec_driver_sql(f'ALTER TABLE "{tmp}" RENAME TO "{original}"')


def init_db() -> None:
    from .insights import backfill

    with engine.begin() as conn:
        if conn.dialect.name == "sqlite":
            _recover_sqlite_batch(conn)
        command.upgrade(alembic_config(conn), "head")
    with Session(engine) as session:
        backfill(session)  # threads stored before a newer version added categories


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
