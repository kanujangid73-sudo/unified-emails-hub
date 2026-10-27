from datetime import timedelta

from sqlmodel import func, select

from app.models import MailAccount, Message, utcnow
from app.providers import ProviderError
from app.providers.demo import DemoProvider
from tests.conftest import register


def biggest(client, headers):
    res = client.get("/api/cleanup", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def count(session, account_id, sender):
    query = select(func.count()).select_from(Message).where(Message.account_id == account_id, func.lower(Message.from_email) == sender)
    return session.exec(query).one()


def test_overview_ranks_senders_by_space(client, demo):
    data = biggest(client, demo)
    senders = data["senders"]
    assert data["total_count"] > 0 and data["total_size"] >= sum(s["size"] for s in senders)
    assert [s["size"] for s in senders] == sorted((s["size"] for s in senders), reverse=True)
    assert all(s["size"] > 0 and 0 <= s["read"] <= s["count"] for s in senders)
    assert any(s["can_unsubscribe"] for s in senders)


def test_trash_removes_a_senders_mail_but_keeps_starred(client, demo, session, monkeypatch):
    trashed = []
    monkeypatch.setattr(DemoProvider, "trash", lambda self, ids: trashed.extend(ids))
    target = next(s for s in biggest(client, demo)["senders"] if s["count"] > 1)
    keep = session.exec(
        select(Message).where(Message.account_id == target["account_id"], func.lower(Message.from_email) == target["email"])
    ).first()
    keep.is_starred = True
    session.add(keep)
    session.commit()

    res = client.post("/api/cleanup/trash", headers=demo, json={"senders": [{"account_id": target["account_id"], "email": target["email"]}]})
    assert res.status_code == 200, res.text
    assert res.json() == {"trashed": target["count"] - 1, "failed": []}
    assert len(trashed) == target["count"] - 1 and keep.remote_id not in trashed
    session.expire_all()
    assert count(session, target["account_id"], target["email"]) == 1


def test_only_older_mail_can_be_chosen(client, demo, session):
    target = next(s for s in biggest(client, demo)["senders"] if s["count"] > 1)
    messages = session.exec(
        select(Message).where(Message.account_id == target["account_id"], func.lower(Message.from_email) == target["email"]).order_by(Message.sent_at)
    ).all()
    for i, m in enumerate(messages):
        m.sent_at = utcnow() - timedelta(days=400 if i == 0 else 1)
        session.add(m)
    session.commit()

    body = {"senders": [{"account_id": target["account_id"], "email": target["email"]}], "older_than_days": 365}
    assert client.post("/api/cleanup/trash", headers=demo, json=body).json()["trashed"] == 1


def test_a_refusing_provider_keeps_the_mail(client, demo, session, monkeypatch):
    def refuse(self, ids):
        raise ProviderError("server said no")

    monkeypatch.setattr(DemoProvider, "trash", refuse)
    target = biggest(client, demo)["senders"][0]
    before = count(session, target["account_id"], target["email"])
    res = client.post("/api/cleanup/trash", headers=demo, json={"senders": [{"account_id": target["account_id"], "email": target["email"]}]})
    account = session.get(MailAccount, target["account_id"])
    assert res.json() == {"trashed": 0, "failed": [account.email]}
    assert count(session, target["account_id"], target["email"]) == before


def test_other_peoples_mail_is_out_of_reach(client, demo, session):
    target = biggest(client, demo)["senders"][0]
    stranger = register(client, "mallory")
    assert biggest(client, stranger)["senders"] == []
    res = client.post("/api/cleanup/trash", headers=stranger, json={"senders": [{"account_id": target["account_id"], "email": target["email"]}]})
    assert res.json()["trashed"] == 0
    assert count(session, target["account_id"], target["email"]) == target["count"]
