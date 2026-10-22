"""Reading and writing RFC 5322 email with the standard library, shared by the adapters."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.headerregistry import Address as HeaderAddress
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, getaddresses, make_msgid, parsedate_to_datetime

from .base import Address, OutgoingMessage

# Bodies larger than this are cut, so one huge message can't bloat the database.
MAX_BODY_CHARS = 500_000


@dataclass
class ParsedMessage:
    sender: Address
    to: tuple[Address, ...]
    cc: tuple[Address, ...]
    subject: str
    body_text: str
    body_html: str
    sent_at: datetime
    message_id: str
    in_reply_to: str
    references: str
    list_unsubscribe: str = ""


def addresses(value: str | None) -> tuple[Address, ...]:
    return tuple(Address(email.strip(), name.strip()) for name, email in getaddresses([value or ""]) if email.strip())


def parse_date(value: str | None, fallback: datetime) -> datetime:
    try:
        parsed = parsedate_to_datetime(value) if value else None
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is None:
        return fallback
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _content(part) -> str:
    try:
        text = part.get_content()
    except (LookupError, ValueError, AssertionError):
        payload = part.get_payload(decode=True) or b""
        text = payload.decode("utf-8", errors="replace")
    return text[:MAX_BODY_CHARS] if isinstance(text, str) else ""


def parse_message(raw: bytes, fallback_date: datetime) -> ParsedMessage:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    text_part = msg.get_body(preferencelist=("plain",))
    html_part = msg.get_body(preferencelist=("html",))
    senders = addresses(str(msg.get("From", "")))
    return ParsedMessage(
        sender=senders[0] if senders else Address(""),
        to=addresses(str(msg.get("To", ""))),
        cc=addresses(str(msg.get("Cc", ""))),
        subject=str(msg.get("Subject", "")).strip(),
        body_text=_content(text_part) if text_part is not None else "",
        body_html=_content(html_part) if html_part is not None else "",
        sent_at=parse_date(msg.get("Date"), fallback_date),
        message_id=str(msg.get("Message-ID", "")).strip(),
        in_reply_to=str(msg.get("In-Reply-To", "")).strip(),
        references=" ".join(str(msg.get("References", "")).split()),
        list_unsubscribe=" ".join(str(msg.get("List-Unsubscribe", "")).split()),
    )


_MSGID = re.compile(r"<[^<>\s]+>")


def thread_key(message_id: str, in_reply_to: str, references: str) -> str:
    """Group a message with its conversation the way mail clients do without a provider thread id:
    the first entry in References is the message that started the thread."""
    for header in (references, in_reply_to, message_id):
        ids = _MSGID.findall(header or "")
        if ids:
            return ids[0]
    return message_id or ""


def build_message(out: OutgoingMessage, domain: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = _format(out.sender)
    msg["To"] = ", ".join(_format(a) for a in out.to)
    if out.cc:
        msg["Cc"] = ", ".join(_format(a) for a in out.cc)
    msg["Subject"] = out.subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=domain or out.sender.email.partition("@")[2] or None)
    if out.reply_to and out.reply_to.message_id_header:
        msg["In-Reply-To"] = out.reply_to.message_id_header
        msg["References"] = " ".join(f"{out.reply_to.references} {out.reply_to.message_id_header}".split())
    msg.set_content(out.body_text)
    return msg


def _format(address: Address) -> str:
    if not address.name:
        return address.email
    return str(HeaderAddress(display_name=address.name, addr_spec=address.email))


def reply_subject(subject: str) -> str:
    return subject if re.match(r"^\s*re:", subject, re.I) else f"Re: {subject}"
