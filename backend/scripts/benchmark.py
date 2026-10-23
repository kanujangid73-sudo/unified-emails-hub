"""Measure sync throughput and inbox/search latency on a large synthetic mailbox.

    python -m scripts.benchmark                      # SQLite file in a temp folder
    DATABASE_URL=postgresql://... python -m scripts.benchmark --messages 20000

It runs the real sync engine (batches, upserts, thread refresh, categories) against a fake
provider, then times the same functions the API calls. In GitHub Actions the results are added
to the job summary.
"""

import argparse
import os
import random
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--messages", type=int, default=10_000)
    parser.add_argument("--repeat", type=int, default=30)
    return parser.parse_args()


ARGS = parse_args()
if not os.getenv("DATABASE_URL"):
    os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/benchmark.db"
os.environ.setdefault("SECRET_KEY", "benchmark-secret-key-that-is-long-enough")
os.environ["SYNC_SCHEDULER"] = "false"

from sqlmodel import Session  # noqa: E402

from app import database  # noqa: E402
from app.models import MailAccount, User  # noqa: E402
from app.providers import Address, FlagChange, MailProvider, RemoteMessage, SyncBatch  # noqa: E402
from app.routers.threads import list_threads  # noqa: E402
from app.sync import sync_account  # noqa: E402

WORDS = (
    "invoice meeting project roadmap deploy release sync search postgres python react design review budget "
    "travel train ticket hotel dinner weekend cricket photos family order delivery payment receipt account "
    "password security update newsletter offer sale discount report quarterly planning hiring interview"
).split()
OWNER = Address("me@bench.example", "Bench Owner")


class SyntheticProvider(MailProvider):
    """N messages in threads of 1-4, 200 senders, newest last; pages of 100 like Gmail."""

    page_size = 100

    def __init__(self, count: int, start: datetime) -> None:
        rng = random.Random(42)
        senders = [Address(f"person{i}@corp{i % 37}.example", f"Person {i}") for i in range(200)]
        self.messages = []
        thread = 0
        while len(self.messages) < count:
            thread += 1
            size = rng.choice((1, 1, 1, 2, 2, 3, 4))
            subject = " ".join(rng.choices(WORDS, k=5)).capitalize()
            for _ in range(size):
                n = len(self.messages)
                body = " ".join(rng.choices(WORDS, k=rng.randint(40, 160)))
                html = f"<p>{body}</p><p><a href='https://x.example/{n}'>link</a></p>" if n % 10 == 0 else ""
                self.messages.append(
                    RemoteMessage(
                        remote_id=f"m{n}",
                        thread_id=f"t{thread}",
                        sender=OWNER if n % 9 == 0 else rng.choice(senders),
                        to=(OWNER,),
                        subject=subject,
                        sent_at=start + timedelta(minutes=n),
                        body_text=body,
                        body_html=html,
                        is_read=rng.random() < 0.8,
                        is_archived=rng.random() < 0.5,
                        list_unsubscribe="<https://news.example/u>" if n % 7 == 0 else "",
                    )
                )

    def fetch_changes(self, cursor):
        start = int(cursor or 0)
        page = self.messages[start : start + self.page_size]
        end = start + len(page)
        return SyncBatch(messages=page, cursor=str(end), has_more=end < len(self.messages))

    def update_flags(self, thread_remote_id, message_remote_ids, change: FlagChange):
        pass

    def send(self, message):
        return None


def timed(fn, repeat):
    samples = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t) * 1000)
    samples.sort()
    return statistics.median(samples), samples[int(len(samples) * 0.95) - 1]


def main() -> None:
    database.init_db()
    engine = database.engine
    dialect = engine.dialect.name
    start = datetime.now(timezone.utc) - timedelta(days=60)
    provider = SyntheticProvider(ARGS.messages, start)

    with Session(engine) as session:
        user = User(username=f"bench{int(time.time())}", password_hash="x")
        session.add(user)
        session.commit()
        account = MailAccount(user_id=user.id, provider="bench", brand="imap", email=OWNER.email)
        session.add(account)
        session.commit()

        t = time.perf_counter()
        result = sync_account(session, account, lambda _: provider)
        # One sync call stops after 50 pages; keep going like the scheduler would.
        while account.sync_cursor and int(account.sync_cursor) < len(provider.messages):
            more = sync_account(session, account, lambda _: provider)
            result.new_messages += more.new_messages
        full = time.perf_counter() - t
        assert result.error is None, result.error

        # 50 new messages arrive: an incremental sync.
        provider.messages += SyntheticProvider(50, start + timedelta(days=59)).messages
        for i, m in enumerate(provider.messages[-50:]):
            provider.messages[-50 + i] = RemoteMessage(**{**m.__dict__, "remote_id": f"new{i}", "thread_id": f"new-t{i}"})
        t = time.perf_counter()
        sync_account(session, account, lambda _: provider)
        incremental = (time.perf_counter() - t) * 1000

        def page(**kw):
            return lambda: list_threads(folder="all", account_id=None, category=None, q="", cursor=None, limit=50, user=user, session=session, **kw)

        first = list_threads(folder="all", account_id=None, category=None, q="", cursor=None, limit=50, user=user, session=session)
        cursor = first.next_cursor
        for _ in range(40):  # walk 40 pages deep for the keyset measurement
            cursor = list_threads(folder="all", account_id=None, category=None, q="", cursor=cursor, limit=50, user=user, session=session).next_cursor

        def search(q):
            return lambda: list_threads(folder="all", account_id=None, category=None, q=q, cursor=None, limit=50, user=user, session=session)

        rows = [
            ("Inbox, first page (50 conversations)", timed(lambda: list_threads(folder="inbox", account_id=None, category=None, q="", cursor=None, limit=50, user=user, session=session), ARGS.repeat)),
            ("All mail, first page", timed(page(), ARGS.repeat)),
            ("All mail, page 41 (keyset cursor)", timed(lambda: list_threads(folder="all", account_id=None, category=None, q="", cursor=cursor, limit=50, user=user, session=session), ARGS.repeat)),
            ("Tab: Newsletters", timed(lambda: list_threads(folder="inbox", account_id=None, category="newsletters", q="", cursor=None, limit=50, user=user, session=session), ARGS.repeat)),
            ('Search "roadmap"', timed(search("roadmap"), ARGS.repeat)),
            ('Search "invoice payment"', timed(search("invoice payment"), ARGS.repeat)),
            ('Search "from:person7 is:unread"', timed(search("from:person7 is:unread"), ARGS.repeat)),
        ]

    lines = [
        f"### Benchmark: {ARGS.messages:,} messages on {dialect}",
        "",
        "| Operation | Result |",
        "|---|---|",
        f"| Full sync of {ARGS.messages:,} messages | {full:.1f} s ({ARGS.messages / full:,.0f} messages/s) |",
        f"| Incremental sync of 50 new messages | {incremental:.0f} ms |",
    ]
    lines += [f"| {name} | p50 {p50:.1f} ms, p95 {p95:.1f} ms |" for name, (p50, p95) in rows]
    report = "\n".join(lines)
    print(report)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report + "\n")


if __name__ == "__main__":
    sys.exit(main())
