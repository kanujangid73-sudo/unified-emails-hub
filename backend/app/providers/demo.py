"""An adapter for the sample mailboxes used by the one-click demo.

It behaves like a real provider: it pages through changes, hands back a cursor, and only
returns messages that "arrived" after that cursor. Messages dated in the future stay hidden
until their time comes, so a sync a few minutes later picks them up, the same way new mail
shows up from Gmail or Outlook. Sending never leaves the server: the message is only stored
in the hub, so the demo can't be used to send real email.
"""

import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from .base import Address, FlagChange, MailProvider, OutgoingMessage, ProviderError, RemoteAttachment, RemoteMessage, SyncBatch


def _utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes; everything in this app is stored in UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _with_unique_times(messages: list[RemoteMessage]) -> list[RemoteMessage]:
    """Nudge equal timestamps apart by a second, so the time-based cursor never skips a message."""
    result: list[RemoteMessage] = []
    for message in messages:
        if result and message.sent_at <= result[-1].sent_at:
            message = replace(message, sent_at=result[-1].sent_at + timedelta(seconds=1))
        result.append(message)
    return result


class DemoProvider(MailProvider):
    page_size = 100

    def __init__(self, brand: str, email: str, anchor: datetime, now=None) -> None:
        from ..demo_data import MAILBOXES, OWNER_NAME  # demo_data imports this package, so import it lazily

        if brand not in MAILBOXES:
            raise ProviderError(f"No sample mailbox for {brand!r}")
        self.owner = Address(email, OWNER_NAME)
        self.mailbox = _with_unique_times(MAILBOXES[brand](self.owner, _utc(anchor)))
        self._now = now or (lambda: datetime.now(timezone.utc))

    def fetch_changes(self, cursor: str | None) -> SyncBatch:
        since = datetime.fromisoformat(cursor) if cursor else None
        now = self._now()
        due = [m for m in self.mailbox if m.sent_at <= now and (since is None or m.sent_at > since)]
        page = due[: self.page_size]
        if not page:
            return SyncBatch(cursor=cursor)
        return SyncBatch(messages=page, cursor=page[-1].sent_at.isoformat(), has_more=len(due) > self.page_size)

    def update_flags(self, thread_remote_id: str, message_remote_ids: list[str], change: FlagChange) -> None:
        # The sample mailboxes are generated from code, so there is nothing to write back.
        # The hub keeps the change in its own database, as it does for every provider.
        return None

    def trash(self, message_remote_ids: list[str]) -> None:
        return None  # nothing to delete remotely; the hub removes its copy

    def fetch_attachment(self, message_remote_id: str, ref: str) -> bytes:
        for message in self.mailbox:
            if message.remote_id == message_remote_id:
                for attachment in message.attachments:
                    if attachment.ref == ref and attachment.data is not None:
                        return attachment.data
        raise ProviderError("That attachment doesn't exist")

    def send(self, message: OutgoingMessage) -> RemoteMessage:
        key = uuid.uuid4().hex
        return RemoteMessage(
            remote_id=f"sent-{key}",
            thread_id=message.reply_to.thread_remote_id if message.reply_to else f"sent-t-{key}",
            sender=self.owner,
            to=message.to,
            cc=message.cc,
            subject=message.subject,
            sent_at=self._now(),
            body_text=message.body_text,
            is_read=True,
            message_id_header=f"<{key}@demo.example>",
            attachments=tuple(
                RemoteAttachment(filename=a.filename, mime_type=a.mime_type, size=len(a.data), ref=str(i), data=a.data)
                for i, a in enumerate(message.attachments)
            ),
        )
