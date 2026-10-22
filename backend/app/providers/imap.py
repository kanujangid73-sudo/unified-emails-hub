"""IMAP + SMTP adapter, for Yahoo, Zoho, iCloud, Fastmail, company servers and any other mailbox.

Sync follows the INBOX by UID. UIDs only grow, so "what's new" is everything above the
highest UID already seen. If the server's UIDVALIDITY changes, its old UIDs mean nothing any
more and the mailbox is synced afresh. Read and starred flags of recent messages are
re-read on each sync, so changes made on a phone show up here.

IMAP has no standard archive, so archiving stays in the hub (RemoteMessage.is_archived None).
Messages are fetched with BODY.PEEK so syncing never marks them as read.
"""

import imaplib
import json
import re
import smtplib
import ssl
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from ..net import UnsafeHostError, check_public_host
from .base import (
    AuthError,
    FlagChange,
    MailProvider,
    OutgoingMessage,
    ProviderError,
    RemoteAttachment,
    RemoteFlags,
    RemoteMessage,
    SyncBatch,
)
from .mime import attachment_bytes, build_message, parse_message, thread_key

TIMEOUT = 30
# Messages bigger than this (usually because of attachments) get their headers only.
MAX_MESSAGE_BYTES = 2_000_000
# How many recent messages have their flags re-read on each sync.
FLAG_WINDOW = 300

_UID = re.compile(rb"UID (\d+)")
_FLAGS = re.compile(rb"FLAGS \(([^)]*)\)")
_SIZE = re.compile(rb"RFC822\.SIZE (\d+)")


def connect_imap(credentials: dict) -> imaplib.IMAP4:
    host, port = credentials["imap_host"], int(credentials.get("imap_port", 993))
    try:
        check_public_host(host, port)
        conn = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT)
    except UnsafeHostError as exc:
        raise ProviderError(str(exc)) from exc
    except (OSError, imaplib.IMAP4.error) as exc:
        raise ProviderError(f"Couldn't connect to {host}:{port} ({exc})", retryable=True) from exc
    try:
        conn.login(credentials["username"], credentials["password"])
    except imaplib.IMAP4.error as exc:
        raise AuthError("The mail server rejected the username or password. Many providers need an app password.") from exc
    return conn


def connect_smtp(credentials: dict) -> smtplib.SMTP:
    host, port = credentials["smtp_host"], int(credentials.get("smtp_port", 465))
    try:
        check_public_host(host, port)
        context = ssl.create_default_context()
        if port == 465:
            conn = smtplib.SMTP_SSL(host, port, context=context, timeout=TIMEOUT)
        else:
            conn = smtplib.SMTP(host, port, timeout=TIMEOUT)
            conn.starttls(context=context)
        conn.login(credentials["username"], credentials["password"])
        return conn
    except UnsafeHostError as exc:
        raise ProviderError(str(exc)) from exc
    except smtplib.SMTPAuthenticationError as exc:
        raise AuthError("The outgoing mail server rejected the username or password.") from exc
    except (OSError, smtplib.SMTPException) as exc:
        raise ProviderError(f"Couldn't send through {host}:{port} ({exc})", retryable=True) from exc


def _check(result: tuple, what: str) -> list:
    status, data = result
    if status != "OK":
        raise ProviderError(f"IMAP {what} failed: {data!r}", retryable=True)
    return data


def _flag_set(raw: bytes) -> set[str]:
    match = _FLAGS.search(raw)
    return set(match.group(1).decode().split()) if match else set()


