import base64
import json
import time
from email import message_from_bytes

import httpx
import pytest
from sqlmodel import select

from app.models import MailAccount, Message, Thread, User
from app.providers import Address, AuthError, FlagChange, OutgoingMessage, ReplyContext
from app.providers.gmail import GmailProvider
from app.providers.oauth import OAuthApp, OAuthSession
from app.sync import sync_account
from tests.fakes import FakeGmail, gmail_message

APP = OAuthApp("gmail", "client", "secret", "https://accounts.google.com/auth", "https://oauth2.googleapis.com/token", ("scope",), revoke_url="https://oauth2.googleapis.com/revoke")


def provider_for(fake: FakeGmail, expires_in: int = 3600, saved: list | None = None) -> GmailProvider:
    credentials = {"access_token": "access-0", "refresh_token": "refresh-1", "expires_at": int(time.time()) + expires_in}
    session = OAuthSession(APP, credentials, httpx.Client(transport=fake.transport()), (saved if saved is not None else []).append)
    return GmailProvider(session)


def sample(fake: FakeGmail) -> None:
    fake.add(
        gmail_message("m1", "t1", ["INBOX", "UNREAD"], subject="Trip plans", html="<p>Let's <b>go</b></p>"),
        gmail_message("m2", "t1", ["INBOX", "STARRED"], subject="Re: Trip plans"),
        gmail_message("m3", "t2", ["CATEGORY_UPDATES"], subject="Receipt"),  # no INBOX: archived
        gmail_message("m4", "t3", ["DRAFT"], subject="Unfinished"),
    )


def collect(provider: GmailProvider, cursor=None):
    batches = []
    while True:
        batch = provider.fetch_changes(cursor)
        batches.append(batch)
        cursor = batch.cursor
        if not batch.has_more:
            return batches, cursor


def test_backfill_pages_through_recent_mail_and_maps_labels():
    fake = FakeGmail()
    sample(fake)
    batches, cursor = collect(provider_for(fake))

    assert len(batches) == 2  # two list pages
    messages = {m.remote_id: m for b in batches for m in b.messages}
    assert set(messages) == {"m1", "m2", "m3"}
    assert [d for b in batches for d in b.deleted] == ["m4"]  # drafts don't belong in the hub
    m1, m2, m3 = messages["m1"], messages["m2"], messages["m3"]
    assert (m1.is_read, m1.is_archived, m1.thread_id) == (False, False, "t1")
    assert m1.body_text == "Hi there" and m1.body_html == "<p>Let's <b>go</b></p>"
    assert m1.sender == Address("priya@example.net", "Priya Sharma")
    assert m1.message_id_header == "<m1@mail.example>"
    assert (m2.is_read, m2.is_starred) == (True, True)
    assert m3.is_archived is True
    assert json.loads(cursor) == {"history": "1000"}
    listing = next(r for r in fake.requests if r.url.path.endswith("/messages"))
    assert listing.url.params["q"] == "newer_than:30d"


def test_history_brings_new_mail_label_changes_and_deletions():
    fake = FakeGmail()
    sample(fake)
    _, cursor = collect(provider_for(fake))
    fake.add(gmail_message("m5", "t1", ["INBOX", "UNREAD"], subject="Re: Trip plans"))
    fake.history_pages = [
        {
            "history": [
                {"messagesAdded": [{"message": {"id": "m5", "threadId": "t1"}}]},
                {"labelsRemoved": [{"message": {"id": "m1", "threadId": "t1", "labelIds": ["INBOX"]}, "labelIds": ["UNREAD"]}]},
                {"labelsAdded": [{"message": {"id": "m2", "threadId": "t1", "labelIds": ["INBOX", "TRASH"]}, "labelIds": ["TRASH"]}]},
                {"messagesDeleted": [{"message": {"id": "m3", "threadId": "t2"}}]},
            ],
            "historyId": "1050",
        }
    ]
    batch = provider_for(fake).fetch_changes(cursor)

    assert [m.remote_id for m in batch.messages] == ["m5"]
    assert [(f.remote_id, f.is_read, f.is_archived) for f in batch.flags] == [("m1", True, False)]
    assert sorted(batch.deleted) == ["m2", "m3"]  # trashed counts as gone
    assert json.loads(batch.cursor) == {"history": "1050"}
    assert batch.has_more is False


