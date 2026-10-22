"""The sync engine: pulls changes from a provider and stores them.

- Incremental: the account's cursor is passed to the provider, so only changes since the
  last sync are transferred.
- Idempotent: messages and threads are upserted by the provider's ids, so replaying a batch
  (after a crash, a retry or an overlapping sync) never creates duplicates.
- Resumable: the cursor is saved after every batch, together with that batch's messages, so
  an interrupted sync continues where it stopped instead of starting over.
- Self-healing: failures are retried later with exponential backoff; rejected credentials
  stop the account's sync until the user reconnects it.
"""

import logging
import random
import re
import threading
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape

from sqlmodel import Session, delete, func, select

from .config import settings
from .insights import analyze
from .models import Attachment, MailAccount, Message, Thread, utcnow
from .providers import AuthError, MailProvider, ProviderError, RemoteMessage, SyncBatch, get_provider

logger = logging.getLogger("mailhub.sync")

# Safety stop for one sync call; the next call carries on from the saved cursor.
MAX_BATCHES = 50
# Retry delays after failures: 1, 2, 4, 8... minutes, at most 6 hours.
BACKOFF_BASE = timedelta(minutes=1)
BACKOFF_MAX = timedelta(hours=6)


@dataclass
class SyncResult:
    account_id: int
    new_messages: int = 0
    updated_messages: int = 0
    deleted_messages: int = 0
    error: str | None = None


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


_INVISIBLE = re.compile(r"<(script|style|head)\b.*?</\1>", re.S | re.I)
_BREAKS = re.compile(r"<(br|/p|/div|/tr|/h[1-6]|/li)\b[^>]*>", re.I)
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\r\f\v]+")
_SPACE = re.compile(r"\s+")


