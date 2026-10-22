"""Search with Gmail-style operators.

    invoice from:zestro is:unread after:2026-09-01

Words must all appear in one message of the conversation (subject, sender or body). On
Postgres this uses the full-text index (migration 0002) with prefix matching, so "invo"
finds "invoice". SQLite, used in development, falls back to substring matching.

Operators: from:  to:  is:unread  is:read  is:starred  has:attachment  before:YYYY-MM-DD  after:YYYY-MM-DD
"""

import re
import shlex
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone

from sqlalchemy import and_, exists, false, func, literal_column, or_

from .models import Message, Thread


@dataclass
class ParsedQuery:
    words: list[str] = field(default_factory=list)
    senders: list[str] = field(default_factory=list)
    recipients: list[str] = field(default_factory=list)
    unread: bool | None = None
    starred: bool | None = None
    has_attachment: bool = False
    after: datetime | None = None
    before: datetime | None = None


def _day(value: str) -> datetime | None:
    try:
        return datetime.combine(date.fromisoformat(value.replace("/", "-")), time(), tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_query(q: str) -> ParsedQuery:
    try:
        tokens = shlex.split(q)
    except ValueError:  # an unclosed quote
        tokens = q.replace('"', " ").split()
    parsed = ParsedQuery()
    for token in tokens:
        key, sep, value = token.partition(":")
        key = key.lower()
        if sep and value and key in {"from", "to", "is", "has", "before", "after"}:
            value_l = value.lower()
            if key == "from":
                parsed.senders.append(value)
            elif key == "to":
                parsed.recipients.append(value)
            elif key == "is" and value_l in {"unread", "read"}:
                parsed.unread = value_l == "unread"
            elif key == "is" and value_l == "starred":
                parsed.starred = True
            elif key == "has" and value_l in {"attachment", "attachments", "file"}:
                parsed.has_attachment = True
            elif key in {"before", "after"} and (day := _day(value)):
                if key == "after":
                    parsed.after = day
                else:
                    parsed.before = day
            else:
                parsed.words.append(token)
        else:
            parsed.words.append(token)
    return parsed


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _ilike(column, term: str):
    return column.ilike(_like(term), escape="\\")


# Whitespace and ASCII punctuation separate words. Every tsquery operator (& | ! ( ) : * ' <->)
# is ASCII punctuation, so none can reach to_tsquery. Letters and combining marks of any script
# survive, which \w alone would break apart (e.g. the vowel signs in Hindi).
_SEPARATORS = re.compile(r"[\s!-/:-@\[-`{-~]+")


def tsquery(words: list[str]) -> str | None:
    """'roadmap Q4' -> 'roadmap:* & q4:*'. Returns None when no searchable word is left."""
    pieces = [p.lower() for w in words for p in _SEPARATORS.split(w) if p]
    return " & ".join(f"{p}:*" for p in pieces) or None


def filter_threads(query, q: str, dialect: str):
    parsed = parse_query(q)
    in_thread = [Message.thread_id == Thread.id]

    if parsed.words:
        if dialect == "postgresql":
            ts = tsquery(parsed.words)
            # Nothing searchable (e.g. only punctuation): no message can match.
            condition = literal_column("message.search_vector").op("@@")(func.to_tsquery(literal_column("'simple'::regconfig"), ts)) if ts else false()
            query = query.where(exists().where(*in_thread, condition))
        else:
            for word in parsed.words:
                in_message = exists().where(
                    *in_thread,
                    or_(_ilike(Message.body_text, word), _ilike(Message.from_email, word), _ilike(Message.from_name, word), _ilike(Message.subject, word)),
                )
                query = query.where(or_(_ilike(Thread.subject, word), _ilike(Thread.participants, word), in_message))
    for sender in parsed.senders:
        query = query.where(exists().where(*in_thread, or_(_ilike(Message.from_email, sender), _ilike(Message.from_name, sender))))
    for recipient in parsed.recipients:
        query = query.where(exists().where(*in_thread, or_(_ilike(Message.to, recipient), _ilike(Message.cc, recipient))))
    if parsed.unread is not None:
        query = query.where(Thread.unread_count > 0 if parsed.unread else Thread.unread_count == 0)
    if parsed.starred:
        query = query.where(Thread.is_starred == True)  # noqa: E712
    if parsed.has_attachment:
        query = query.where(Thread.attachment_count > 0)
    if parsed.after:
        query = query.where(Thread.last_message_at >= parsed.after)
    if parsed.before:
        # Conversations with a message before that day.
        query = query.where(exists().where(*in_thread, Message.sent_at < parsed.before))
    return query


def sent_condition():
    return exists().where(and_(Message.thread_id == Thread.id, Message.is_sent == True))  # noqa: E712

