from sqlmodel import select

from app.models import MailAccount
from app.routers.messages import send_limiter
from tests.test_threads import all_pages, inbox


def account_id(client, headers, brand="gmail"):
    return next(a["id"] for a in client.get("/api/accounts", headers=headers).json() if a["brand"] == brand)


def test_new_message_appears_in_sent_not_inbox(client, demo):
    res = client.post(
        "/api/messages",
        headers=demo,
        json={"account_id": account_id(client, demo), "to": ["sam.lee@example.org"], "subject": "Lunch?", "body": "Free on Friday?"},
    )
    assert res.status_code == 201, res.text
    thread = res.json()
    assert thread["subject"] == "Lunch?" and thread["participants"] == "me"
    assert thread["id"] in [t["id"] for t in all_pages(client, demo, folder="sent")]
    assert thread["id"] not in [t["id"] for t in all_pages(client, demo)]
    message = client.get(f"/api/threads/{thread['id']}", headers=demo).json()["messages"][0]
    assert message["is_sent"] and message["to"] == "sam.lee@example.org"


def test_reply_joins_the_conversation(client, demo):
    thread = inbox(client, demo, q="Cricket this Saturday")["threads"][0]
    res = client.post(
        "/api/messages",
        headers=demo,
        json={"account_id": thread["account_id"], "to": ["rohan.mehta@example.net"], "body": "I'm in!", "reply_to_thread_id": thread["id"]},
    )
    assert res.status_code == 201, res.text
    updated = res.json()
    assert updated["id"] == thread["id"] and updated["message_count"] == thread["message_count"] + 1
    assert updated["participants"] == "Rohan Mehta, me" and not updated["is_archived"]
    last = client.get(f"/api/threads/{thread['id']}", headers=demo).json()["messages"][-1]
    assert last["subject"] == "Re: Cricket this Saturday?" and last["body_text"] == "I'm in!"


def test_reply_must_use_the_conversations_account(client, demo):
    thread = inbox(client, demo, q="Cricket this Saturday")["threads"][0]
    other = account_id(client, demo, "outlook")
    res = client.post("/api/messages", headers=demo, json={"account_id": other, "to": ["x@example.org"], "body": "hi", "reply_to_thread_id": thread["id"]})
    assert res.status_code == 404


def test_validation_and_header_injection(client, demo):
    base = {"account_id": account_id(client, demo), "body": "hi"}
    assert client.post("/api/messages", headers=demo, json={**base, "to": []}).status_code == 422
    assert client.post("/api/messages", headers=demo, json={**base, "to": ["bad address"]}).status_code == 422
    res = client.post("/api/messages", headers=demo, json={**base, "to": ["a@example.org"], "subject": "Hi\r\nBcc: victim@example.org"})
    assert res.json()["subject"] == "Hi Bcc: victim@example.org"  # newlines removed: no extra header


def test_sending_is_rate_limited(client, demo):
    send_limiter.hits.clear()
    send_limiter.limit = 2
    try:
        body = {"account_id": account_id(client, demo), "to": ["a@example.org"], "body": "hi"}
        assert client.post("/api/messages", headers=demo, json=body).status_code == 201
        assert client.post("/api/messages", headers=demo, json=body).status_code == 201
        assert client.post("/api/messages", headers=demo, json=body).status_code == 429
    finally:
        send_limiter.limit = 30
        send_limiter.hits.clear()


def test_accounts_needing_reconnect_cannot_send(client, demo, session):
    account = session.exec(select(MailAccount).where(MailAccount.brand == "gmail")).one()
    account.needs_reauth = True
    session.add(account)
    session.commit()
    res = client.post("/api/messages", headers=demo, json={"account_id": account.id, "to": ["a@example.org"], "body": "hi"})
    assert res.status_code == 409
