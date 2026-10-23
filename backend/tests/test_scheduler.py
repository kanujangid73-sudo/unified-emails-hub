from datetime import timedelta

from sqlmodel import Session, select

from app import database, scheduler
from app import sync as sync_module
from app.models import MailAccount, User, utcnow
from app.providers import AuthError, ProviderError, SyncBatch
from app.sync import as_utc, backoff


class Provider:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def fetch_changes(self, cursor):
        self.calls += 1
        if self.error:
            raise self.error
        return SyncBatch(cursor="c")


def accounts(session, count=2) -> list[MailAccount]:
    user = User(username="sched", password_hash="x")
    session.add(user)
    session.commit()
    made = [MailAccount(user_id=user.id, provider="test", brand="imap", email=f"a{i}@example.com") for i in range(count)]
    session.add_all(made)
    session.commit()
    return made


def use(monkeypatch, provider: Provider) -> None:
    monkeypatch.setattr(sync_module, "get_provider", lambda account: provider)


def reload(account_id: int) -> MailAccount:
    with Session(database.engine) as s:
        return s.get(MailAccount, account_id)


def test_due_accounts_are_synced_and_rescheduled(session, monkeypatch):
    made = accounts(session)
    provider = Provider()
    use(monkeypatch, provider)

    assert scheduler.sync_due_accounts() == 2
    assert provider.calls == 2
    for account in made:
        fresh = reload(account.id)
        assert fresh.sync_cursor == "c"
        assert as_utc(fresh.next_sync_at) > utcnow() + timedelta(minutes=4)

    assert scheduler.sync_due_accounts() == 0  # nothing is due any more


def test_an_account_can_only_be_claimed_once(session):
    account = accounts(session, 1)[0]
    now = utcnow()
    assert scheduler.claim(session, account.id, now) is True
    assert scheduler.claim(session, account.id, now) is False  # another process loses the race
    assert scheduler.claim(session, account.id, now + scheduler.LEASE + timedelta(seconds=1)) is True  # lease expired


def test_failures_back_off_exponentially(session, monkeypatch):
    account = accounts(session, 1)[0]
    use(monkeypatch, Provider(ProviderError("rate limited", retryable=True)))

    scheduler.sync_due_accounts()
    first = reload(account.id)
    assert first.failure_count == 1 and first.sync_error == "rate limited"
    assert utcnow() + timedelta(seconds=40) < as_utc(first.next_sync_at) < utcnow() + timedelta(seconds=80)

    scheduler.sync_due_accounts(now=as_utc(first.next_sync_at) + timedelta(seconds=1))
    assert reload(account.id).failure_count == 2
    assert backoff(10) <= timedelta(hours=6) * 1.2


def test_rejected_credentials_stop_syncing_until_reconnected(session, monkeypatch):
    account = accounts(session, 1)[0]
    provider = Provider(AuthError("revoked"))
    use(monkeypatch, provider)

    scheduler.sync_due_accounts()
    assert reload(account.id).needs_reauth is True
    scheduler.sync_due_accounts(now=utcnow() + timedelta(days=1))
    assert provider.calls == 1


def test_a_crashing_provider_does_not_stop_the_others(session, monkeypatch):
    made = accounts(session, 2)

    class Flaky(Provider):
        def fetch_changes(self, cursor):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("bug in an adapter")
            return SyncBatch(cursor="ok")

    use(monkeypatch, Flaky())
    assert scheduler.sync_due_accounts() == 2
    states = sorted((reload(a.id).sync_error or "", reload(a.id).sync_cursor or "") for a in made)
    assert states == [("", "ok"), ("Unexpected error while syncing. It will be retried.", "")]


def test_cleanup_removes_expired_demo_accounts(client, demo, session):
    guest = session.exec(select(User).where(User.is_guest == True)).one()  # noqa: E712
    guest.created_at = utcnow() - timedelta(days=2)
    session.add(guest)
    session.commit()
    assert scheduler.cleanup() == 1