def html_to_text(html: str) -> str:
    """Readable text from an HTML email, for search and previews."""
    text = _BREAKS.sub("\n", _INVISIBLE.sub(" ", html))
    text = unescape(_TAGS.sub(" ", text))
    lines = (_SPACES.sub(" ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def make_snippet(text: str, html: str = "", length: int = 200) -> str:
    """A one-line preview of a message, from its text body or, failing that, its HTML."""
    flat = _SPACE.sub(" ", text or html_to_text(html)).strip()
    return flat if len(flat) <= length else flat[: length - 1].rstrip() + "…"


def delete_account_mail(session: Session, account_ids: list[int]) -> None:
    """Remove everything the hub stored for some accounts (children before parents)."""
    if not account_ids:
        return
    message_ids = select(Message.id).where(Message.account_id.in_(account_ids))
    session.exec(delete(Attachment).where(Attachment.message_id.in_(message_ids)))
    session.exec(delete(Message).where(Message.account_id.in_(account_ids)))
    session.exec(delete(Thread).where(Thread.account_id.in_(account_ids)))


def _store_attachments(session: Session, stored: dict[str, tuple[Message, RemoteMessage]]) -> None:
    """Replace the attachment rows of the messages in a batch with what the provider reports."""
    ids = [m.id for m, _ in stored.values()]
    session.exec(delete(Attachment).where(Attachment.message_id.in_(ids)))
    for message, remote in stored.values():
        for a in remote.attachments:
            session.add(
                Attachment(
                    message_id=message.id,
                    filename=a.filename[:255],
                    mime_type=(a.mime_type or "application/octet-stream")[:127],
                    size=a.size,
                    ref=a.ref,
                    content_id=a.content_id[:255],
                    inline=a.inline,
                    data=a.data,
                )
            )


def _store_message(session: Session, account: MailAccount, thread: Thread, remote: RemoteMessage, existing: Message | None) -> Message:
    message = existing or Message(account_id=account.id, thread_id=thread.id, remote_id=remote.remote_id, sent_at=remote.sent_at)
    message.thread_id = thread.id
    message.from_name = remote.sender.name[:200]
    message.from_email = remote.sender.email[:254]
    message.to = ", ".join(a.email for a in remote.to)[:2000]
    message.cc = ", ".join(a.email for a in remote.cc)[:2000]
    message.subject = remote.subject[:500]
    message.body_html = remote.body_html
    message.body_text = remote.body_text or html_to_text(remote.body_html)
    message.snippet = make_snippet(message.body_text)
    message.is_read = remote.is_read
    message.is_starred = remote.is_starred
    message.is_sent = _from_owner(remote, account)
    message.message_id_header = remote.message_id_header[:998]
    message.references_header = remote.references
    message.list_unsubscribe = remote.list_unsubscribe
    message.sent_at = as_utc(remote.sent_at)
    session.add(message)
    return message


def _from_owner(remote: RemoteMessage, account: MailAccount) -> bool:
    return remote.sender.email.lower() == account.email.lower()


def refresh_threads(session: Session, thread_ids: set[int], owner_email: str) -> None:
    """Recompute the inbox fields of threads from their messages, and drop threads left empty."""
    if not thread_ids:
        return
    messages = session.exec(select(Message).where(Message.thread_id.in_(thread_ids)).order_by(Message.sent_at, Message.id)).all()
    by_thread: dict[int, list[Message]] = {}
    for message in messages:
        by_thread.setdefault(message.thread_id, []).append(message)
    files = dict(
        session.exec(
            select(Message.thread_id, func.count(Attachment.id))
            .join(Attachment, Attachment.message_id == Message.id)
            .where(Message.thread_id.in_(thread_ids), Attachment.inline == False)  # noqa: E712
            .group_by(Message.thread_id)
        ).all()
    )
    for thread in session.exec(select(Thread).where(Thread.id.in_(thread_ids))).all():
        items = by_thread.get(thread.id, [])
        if not items:
            session.delete(thread)
            continue
        latest = items[-1]
        names: list[str] = []
        for m in items:
            name = "me" if m.from_email.lower() == owner_email.lower() else (m.from_name or m.from_email)
            if name not in names:
                names.append(name)
        thread.subject = items[0].subject or "(no subject)"
        thread.snippet = latest.snippet
        thread.participants = ", ".join(names)[:500]
        thread.message_count = len(items)
        thread.unread_count = sum(not m.is_read for m in items)
        thread.attachment_count = files.get(thread.id, 0)
        thread.is_starred = any(m.is_starred for m in items)
        thread.last_message_at = as_utc(latest.sent_at)
        analyze(thread, items)
        session.add(thread)


def apply_batch(session: Session, account: MailAccount, batch: SyncBatch) -> tuple[int, int, int]:
    """Store one batch of changes. Returns (new, updated, deleted) message counts."""
    if batch.reset:
        delete_account_mail(session, [account.id])
        session.flush()

    touched: set[int] = set()
    # Archive "votes" per thread: a thread is archived when all the evidence in this batch says so.
    votes: dict[int, list[bool]] = defaultdict(list)

    deleted = 0
    if batch.deleted:
        gone = session.exec(select(Message).where(Message.account_id == account.id, Message.remote_id.in_(batch.deleted))).all()
        session.exec(delete(Attachment).where(Attachment.message_id.in_([m.id for m in gone])))
        for message in gone:
            touched.add(message.thread_id)
            session.delete(message)
        deleted = len(gone)

    new = updated = 0
    if batch.messages:
        thread_keys = {m.thread_id for m in batch.messages}
        threads = {
            t.remote_id: t
            for t in session.exec(select(Thread).where(Thread.account_id == account.id, Thread.remote_id.in_(thread_keys))).all()
        }
        created = thread_keys - threads.keys()
        for key in created:
            threads[key] = Thread(user_id=account.user_id, account_id=account.id, remote_id=key)
            session.add(threads[key])
        session.flush()  # assigns ids to new threads

        existing = {
            m.remote_id: m
            for m in session.exec(
                select(Message).where(Message.account_id == account.id, Message.remote_id.in_([m.remote_id for m in batch.messages]))
            ).all()
        }
        stored: dict[str, tuple[Message, RemoteMessage]] = {}
        for remote in batch.messages:
            thread = threads[remote.thread_id]
            is_new = remote.remote_id not in existing
            stored[remote.remote_id] = (_store_message(session, account, thread, remote, existing.get(remote.remote_id)), remote)
            new += is_new
            updated += not is_new
            touched.add(thread.id)
            if remote.is_archived is not None:
                votes[thread.id].append(remote.is_archived)
            elif is_new and not _from_owner(remote, account):
                # Providers without archiving (IMAP): new mail brings a conversation back to the
                # inbox, as in Gmail. Your own reply doesn't.
                votes[thread.id].append(False)
        session.flush()  # ids for new messages, which their attachments point to
        _store_attachments(session, stored)
        for key in created:
            thread = threads[key]
            if not votes[thread.id]:
                # A brand-new conversation you started yourself lives in Sent, not the inbox.
                votes[thread.id].append(True)

    if batch.flags:
        changed = session.exec(
            select(Message).where(Message.account_id == account.id, Message.remote_id.in_([f.remote_id for f in batch.flags]))
        ).all()
        by_id = {m.remote_id: m for m in changed}
        for flags in batch.flags:
            message = by_id.get(flags.remote_id)
            if message is None:
                continue
            if flags.is_read is not None:
                message.is_read = flags.is_read
            if flags.is_starred is not None:
                message.is_starred = flags.is_starred
            if flags.is_archived is not None:
                votes[message.thread_id].append(flags.is_archived)
            session.add(message)
            touched.add(message.thread_id)
            updated += 1

    session.flush()
    for thread_id, thread_votes in votes.items():
        thread = session.get(Thread, thread_id)
        if thread is not None and thread_votes:
            thread.is_archived = all(thread_votes)
    refresh_threads(session, touched, account.email)
    return new, updated, deleted


def store_message(session: Session, account: MailAccount, remote: RemoteMessage) -> Thread:
    """Store a single message right away (e.g. one just sent) and return its thread."""
    apply_batch(session, account, SyncBatch(messages=[remote]))
    session.commit()
    return session.exec(select(Thread).where(Thread.account_id == account.id, Thread.remote_id == remote.thread_id)).one()


def backoff(failures: int) -> timedelta:
    delay = min(BACKOFF_BASE * (2 ** max(failures - 1, 0)), BACKOFF_MAX)
    return delay * random.uniform(0.8, 1.2)  # jitter, so failed accounts don't all retry at once


_locks: dict[int, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()


def _account_lock(account_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks[account_id]


def sync_account(
    session: Session,
    account: MailAccount,
    provider_factory: Callable[[MailAccount], MailProvider] | None = None,
) -> SyncResult:
    """Sync one account. Overlapping syncs of the same account (say, two open tabs) take turns;
    the unique constraints on remote ids back this up across server processes."""
    lock = _account_lock(account.id)
    if not lock.acquire(timeout=60):
        return SyncResult(account_id=account.id, error="Another sync of this account is still running")
    try:
        return _sync(session, account, provider_factory or get_provider)
    finally:
        lock.release()


def _sync(session: Session, account: MailAccount, provider_factory: Callable[[MailAccount], MailProvider]) -> SyncResult:
    session.refresh(account)  # pick up the cursor saved by a sync that finished while we waited
    result = SyncResult(account_id=account.id)
    try:
        provider = provider_factory(account)
        for _ in range(MAX_BATCHES):
            batch = provider.fetch_changes(account.sync_cursor)
            new, updated, deleted = apply_batch(session, account, batch)
            result.new_messages += new
            result.updated_messages += updated
            result.deleted_messages += deleted
            if batch.cursor is not None or batch.reset:
                account.sync_cursor = batch.cursor
            session.add(account)
            session.commit()  # changes and cursor together: a crash replays at most one batch
            if not batch.has_more:
                break
        account.sync_error = None
        account.failure_count = 0
        account.needs_reauth = False
        account.next_sync_at = utcnow() + timedelta(seconds=settings.sync_interval_seconds)
    except AuthError as exc:
        session.rollback()
        result.error = account.sync_error = str(exc)[:500]
        account.needs_reauth = True
        account.next_sync_at = None
        logger.warning("Account %s needs to be reconnected: %s", account.id, exc)
    except Exception as exc:  # noqa: BLE001  (a provider bug must not stop other accounts syncing)
        session.rollback()
        if isinstance(exc, ProviderError):
            result.error = str(exc)[:500]
            logger.warning("Sync failed for account %s: %s", account.id, exc)
        else:
            result.error = "Unexpected error while syncing. It will be retried."
            logger.exception("Sync crashed for account %s", account.id)
        account.sync_error = result.error
        account.failure_count += 1
        account.next_sync_at = utcnow() + backoff(account.failure_count)
    account.last_synced_at = utcnow()
    session.add(account)
    session.commit()
    session.refresh(account)
    return result
