"""The provider adapter interface.

Every mail service speaks its own protocol: Gmail has a REST API with history ids,
Outlook has Microsoft Graph with delta links, other servers speak IMAP with UIDs. Each one
gets an adapter that translates it into the same small vocabulary below, so the sync engine
and the rest of the app never need to know which service a mailbox lives on.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Address:
    email: str
    name: str = ""


@dataclass(frozen=True)
class RemoteAttachment:
    """A file attached to a message. The content stays with the provider and is fetched on demand
    with `ref`; only copies the hub keeps itself (sent over SMTP, demo mail) carry `data`."""

    filename: str
    mime_type: str
    size: int
    ref: str  # provider-specific: Gmail part id, Graph attachment id, index of the MIME part
    content_id: str = ""
    inline: bool = False
    data: bytes | None = None


@dataclass(frozen=True)
class RemoteMessage:
    """One message as the provider reports it, already converted to plain Python values."""

    remote_id: str
    thread_id: str
    sender: Address
    to: tuple[Address, ...]
    subject: str
    sent_at: datetime
    body_text: str = ""
    body_html: str = ""
    cc: tuple[Address, ...] = ()
    is_read: bool = False
    is_starred: bool = False
    # None when the provider has no notion of archiving (IMAP): the hub then keeps its own state.
    is_archived: bool | None = None
    # RFC 5322 Message-ID and References headers, used to thread replies correctly.
    message_id_header: str = ""
    references: str = ""
    # The List-Unsubscribe header, e.g. "<https://news.example/unsub?u=1>, <mailto:leave@news.example>".
    list_unsubscribe: str = ""
    attachments: tuple[RemoteAttachment, ...] = ()
    # Bytes the message takes up in the mailbox, when the provider reports it.
    size: int | None = None


@dataclass(frozen=True)
class RemoteFlags:
    """A change to a message the hub already has, without its content (e.g. read on a phone)."""

    remote_id: str
    is_read: bool | None = None
    is_starred: bool | None = None
    is_archived: bool | None = None


@dataclass
class SyncBatch:
    """The result of one fetch: what changed, and where the next fetch should resume.

    `cursor` is opaque to the sync engine. It is stored on the account and passed back on the
    next call, so each sync only transfers what changed since the previous one.
    """

    messages: list[RemoteMessage] = field(default_factory=list)
    flags: list[RemoteFlags] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    cursor: str | None = None
    # True when the provider has more changes waiting; the engine keeps fetching.
    has_more: bool = False
    # The provider can no longer give changes since the old cursor (Gmail history expired,
    # IMAP UIDVALIDITY changed): the stored copy is discarded and synced again from scratch.
    reset: bool = False


@dataclass(frozen=True)
class FlagChange:
    """A change the user made in the hub, to be written back to the real mailbox."""

    is_read: bool | None = None
    is_starred: bool | None = None
    is_archived: bool | None = None


@dataclass(frozen=True)
class ReplyContext:
    remote_id: str  # the provider's id of the message being answered
    thread_remote_id: str
    message_id_header: str = ""
    references: str = ""


@dataclass(frozen=True)
class OutgoingAttachment:
    filename: str
    mime_type: str
    data: bytes


@dataclass(frozen=True)
class OutgoingMessage:
    sender: Address
    to: tuple[Address, ...]
    subject: str
    body_text: str
    cc: tuple[Address, ...] = ()
    reply_to: ReplyContext | None = None
    attachments: tuple[OutgoingAttachment, ...] = ()


class ProviderError(Exception):
    """A provider call failed. `retryable` is True for timeouts, rate limits and server errors."""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class AuthError(ProviderError):
    """The provider rejected the account's credentials (password changed, access revoked).

    Retrying won't help: the user has to reconnect the account.
    """


class MailProvider(ABC):
    @abstractmethod
    def fetch_changes(self, cursor: str | None) -> SyncBatch:
        """Return changes since `cursor` (a first batch of recent mail when it is None)."""

    @abstractmethod
    def update_flags(self, thread_remote_id: str, message_remote_ids: list[str], change: FlagChange) -> None:
        """Apply read/star/archive changes to the real mailbox."""

    @abstractmethod
    def send(self, message: OutgoingMessage) -> RemoteMessage | None:
        """Send an email.

        Returns the sent message when the provider won't report it on the next sync (so the
        hub stores it right away), or None when the next sync will pick it up.
        """

    def fetch_attachment(self, message_remote_id: str, ref: str) -> bytes:
        """Download one attachment's content."""
        raise ProviderError("This mailbox can't download attachments")

    def trash(self, message_remote_ids: list[str]) -> None:
        """Move messages to the mailbox's Trash, where the provider keeps them for a while (Gmail
        and Outlook: 30 days) before deleting them for good. Messages already gone are skipped."""
        raise ProviderError("This mailbox can't delete mail")

    def disconnect(self) -> None:
        """Called when the user removes the account, e.g. to revoke OAuth access. Best effort."""
