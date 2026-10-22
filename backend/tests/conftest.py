import os

# Configure before the app is imported: throwaway database and a fixed secret.
# Set TEST_DATABASE_URL to run the suite against Postgres; its tables are dropped between tests.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL or "sqlite://"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-at-least-32-bytes"
os.environ["SYNC_SCHEDULER"] = "false"  # tests run sync explicitly
os.environ["ALLOW_PRIVATE_HOSTS"] = "true"
os.environ["GEMINI_API_KEY"] = ""  # offline assistant unless a test turns Gemini on

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import database
from app.routers.auth import demo_limiter

if TEST_DATABASE_URL:
    test_engine = database.engine
else:
    # One shared in-memory database for the whole app during tests.
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    database.engine = test_engine

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    SQLModel.metadata.drop_all(test_engine)
    with test_engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))  # so startup migrates from scratch
    demo_limiter.hits.clear()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def session(client):
    with Session(test_engine) as s:
        yield s


def register(client, username="alice", password="secret123"):
    res = client.post("/api/auth/register", json={"username": username, "password": password})
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture()
def auth(client):
    return register(client)


@pytest.fixture()
def demo(client):
    """Headers for a demo guest with the three sample mailboxes synced."""
    res = client.post("/api/auth/demo")
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}
