import pytest
from sqlalchemy import create_engine, inspect, text

from app.database import _recover_sqlite_batch


@pytest.fixture()
def conn():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        yield connection


def test_leftover_copy_is_dropped_when_the_original_exists(conn):
    conn.execute(text("CREATE TABLE mailaccount (id INTEGER)"))
    conn.execute(text("CREATE TABLE _alembic_tmp_mailaccount (id INTEGER)"))
    _recover_sqlite_batch(conn)
    assert inspect(conn).get_table_names() == ["mailaccount"]


def test_copy_replaces_a_dropped_original(conn):
    conn.execute(text("CREATE TABLE _alembic_tmp_message (id INTEGER)"))
    conn.execute(text("INSERT INTO _alembic_tmp_message VALUES (42)"))
    _recover_sqlite_batch(conn)
    assert inspect(conn).get_table_names() == ["message"]
    assert conn.execute(text("SELECT id FROM message")).scalar() == 42