def test_expired_history_triggers_a_full_resync():
    fake = FakeGmail()
    fake.history_pages = None
    batch = provider_for(fake).fetch_changes(json.dumps({"history": "1"}))
    assert batch.reset is True and batch.cursor is None and batch.has_more is True


def test_token_is_refreshed_before_expiry_and_saved():
    fake = FakeGmail()
    saved = []
    provider_for(fake, expires_in=10, saved=saved).identity()
    assert fake.tokens.grants[0]["grant_type"] == "refresh_token"
    assert saved[0]["access_token"] == "access-1"
    assert saved[0]["refresh_token"] == "refresh-1"  # Google doesn't resend it; the old one is kept
    assert fake.requests[-1].headers["Authorization"] == "Bearer access-1"


def test_401_refreshes_once_and_retries():
    fake = FakeGmail()
    fake.unauthorized_once = True
    assert provider_for(fake).identity() == Address("me@example.com")
    assert len(fake.tokens.grants) == 1


def test_revoked_access_raises_auth_error():
    fake = FakeGmail()
    fake.tokens.fail_refresh = True
    with pytest.raises(AuthError):
        provider_for(fake, expires_in=0).identity()


def test_flag_changes_become_label_changes():
    fake = FakeGmail()
    provider = provider_for(fake)
    provider.update_flags("t1", ["m1"], FlagChange(is_read=True, is_archived=True))
    provider.update_flags("t1", ["m1"], FlagChange(is_starred=True))
    provider.update_flags("t1", ["m1"], FlagChange(is_read=False, is_archived=False, is_starred=False))
    assert fake.modified == [
        ("t1", {"addLabelIds": [], "removeLabelIds": ["UNREAD", "INBOX"]}),
        ("t1", {"addLabelIds": ["STARRED"], "removeLabelIds": []}),
        ("t1", {"addLabelIds": ["UNREAD", "INBOX"], "removeLabelIds": ["STARRED"]}),
    ]


def test_reply_is_sent_in_the_thread_with_reply_headers():
    fake = FakeGmail()
    reply = ReplyContext(remote_id="m2", thread_remote_id="t1", message_id_header="<m2@mail.example>", references="<m1@mail.example>")
    provider_for(fake).send(
        OutgoingMessage(sender=Address("me@example.com", "Me"), to=(Address("priya@example.net"),), subject="Re: Trip plans", body_text="Sounds good!", reply_to=reply)
    )
    sent = fake.sent[0]
    assert sent["threadId"] == "t1"
    mime = message_from_bytes(base64.urlsafe_b64decode(sent["raw"]))
    assert mime["In-Reply-To"] == "<m2@mail.example>"
    assert mime["References"] == "<m1@mail.example> <m2@mail.example>"
    assert mime["Subject"] == "Re: Trip plans"


def test_full_sync_through_the_engine(session):
    fake = FakeGmail()
    sample(fake)
    user = User(username="gm", password_hash="x")
    session.add(user)
    session.commit()
    account = MailAccount(user_id=user.id, provider="gmail", brand="gmail", email="me@example.com")
    session.add(account)
    session.commit()

    result = sync_account(session, account, lambda _: provider_for(fake))
    assert (result.new_messages, result.error) == (3, None)
    threads = {t.remote_id: t for t in session.exec(select(Thread)).all()}
    assert threads["t1"].message_count == 2 and threads["t1"].unread_count == 1 and threads["t1"].is_starred
    assert threads["t2"].is_archived is True
    # HTML-only mail still gets searchable text.
    assert session.exec(select(Message).where(Message.remote_id == "m1")).one().body_text == "Hi there"

    fake.history_pages = [{"history": [{"messagesDeleted": [{"message": {"id": "m3"}}]}], "historyId": "2000"}]
    result = sync_account(session, account, lambda _: provider_for(fake))
    assert result.deleted_messages == 1
    assert "t2" not in {t.remote_id for t in session.exec(select(Thread)).all()}  # empty thread removed
    assert json.loads(account.sync_cursor) == {"history": "2000"}


def test_trash_and_size():
    fake = FakeGmail()
    sample(fake)
    fake.messages["m1"]["sizeEstimate"] = 5120
    sizes = {m.remote_id: m.size for b in collect(provider_for(fake))[0] for m in b.messages}
    assert sizes["m1"] == 5120

    provider_for(fake).trash(["m1", "gone"])  # an already deleted message is skipped
    assert fake.trashed == ["m1"]
