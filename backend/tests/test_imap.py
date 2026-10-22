import json
from datetime import datetime, timezone

import pytest

from app.providers import Address, AuthError, FlagChange, OutgoingMessage, ReplyContext
from app.providers import imap as imap_module
from app.providers.imap import ImapProvider
from tests.fakes import FakeImap, FakeSmtp, rfc822

NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)
CREDENTIALS = {"username": "me@oldmail.example", "password": "app-pass", "imap_host": "imap.oldmail.example", "smtp_host": "smtp.oldmail.example"}


def provider(server: FakeImap, smtp: FakeSmtp | None = None) -> ImapProvider:
    return ImapProvider(CREDENTIALS, "me@oldmail.example", connect=server.connect, smtp=(smtp or FakeSmtp()).connect, now=lambda: NOW)


def mailbox() -> FakeImap:
    server = FakeImap()
    server.add(3, rfc822("Long time no see!", msgid="<a@old>"), flags=["\\Seen"])
    server.add(5, rfc822("Re: Long time no see!", sender="Me <me@oldmail.example>", msgid="<b@old>", in_reply_to="<a@old>", references="<a@old>"), flags=["\\Seen"])
    server.add(9, rfc822("Weekly loot", sender="GameVerse <loot@gameverse.example>", msgid="<c@gv>", html="<p>Claim <b>500</b> coins</p>"), flags=["\\Flagged"])
    return server


def test_first_sync_reads_recent_mail_without_marking_it_read():
    server = mailbox()
    batch = provider(server).fetch_changes(None)

    assert [m.remote_id for m in batch.messages] == ["7:3", "7:5", "7:9"]
    first, reply, loot = batch.messages
    assert first.thread_id == reply.thread_id == "<a@old>"  # threaded by References
    assert loot.thread_id == "<c@gv>"
    assert first.is_read and not loot.is_read and loot.is_starred
    assert loot.body_html == "<p>Claim <b>500</b> coins</p>\n"
    assert first.is_archived is None  # IMAP has no archive; the hub keeps its own
    assert first.sender == Address("neha@oldmail.example", "Neha Kapoor")
    assert json.loads(batch.cursor) == {"v": "7", "last": 9}
    assert server.readonly == [True]  # a read-only SELECT can't change flags by accident


def test_next_sync_fetches_only_new_uids_and_refreshes_flags():
    server = mailbox()
    p = provider(server)
    cursor = p.fetch_changes(None).cursor
    server.add(12, rfc822("Double coins weekend", sender="loot@gameverse.example", msgid="<d@gv>"))
    server.mail[3]["flags"].discard("\\Seen")  # marked unread on the phone

    batch = p.fetch_changes(cursor)
    assert [m.remote_id for m in batch.messages] == ["7:12"]
    assert json.loads(batch.cursor)["last"] == 12

    batch = p.fetch_changes(batch.cursor)
    assert batch.messages == []  # "UID 13:*" returns 12 again; it is ignored
    assert ("7:3", False) in [(f.remote_id, f.is_read) for f in batch.flags]


def test_paging_large_backfills():
    server = FakeImap()
    for uid in range(1, 8):
        server.add(uid, rfc822(f"Message {uid}", msgid=f"<{uid}@x>"))
    p = provider(server)
    p.page_size = 3
    batch = p.fetch_changes(None)
    assert [m.remote_id for m in batch.messages] == ["7:1", "7:2", "7:3"] and batch.has_more
    batch = p.fetch_changes(batch.cursor)
    assert [m.remote_id for m in batch.messages] == ["7:4", "7:5", "7:6"] and batch.has_more


def test_uidvalidity_change_resets_the_mailbox():
    server = mailbox()
    cursor = provider(server).fetch_changes(None).cursor
    server.validity = "8"
    batch = provider(server).fetch_changes(cursor)
    assert batch.reset is True and batch.cursor is None


def test_huge_messages_are_stored_without_their_body():
    server = mailbox()
    server.mail[9]["size"] = 50_000_000
    loot = provider(server).fetch_changes(None).messages[-1]
    assert loot.subject == "Weekly loot"
    assert "too large" in loot.body_text and loot.body_html == ""


def test_flags_are_written_back_but_archive_stays_local():
    server = mailbox()
    p = provider(server)
    p.update_flags("<a@old>", ["7:3", "7:9", "6:1"], FlagChange(is_read=False, is_starred=True))
    p.update_flags("<a@old>", ["7:3"], FlagChange(is_archived=True))
    assert server.stores == [("3,9", "-FLAGS", "(\\Seen)"), ("3,9", "+FLAGS", "(\\Flagged)")]  # stale UIDVALIDITY skipped
    assert server.readonly == [False]  # archive didn't even connect


def test_send_uses_smtp_and_keeps_a_threaded_copy():
    smtp = FakeSmtp()
    reply = ReplyContext("7:3", "<a@old>", message_id_header="<a@old>")
    stored = provider(mailbox(), smtp).send(
        OutgoingMessage(sender=Address("me@oldmail.example"), to=(Address("neha@oldmail.example"),), subject="Re: Long time no see!", body_text="Coffee on Friday?", reply_to=reply)
    )
    sent = smtp.sent[0]
    assert sent["In-Reply-To"] == "<a@old>" and sent["To"] == "neha@oldmail.example"
    assert stored.thread_id == "<a@old>" and stored.is_read and stored.remote_id.startswith("local:")
    assert stored.message_id_header == sent["Message-ID"]


def test_rejected_password_is_an_auth_error(monkeypatch):
    class Refuses:
        def __init__(self, *a, **k):
            pass

        def login(self, user, password):
            raise imap_module.imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    monkeypatch.setattr(imap_module.imaplib, "IMAP4_SSL", Refuses)
    with pytest.raises(AuthError):
        ImapProvider(CREDENTIALS, "me@oldmail.example").verify()


def test_list_unsubscribe_header_is_kept():
    server = FakeImap()
    raw = rfc822("Weekly digest", msgid="<n@news>").replace(b"Subject:", b"List-Unsubscribe: <https://news.example/u?id=1>\nSubject:", 1)
    server.add(1, raw)
    assert provider(server).fetch_changes(None).messages[0].list_unsubscribe == "<https://news.example/u?id=1>"
