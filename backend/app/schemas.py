import base64
import binascii
import json
import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, field_validator

from .models import Attachment, MailAccount, Message, Thread, User
from .sync import SyncResult, as_utc

# SQLite hands back naive datetimes; mark every outgoing time as UTC so browsers read it right.
UTCDatetime = Annotated[datetime, AfterValidator(as_utc)]


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=6, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    is_guest: bool = False
    created_at: UTCDatetime

    @classmethod
    def of(cls, user: User) -> "UserOut":
        return cls(id=user.id, username=user.username, is_guest=user.is_guest, created_at=user.created_at)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class AccountOut(BaseModel):
    id: int
    provider: str
    brand: str
    email: str
    display_name: str
    color: str
    unread_count: int = 0  # unread conversations in the inbox
    last_synced_at: UTCDatetime | None
    sync_error: str | None
    needs_reauth: bool

    @classmethod
    def of(cls, account: MailAccount, unread_count: int = 0) -> "AccountOut":
        return cls(
            id=account.id,
            provider=account.provider,
            brand=account.brand,
            email=account.email,
            display_name=account.display_name,
            color=account.color,
            unread_count=unread_count,
            last_synced_at=account.last_synced_at,
            sync_error=account.sync_error,
            needs_reauth=account.needs_reauth,
        )


class ThreadOut(BaseModel):
    id: int
    account_id: int
    subject: str
    snippet: str
    participants: str
    message_count: int
    unread_count: int
    is_starred: bool
    is_archived: bool
    last_message_at: UTCDatetime
    attachment_count: int = 0
    category: str
    # Why the conversation looks like phishing; empty when it doesn't.
    suspicious_reasons: list[str] = []

    @classmethod
    def of(cls, thread: Thread) -> "ThreadOut":
        data = thread.model_dump(include=set(cls.model_fields) - {"suspicious_reasons", "category"})
        reasons = json.loads(thread.suspicious_reasons) if thread.suspicious_reasons else []
        return cls(**data, category=thread.category or "primary", suspicious_reasons=reasons)


class ThreadPage(BaseModel):
    threads: list[ThreadOut]
    # Pass back as `cursor` to get the next page; None on the last page.
    next_cursor: str | None


class AttachmentOut(BaseModel):
    id: int
    filename: str
    mime_type: str
    size: int
    inline: bool

    @classmethod
    def of(cls, attachment: Attachment) -> "AttachmentOut":
        return cls(**attachment.model_dump(include=set(cls.model_fields)))


class MessageOut(BaseModel):
    id: int
    from_name: str
    from_email: str
    to: str
    cc: str
    subject: str
    body_text: str
    body_html: str
    is_read: bool
    is_starred: bool
    is_sent: bool
    sent_at: UTCDatetime
    attachments: list[AttachmentOut] = []

    @classmethod
    def of(cls, message: Message, attachments: list[Attachment] = ()) -> "MessageOut":
        return cls(
            **message.model_dump(include=set(cls.model_fields) - {"attachments"}),
            attachments=[AttachmentOut.of(a) for a in attachments],
        )


class ThreadDetail(ThreadOut):
    messages: list[MessageOut]


class ThreadUpdate(BaseModel):
    """Fields left out are not changed."""

    is_read: bool | None = None
    is_starred: bool | None = None
    is_archived: bool | None = None


Folder = Literal["inbox", "unread", "starred", "sent", "archive", "all"]
Category = Literal["primary", "updates", "promotions", "newsletters"]


class BulkUpdate(BaseModel):
    thread_ids: list[int] = Field(min_length=1, max_length=500)
    change: ThreadUpdate


class BulkResult(BaseModel):
    updated: list[int] = []
    failed: list[int] = []


class SyncOut(BaseModel):
    account_id: int
    new_messages: int
    updated_messages: int
    deleted_messages: int
    error: str | None

    @classmethod
    def of(cls, result: SyncResult) -> "SyncOut":
        return cls(**result.__dict__)


# A pragmatic address check: one @, no spaces or separators. The provider is the real judge.
EMAIL_PATTERN = r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$"
Email = Annotated[str, Field(pattern=EMAIL_PATTERN, max_length=254)]
HOST_PATTERN = r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$"


class ImapConnect(BaseModel):
    email: Email
    display_name: str = Field(default="", max_length=80)
    username: str = Field(default="", max_length=254, description="Defaults to the email address")
    password: str = Field(min_length=1, max_length=256, description="Usually an app password")
    imap_host: str = Field(pattern=HOST_PATTERN, max_length=253)
    # TLS only: plain-text ports would send the password unencrypted.
    imap_port: Literal[993] = 993
    smtp_host: str = Field(pattern=HOST_PATTERN, max_length=253)
    smtp_port: Literal[465, 587] = 465


MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # in total, per message
_UNSAFE_NAME = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')


class AttachmentIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(default="application/octet-stream", max_length=127, pattern=r"^[\w.+-]+/[\w.+-]+$")
    data: str = Field(description="The file's content, base64-encoded")

    @field_validator("filename")
    @classmethod
    def plain_name(cls, value: str) -> str:
        # No folders, control characters or characters Windows forbids in file names.
        name = _UNSAFE_NAME.sub("_", value).strip(" .")
        return name or "attachment"

    def content(self) -> bytes:
        try:
            return base64.b64decode(self.data, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(f"{self.filename} isn't valid base64") from None


class SendIn(BaseModel):
    account_id: int
    to: list[Email] = Field(min_length=1, max_length=50)
    cc: list[Email] = Field(default_factory=list, max_length=50)
    subject: str = Field(default="", max_length=500)
    body: str = Field(max_length=100_000)
    # Reply within this conversation (threaded for every recipient's mail client).
    reply_to_thread_id: int | None = None
    attachments: list[AttachmentIn] = Field(default_factory=list, max_length=10)

    @field_validator("subject")
    @classmethod
    def one_line(cls, value: str) -> str:
        # Newlines in a header would let someone inject extra headers.
        return " ".join(value.split())


class ProvidersOut(BaseModel):
    gmail: bool
    outlook: bool
    imap: bool = True


class OAuthStartOut(BaseModel):
    url: str


class SummaryOut(BaseModel):
    summary: str
    action_items: list[str] = []
    source: Literal["gemini", "offline"]
    notice: str | None = None
    cached: bool = False


class DraftIn(BaseModel):
    instruction: str = Field(default="", max_length=300, description='Optional, e.g. "say yes politely"')


class DraftOut(BaseModel):
    draft: str
    source: Literal["gemini", "offline"]
    notice: str | None = None


class AIStatus(BaseModel):
    provider: Literal["gemini", "offline"]
    model: str | None
    requests_per_hour: int


class AccountUseOut(BaseModel):
    account_id: int
    email: str
    color: str
    first_seen: UTCDatetime
    last_seen: UTCDatetime
    signals: list[str]
    messages: int
    thread_id: int | None


class ServiceOut(BaseModel):
    name: str
    domain: str
    accounts: list[AccountUseOut]


class AccountFinderOut(BaseModel):
    services: list[ServiceOut]
    signal_labels: dict[str, str]


class SubscriptionOut(BaseModel):
    name: str
    domain: str
    count: int
    unread: int
    last_seen: UTCDatetime | None
    unsubscribe_url: str | None
    unsubscribe_mailto: str | None
    thread_ids: list[int]
    account_ids: list[int]
