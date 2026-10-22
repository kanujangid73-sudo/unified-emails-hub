"""Database tables.

Mail is stored per connected account and keyed by the provider's own ids (remote_id), so a
sync can be repeated safely: a message that is already stored is updated, never duplicated.
Thread rows keep a few denormalized fields (latest date, snippet, unread count) so the
unified inbox can be listed with one indexed query.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(**kwargs) -> Column:
    return Column(DateTime(timezone=True), **kwargs)


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=32)
    password_hash: str
    is_guest: bool = False  # temporary demo account, deleted after GUEST_TTL_HOURS
    created_at: datetime = Field(default_factory=utcnow, sa_column=_timestamp(nullable=False))


class MailAccount(SQLModel, table=True):
    """A mailbox the user connected (a Gmail address, an Outlook address, an IMAP server...)."""

    __table_args__ = (UniqueConstraint("user_id", "email", name="uq_account_user_email"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    # Which adapter talks to the mailbox: "demo", "gmail", "outlook" or "imap".
    provider: str = Field(max_length=16)
    # How the account looks in the UI (icon and name): "gmail", "outlook" or "imap".
    brand: str = Field(max_length=16)
    email: str = Field(max_length=254)
    display_name: str = Field(default="", max_length=80)
    color: str = Field(default="#6366f1", max_length=9)
    # Encrypted JSON (see crypto.py): OAuth tokens, or IMAP/SMTP server and password.
    credentials: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    # Provider-specific position of the last sync (Gmail historyId, Graph delta links, IMAP UID...).
    sync_cursor: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    last_synced_at: datetime | None = Field(default=None, sa_column=_timestamp(nullable=True))
    sync_error: str | None = Field(default=None, max_length=500)
    # Background sync: when the account is next due, and consecutive failures (for backoff).
    next_sync_at: datetime | None = Field(default=None, sa_column=_timestamp(nullable=True, index=True))
    failure_count: int = 0
    # The provider rejected the credentials; syncing stops until the user reconnects.
    needs_reauth: bool = False
    created_at: datetime = Field(default_factory=utcnow, sa_column=_timestamp(nullable=False))


class Thread(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("account_id", "remote_id", name="uq_thread_account_remote"),
        # The unified inbox: newest first, across all of a user's accounts.
        Index("ix_thread_user_inbox", "user_id", "is_archived", "last_message_at", "id"),
        # Inbox tabs (Primary, Updates, Promotions, Newsletters).
        Index("ix_thread_user_category", "user_id", "category", "is_archived", "last_message_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    account_id: int = Field(foreign_key="mailaccount.id", index=True)
    remote_id: str = Field(max_length=255)
    subject: str = Field(default="", max_length=500)
    snippet: str = Field(default="", max_length=300)
    # Names of the other people in the conversation, for the inbox row.
    participants: str = Field(default="", max_length=500)
    message_count: int = 0
    unread_count: int = 0
    attachment_count: int = 0
    is_starred: bool = False
    is_archived: bool = False
    last_message_at: datetime = Field(default_factory=utcnow, sa_column=_timestamp(nullable=False))
    # Computed on the server from the messages (insights.py); nothing is sent to an AI for this.
    category: str | None = Field(default=None, max_length=16)  # primary, updates, promotions, newsletters
    suspicious_reasons: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))  # JSON list
    # Cached on-demand summary, valid while message_count still equals summary_for.
    summary: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    summary_for: int | None = None


class Message(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("account_id", "remote_id", name="uq_message_account_remote"),)

    id: int | None = Field(default=None, primary_key=True)
    thread_id: int = Field(foreign_key="thread.id", index=True)
    account_id: int = Field(foreign_key="mailaccount.id")
    remote_id: str = Field(max_length=255)
    from_name: str = Field(default="", max_length=200)
    from_email: str = Field(default="", max_length=254)
    to: str = Field(default="", max_length=2000)  # comma-separated addresses
    cc: str = Field(default="", max_length=2000)
    subject: str = Field(default="", max_length=500)
    snippet: str = Field(default="", max_length=300)
    body_text: str = ""
    body_html: str = ""
    is_read: bool = False
    is_starred: bool = False
    is_sent: bool = False  # written by the account owner
    # RFC 5322 headers, so replies can be threaded by every mail client.
    message_id_header: str = Field(default="", max_length=998)
    references_header: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    # The List-Unsubscribe header (RFC 2369): how to leave a mailing list.
    list_unsubscribe: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    sent_at: datetime = Field(sa_column=_timestamp(nullable=False))


class Attachment(SQLModel, table=True):
    """What a message has attached. Content is downloaded from the provider when asked for,
    except for copies the hub keeps itself (`data`), such as mail sent over SMTP."""

    id: int | None = Field(default=None, primary_key=True)
    message_id: int = Field(foreign_key="message.id", index=True)
    filename: str = Field(max_length=255)
    mime_type: str = Field(default="application/octet-stream", max_length=127)
    size: int = 0
    ref: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    content_id: str = Field(default="", max_length=255)
    inline: bool = False
    data: bytes | None = None
