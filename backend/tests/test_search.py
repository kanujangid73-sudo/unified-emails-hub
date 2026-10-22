from datetime import datetime, timezone

from app.search import parse_query, tsquery
from tests.test_threads import all_pages, inbox


def test_parse_query_splits_words_and_operators():
    parsed = parse_query('invoice "spice route" from:zestro is:unread is:starred after:2026-09-01 before:2026/10/01 label:x')
    assert parsed.words == ["invoice", "spice route", "label:x"]
    assert parsed.senders == ["zestro"]
    assert parsed.unread is True and parsed.starred is True
    assert parsed.after == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert parsed.before == datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert parse_query('unclosed "quote').words == ["unclosed", "quote"]


def test_tsquery_uses_prefixes_and_only_word_characters():
    assert tsquery(["Roadmap", "Q4"]) == "roadmap:* & q4:*"
    assert tsquery(["no-reply@zestro.example"]) == "no:* & reply:* & zestro:* & example:*"
    assert tsquery(["!&|:*()"]) is None  # no way to inject tsquery operators
    assert tsquery(["नमस्ते"]) == "नमस्ते:*"


def test_operators_filter_the_inbox(client, demo):
    from_priya = all_pages(client, demo, folder="all", q="from:priya")
    assert from_priya and all("Priya" in t["participants"] for t in from_priya)
    assert all(t["unread_count"] > 0 for t in all_pages(client, demo, folder="all", q="is:unread"))
    assert all(t["is_starred"] for t in all_pages(client, demo, folder="all", q="is:starred"))
    assert all_pages(client, demo, folder="all", q="from:priya is:starred")[0]["subject"] == "Weekend trip to the hills?"
    to_work = all_pages(client, demo, folder="all", q="to:northwind")
    assert to_work and len(to_work) < len(all_pages(client, demo, folder="all"))


def test_date_operators(client, demo):
    everything = all_pages(client, demo, folder="all")
    recent = all_pages(client, demo, folder="all", q="after:2100-01-01")
    old = all_pages(client, demo, folder="all", q="before:2000-01-01")
    assert recent == [] and old == []
    assert len(all_pages(client, demo, folder="all", q="after:2000-01-01")) == len(everything)


def test_words_and_operators_combine(client, demo):
    threads = inbox(client, demo, q="order from:zestro", folder="all")["threads"]
    assert threads and all("Zestro" in t["participants"] for t in threads)
    assert "Your order from Spice Route" in [t["subject"] for t in threads]
    assert "Trip" not in " ".join(t["subject"] for t in threads)
