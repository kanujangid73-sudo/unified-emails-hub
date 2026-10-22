from datetime import datetime, timezone

from sqlmodel import select

from app.insights import backfill, categorize, registrable_domain, signals_of, suspicion, unsubscribe_targets
from app.models import Message, Thread
from tests.test_threads import all_pages


def message(**kw) -> Message:
    defaults = dict(thread_id=1, account_id=1, remote_id="r", from_name="", from_email="", subject="", body_text="", sent_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    return Message(**{**defaults, **kw})


def test_registrable_domain():
    assert registrable_domain("deals.shopkart.example") == "shopkart.example"
    assert registrable_domain("mail.yahoo.co.in") == "yahoo.co.in"
    assert registrable_domain("gmail.com") == "gmail.com"


def test_categories():
    person = message(from_name="Priya", from_email="priya@example.net", subject="Trip?")
    promo = message(from_email="hello@shop.example", subject="Up to 60% off headphones", list_unsubscribe="<https://shop.example/u>")
    news = message(from_email="hello@news.example", subject="Issue #12: Postgres 19", list_unsubscribe="<https://news.example/u>")
    receipt = message(from_email="no-reply@shop.example", subject="Your order has shipped")
    mine = message(from_email="me@example.com", subject="Re: Your order", is_sent=True)
    assert categorize([person]) == "primary"
    assert categorize([promo]) == "promotions"
    assert categorize([news]) == "newsletters"
    assert categorize([receipt]) == "updates"
    assert categorize([receipt, mine]) == "primary"  # you replied: it's a conversation now


def test_phishing_needs_strong_or_combined_evidence():
    phish = message(
        from_name="PayWave Security",
        from_email="security@paywave-account-verify.example",
        subject="URGENT: Your account will be suspended",
        body_text="Verify now: http://paywave-account-verify.example/login",
    )
    reasons = suspicion(phish)
    assert len(reasons) == 3 and "imitates PayWave" in reasons[0]
    # Real senders with urgent words alone are not flagged.
    reset = message(from_name="GameVerse", from_email="no-reply@gameverse.example", subject="Reset your password", body_text="Use this link within 1 hour: https://gameverse.example/reset")
    assert suspicion(reset) == []
    legit = message(from_name="ShopKart Deals", from_email="hello@deals.shopkart.example", subject="Sale")
    assert suspicion(legit) == []


def test_account_signals():
    assert signals_of(message(subject="Welcome to Zestro!")) == ["signup"]
    assert signals_of(message(subject="Verify your email for FitPulse")) == ["signup"]
    assert signals_of(message(subject="Your StreamBox password was changed")) == ["security"]
    assert signals_of(message(subject="482913 is your PayWave verification code")) == ["code"]
    assert signals_of(message(subject="Order SK-1 confirmed")) == ["activity"]
    assert signals_of(message(subject="Photos from the trek")) == []


def test_unsubscribe_targets():
    m = message(list_unsubscribe="<mailto:leave@news.example>, <https://news.example/u?id=1>")
    assert unsubscribe_targets(m) == ("https://news.example/u?id=1", "mailto:leave@news.example")
    body = message(body_html='<a href="https://shop.example/unsubscribe?u=1&amp;x=2">Unsubscribe</a>')
    assert unsubscribe_targets(body) == ("https://shop.example/unsubscribe?u=1&x=2", None)


def test_inbox_tabs_and_phishing_flag(client, demo):
    newsletters = all_pages(client, demo, folder="all", category="newsletters")
    assert newsletters and all(t["category"] == "newsletters" for t in newsletters)
    assert any("Morning Byte" in t["subject"] for t in newsletters)
    primary = {t["subject"] for t in all_pages(client, demo, folder="all", category="primary")}
    assert "Weekend trip to the hills?" in primary and not any("Deals" in s for s in primary)
    suspicious = [t for t in all_pages(client, demo, folder="all") if t["suspicious_reasons"]]
    assert [t["subject"] for t in suspicious] == ["URGENT: Your account will be suspended in 24 hours"]


def test_account_finder(client, demo):
    data = client.get("/api/insights/accounts", headers=demo).json()
    services = {s["name"]: s for s in data["services"]}
    assert {a["email"] for a in services["ShopKart"]["accounts"]} == {"alex.morgan@example.com", "alex_m90@oldmail.example"}
    assert [a["email"] for a in services["PayWave"]["accounts"]] == ["alex.morgan@example.com"]  # the phishing copy doesn't count
    assert services["Linkly"]["accounts"][0]["email"] == "alex.morgan@northwind.example"
    assert "signup" in services["Zestro"]["accounts"][0]["signals"]
    assert not any("verify" in s["domain"] for s in data["services"])
    assert not any(s["domain"].endswith("example.net") for s in data["services"])  # people aren't services
    welcome = client.get(f"/api/threads/{services['Zestro']['accounts'][0]['thread_id']}", headers=demo).json()
    assert "Zestro" in welcome["subject"]


def test_subscriptions_and_bulk_archive(client, demo):
    subs = {s["name"]: s for s in client.get("/api/insights/subscriptions", headers=demo).json()}
    byte = subs["The Morning Byte"]
    assert byte["count"] == 10 and byte["unsubscribe_url"] == "https://morningbyte.example/unsubscribe?u=demo"

    res = client.post("/api/threads/bulk", headers=demo, json={"thread_ids": byte["thread_ids"], "change": {"is_archived": True}})
    assert sorted(res.json()["updated"]) == sorted(byte["thread_ids"]) and res.json()["failed"] == []
    assert not any("Morning Byte" in t["subject"] for t in all_pages(client, demo))


def test_bulk_skips_other_peoples_threads(client, demo, auth):
    mine = client.get("/api/threads", headers=demo).json()["threads"][0]["id"]
    res = client.post("/api/threads/bulk", headers=auth, json={"thread_ids": [mine], "change": {"is_read": True}})
    assert res.json() == {"updated": [], "failed": [mine]}


def test_backfill_analyses_old_threads(client, demo, session):
    for thread in session.exec(select(Thread)).all():
        thread.category = None
        session.add(thread)
    session.commit()
    assert backfill(session) > 100
    assert session.exec(select(Thread).where(Thread.category == None)).all() == []  # noqa: E711
