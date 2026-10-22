from datetime import datetime, timedelta, timezone

from sqlmodel import func, select

from app.models import MailAccount, Message, Thread, User
from app.providers import Address, FlagChange, MailProvider, ProviderError, RemoteMessage, SyncBatch
from app.providers.demo import DemoProvider
from app.sync import make_snippet, sync_account

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
ME = Address("me@example.com", "Me")


def msg(n: int, thread: str = "t1", minutes: int | None = None, **kw) -> RemoteMessage:
    return RemoteMessage(
        remote_id=f"m{n}",
        thread_id=thread,
        sender=kw.pop("sender", Address(f"friend{n}@example.com", f"Friend {n}")),
        to=(ME,),
        subject=kw.pop("subject", "Hello"),
        sent_at=T0 + timedelta(minutes=n if minutes is None else minutes),
        body_text=kw.pop("body_text", f"Body {n}"),
        **kw,
    )


class ScriptedProvider(MailProvider):
    """Plays back prepared batches. Each call returns the batch for the cursor it is given."""

    def __init__(self, batches: dict[str | None, SyncBatch], fail_on: str = "") -> None:
        self.batches = batches
        self.fail_on = fail_on  # a cursor whose fetch fails ("" = never)
        self.calls: list[str | None] = []

    def fetch_changes(self, cursor):
        self.calls.append(cursor)
        if cursor == self.fail_on:
            raise ProviderError("rate limited", retryable=True)
        return self.batches.get(cursor, SyncBatch(cursor=cursor))

    def update_flags(self, thread_remote_id, message_remote_ids, change: FlagChange):
        pass

    def send(self, message):
        return None


def make_account(session) -> MailAccount:
    user = User(username="syncer", password_hash="x")
    session.add(user)
    session.commit()
    account = MailAccount(user_id=user.id, provider="test", brand="imap", email=ME.email)
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def count(session, model, account) -> int:
    return session.exec(select(func.count()).select_from(model).where(model.account_id == account.id)).one()


def test_sync_stores_threads_and_saves_the_cursor(session):
    account = make_account(session)
    provider = ScriptedProvider({None: SyncBatch([msg(1), msg(2), msg(3, thread="t2")], cursor="c1")})

    result = sync_account(session, account, lambda _: provider)

    assert (result.new_messages, result.updated_messages, result.error) == (3, 0, None)
    assert account.sync_cursor == "c1"
    thread = session.exec(select(Thread).where(Thread.remote_id == "t1")).one()
    assert thread.message_count == 2
    assert thread.unread_count == 2
    assert thread.participants == "Friend 1, Friend 2"
    assert thread.snippet == "Body 2"


def test_next_sync_resumes_from_the_cursor(session):
    account = make_account(session)
    provider = ScriptedProvider({None: SyncBatch([msg(1)], cursor="c1"), "c1": SyncBatch([msg(2)], cursor="c2")})

    sync_account(session, account, lambda _: provider)
    result = sync_account(session, account, lambda _: provider)

    assert provider.calls == [None, "c1"]
    assert result.new_messages == 1
    assert account.sync_cursor == "c2"


def test_replaying_a_batch_never_duplicates(session):
    account = make_account(session)
    batch = [msg(1), msg(2, is_read=True)]
    sync_account(session, account, lambda _: ScriptedProvider({None: SyncBatch(batch, cursor="c1")}))
    # The provider sends the same messages again, now both read (e.g. read on the phone).
    account.sync_cursor = None
    session.add(account)
    session.commit()
    replay = [msg(1, is_read=True), msg(2, is_read=True)]
    result = sync_account(session, account, lambda _: ScriptedProvider({None: SyncBatch(replay, cursor="c1")}))

    assert (result.new_messages, result.updated_messages) == (0, 2)
    assert count(session, Message, account) == 2
    assert count(session, Thread, account) == 1
    assert session.exec(select(Thread)).one().unread_count == 0


def test_has_more_keeps_fetching_pages(session):
    account = make_account(session)
    provider = ScriptedProvider({
        None: SyncBatch([msg(1)], cursor="p1", has_more=True),
        "p1": SyncBatch([msg(2)], cursor="p2", has_more=True),
        "p2": SyncBatch([msg(3)], cursor="p3"),
    })
    result = sync_account(session, account, lambda _: provider)
    assert result.new_messages == 3
    assert account.sync_cursor == "p3"


def test_failure_keeps_finished_batches_and_resumes_after_them(session):
    account = make_account(session)
    provider = ScriptedProvider(
        {None: SyncBatch([msg(1)], cursor="p1", has_more=True), "p2": SyncBatch([msg(3)], cursor="p3")},
        fail_on="p1",
    )
    result = sync_account(session, account, lambda _: provider)

    assert result.error == "rate limited"
    assert account.sync_error == "rate limited"
    assert account.sync_cursor == "p1"  # the first page was saved before the failure
    assert count(session, Message, account) == 1

    provider.fail_on = ""
    provider.batches["p1"] = SyncBatch([msg(2)], cursor="p2", has_more=True)
    result = sync_account(session, account, lambda _: provider)
    assert result.error is None and account.sync_error is None
    assert count(session, Message, account) == 3


def test_new_reply_brings_an_archived_thread_back(session):
    account = make_account(session)
    provider = ScriptedProvider({
        None: SyncBatch([msg(1, is_archived=True)], cursor="c1"),
        "c1": SyncBatch([msg(2)], cursor="c2"),
    })
    sync_account(session, account, lambda _: provider)
    assert session.exec(select(Thread)).one().is_archived is True
    sync_account(session, account, lambda _: provider)
    session.expire_all()
    assert session.exec(select(Thread)).one().is_archived is False


def test_owner_messages_are_marked_sent_and_shown_as_me(session):
    account = make_account(session)
    batch = [msg(1), msg(2, sender=ME, is_read=True)]
    sync_account(session, account, lambda _: ScriptedProvider({None: SyncBatch(batch, cursor="c")}))
    sent = session.exec(select(Message).where(Message.remote_id == "m2")).one()
    assert sent.is_sent is True
    assert session.exec(select(Thread)).one().participants == "Friend 1, me"


def test_snippet_from_html_drops_tags_styles_and_entities():
    html = "<style>p{color:red}</style><p>Hello&nbsp;<b>there</b> &amp; welcome</p><script>x()</script>"
    assert make_snippet("", html) == "Hello there & welcome"
    assert make_snippet("a" * 300).endswith("…") and len(make_snippet("a" * 300)) == 200


def test_demo_provider_delivers_later_mail_on_a_later_sync():
    anchor = T0
    clock = {"now": anchor}
    provider = DemoProvider("gmail", "alex@example.com", anchor, now=lambda: clock["now"])
    provider.page_size = 25

    first, cursor = [], None
    while True:
        batch = provider.fetch_changes(cursor)
        first += batch.messages
        cursor = batch.cursor
        if not batch.has_more:
            break
    assert len(first) > 75  # several pages
    assert all(m.sent_at <= anchor for m in first)
    assert len({m.remote_id for m in first}) == len(first)

    assert provider.fetch_changes(cursor).messages == []
    clock["now"] = anchor + timedelta(minutes=30)
    arrived = provider.fetch_changes(cursor).messages
    assert [m.subject for m in arrived] == ["Train tickets booked!", "Hungry? 40% off your next order"]