class ImapProvider(MailProvider):
    page_size = 50

    def __init__(
        self,
        credentials: dict,
        account_email: str,
        backfill_days: int = 30,
        connect: Callable[[dict], imaplib.IMAP4] | None = None,
        smtp: Callable[[dict], smtplib.SMTP] | None = None,
        now=None,
    ) -> None:
        self.credentials = credentials
        self.account_email = account_email
        self.backfill_days = backfill_days
        self._connect = connect or connect_imap
        self._connect_smtp = smtp or connect_smtp
        self._now = now or (lambda: datetime.now(timezone.utc))

    @contextmanager
    def _inbox(self, readonly: bool = True) -> Iterator[tuple[imaplib.IMAP4, str]]:
        conn = self._connect(self.credentials)
        try:
            _check(conn.select("INBOX", readonly=readonly), "SELECT")
            validity = conn.response("UIDVALIDITY")[1][0] or b"0"
            yield conn, validity.decode() if isinstance(validity, bytes) else str(validity)
        except (OSError, imaplib.IMAP4.error) as exc:
            raise ProviderError(f"Lost the connection to the mail server ({exc})", retryable=True) from exc
        finally:
            try:
                conn.logout()
            except (OSError, imaplib.IMAP4.error):
                pass

    def verify(self) -> None:
        """Check the credentials work, for the connect form."""
        with self._inbox():
            pass

    def fetch_changes(self, cursor: str | None) -> SyncBatch:
        state = json.loads(cursor) if cursor else {}
        with self._inbox() as (conn, validity):
            if state and state.get("v") != validity:
                return SyncBatch(reset=True, cursor=None, has_more=True)
            last = int(state.get("last", 0))
            if state:
                found = _check(conn.uid("SEARCH", None, f"UID {last + 1}:*"), "SEARCH")
            else:
                since = (self._now() - timedelta(days=self.backfill_days)).strftime("%d-%b-%Y")
                found = _check(conn.uid("SEARCH", None, f"SINCE {since}"), "SEARCH")
            # "UID n:*" always includes the highest UID, even when it's below n.
            uids = sorted(u for u in (int(x) for x in b" ".join(found).split()) if u > last)
            page = uids[: self.page_size]

            batch = SyncBatch(messages=self._fetch(conn, validity, page) if page else [])
            batch.has_more = len(uids) > len(page)
            newest = max(page, default=last)
            if not batch.has_more and last:
                batch.flags = self._recent_flags(conn, validity, last)
            batch.cursor = json.dumps({"v": validity, "last": newest})
            return batch

    def _fetch(self, conn: imaplib.IMAP4, validity: str, uids: list[int]) -> list[RemoteMessage]:
        id_list = ",".join(map(str, uids))
        sizes = {}
        for item in _check(conn.uid("FETCH", id_list, "(UID RFC822.SIZE)"), "FETCH"):
            raw = item[0] if isinstance(item, tuple) else item
            if isinstance(raw, bytes) and (uid := _UID.search(raw)) and (size := _SIZE.search(raw)):
                sizes[int(uid.group(1))] = int(size.group(1))
        small = [u for u in uids if sizes.get(u, 0) <= MAX_MESSAGE_BYTES]
        large = [u for u in uids if u not in small]

        messages = []
        for wanted, part in ((small, "BODY.PEEK[]"), (large, "BODY.PEEK[HEADER]")):
            if not wanted:
                continue
            data = _check(conn.uid("FETCH", ",".join(map(str, wanted)), f"(UID FLAGS {part})"), "FETCH")
            for item in data:
                if not isinstance(item, tuple):
                    continue
                meta, raw = item
                uid = _UID.search(meta)
                if uid:
                    messages.append(self._convert(validity, int(uid.group(1)), _flag_set(meta), raw, truncated=part.endswith("[HEADER]")))
        return messages

    def _convert(self, validity: str, uid: int, flags: set[str], raw: bytes, truncated: bool) -> RemoteMessage:
        parsed = parse_message(raw, self._now())
        text = parsed.body_text
        if truncated:
            text = "This message is too large to preview here (it probably has big attachments). Open it in your mail app to see them."
        return RemoteMessage(
            remote_id=f"{validity}:{uid}",
            thread_id=thread_key(parsed.message_id, parsed.in_reply_to, parsed.references) or f"{validity}:{uid}",
            sender=parsed.sender,
            to=parsed.to,
            cc=parsed.cc,
            subject=parsed.subject,
            sent_at=parsed.sent_at,
            body_text=text,
            body_html="" if truncated else parsed.body_html,
            is_read="\\Seen" in flags,
            is_starred="\\Flagged" in flags,
            message_id_header=parsed.message_id,
            references=parsed.references,
            list_unsubscribe=parsed.list_unsubscribe,
            attachments=() if truncated else parsed.attachments,
        )

    def fetch_attachment(self, message_remote_id: str, ref: str) -> bytes:
        validity, _, uid = message_remote_id.partition(":")
        with self._inbox() as (conn, current):
            if validity != current:
                raise ProviderError("The mailbox was reorganised since this message was synced; sync again")
            for item in _check(conn.uid("FETCH", uid, "(UID BODY.PEEK[])"), "FETCH"):
                if isinstance(item, tuple):
                    content = attachment_bytes(item[1], ref)
                    if content is not None:
                        return content
        raise ProviderError("That attachment no longer exists on the mail server")

    def _recent_flags(self, conn: imaplib.IMAP4, validity: str, last: int) -> list[RemoteFlags]:
        low = max(1, last - FLAG_WINDOW)
        result = []
        for item in _check(conn.uid("FETCH", f"{low}:{last}", "(UID FLAGS)"), "FETCH"):
            raw = item[0] if isinstance(item, tuple) else item
            if isinstance(raw, bytes) and (uid := _UID.search(raw)):
                flags = _flag_set(raw)
                result.append(RemoteFlags(remote_id=f"{validity}:{int(uid.group(1))}", is_read="\\Seen" in flags, is_starred="\\Flagged" in flags))
        return result

    def update_flags(self, thread_remote_id: str, message_remote_ids: list[str], change: FlagChange) -> None:
        if change.is_read is None and change.is_starred is None:
            return  # archive is kept in the hub only
        with self._inbox(readonly=False) as (conn, validity):
            uids = [rid.split(":", 1)[1] for rid in message_remote_ids if rid.startswith(f"{validity}:")]
            if not uids:
                return
            id_list = ",".join(uids)
            for value, flag in ((change.is_read, "\\Seen"), (change.is_starred, "\\Flagged")):
                if value is not None:
                    _check(conn.uid("STORE", id_list, "+FLAGS" if value else "-FLAGS", f"({flag})"), "STORE")

    def send(self, message: OutgoingMessage) -> RemoteMessage:
        mime = build_message(message)
        smtp = self._connect_smtp(self.credentials)
        try:
            smtp.send_message(mime)
        except smtplib.SMTPException as exc:
            raise ProviderError(f"The mail server refused the message: {exc}") from exc
        finally:
            try:
                smtp.quit()
            except (OSError, smtplib.SMTPException):
                pass
        # The sync only follows INBOX, so keep a copy of the sent message in the hub directly.
        message_id = mime["Message-ID"]
        reply = message.reply_to
        return RemoteMessage(
            remote_id=f"local:{uuid.uuid4().hex}",
            thread_id=reply.thread_remote_id if reply else thread_key(message_id, "", ""),
            sender=message.sender,
            to=message.to,
            cc=message.cc,
            subject=message.subject,
            sent_at=self._now(),
            body_text=message.body_text,
            is_read=True,
            message_id_header=message_id,
            references=mime.get("References", ""),
            # The hub keeps the only copy, so it keeps the files too.
            attachments=tuple(
                RemoteAttachment(filename=a.filename, mime_type=a.mime_type, size=len(a.data), ref=str(i), data=a.data)
                for i, a in enumerate(message.attachments)
            ),
        )
