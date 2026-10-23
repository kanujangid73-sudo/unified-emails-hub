from datetime import timedelta

from sqlmodel import select

from app.models import MailAccount, Message, Thread, User, utcnow
from tests.conftest import register


def test_register_login_and_me(client):
    register(client, "bob", "hunter22")
    res = client.post("/api/auth/login", json={"username": "BOB", "password": "hunter22"})
    assert res.status_code == 200
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {res.json()['access_token']}"}).json()
    assert me["username"] == "bob"
    assert me["created_at"].endswith("Z")  # UTC, so browsers show local time correctly


def test_wrong_password_and_duplicate_name(client):
    register(client, "bob", "hunter22")
    assert client.post("/api/auth/login", json={"username": "bob", "password": "nope123"}).status_code == 401
    assert client.post("/api/auth/register", json={"username": "Bob", "password": "x123456"}).status_code == 409


def test_endpoints_need_a_token(client):
    assert client.get("/api/threads").status_code == 401
    assert client.get("/api/accounts").status_code == 401


def test_demo_creates_three_synced_mailboxes(client, demo):
    accounts = client.get("/api/accounts", headers=demo).json()
    assert [a["brand"] for a in accounts] == ["gmail", "outlook", "imap"]
    assert all(a["last_synced_at"] and a["sync_error"] is None for a in accounts)
    assert all(a["unread_count"] > 0 for a in accounts)
    me = client.get("/api/auth/me", headers=demo).json()
    assert me["is_guest"] is True


def test_demo_is_rate_limited(client):
    from app.routers.auth import demo_limiter

    demo_limiter.limit = 2
    try:
        assert client.post("/api/auth/demo").status_code == 201
        assert client.post("/api/auth/demo").status_code == 201
        assert client.post("/api/auth/demo").status_code == 429
    finally:
        demo_limiter.limit = 10


def test_expired_guests_are_removed_with_their_mail(client, demo, session):
    guest = session.exec(select(User).where(User.is_guest == True)).one()  # noqa: E712
    old_name = guest.username
    guest.created_at = utcnow() - timedelta(days=2)
    session.add(guest)
    session.commit()

    res = client.post("/api/auth/demo")  # a new demo login purges expired guests
    assert res.status_code == 201, res.text

    session.expire_all()
    # Only the new guest is left (SQLite may give it the old id, so compare names).
    users = session.exec(select(User)).all()
    assert len(users) == 1 and users[0].username != old_name
    new_guest = users[0]
    assert {a.user_id for a in session.exec(select(MailAccount)).all()} == {new_guest.id}
    assert len(session.exec(select(MailAccount)).all()) == 3
    account_ids = {a.id for a in session.exec(select(MailAccount)).all()}
    assert {t.account_id for t in session.exec(select(Thread)).all()} <= account_ids
    assert {m.account_id for m in session.exec(select(Message)).all()} <= account_ids


def test_health_needs_no_login_or_database(client):
    res = client.get("/api/health")
    assert res.status_code == 200 and res.json()["status"] == "ok"
