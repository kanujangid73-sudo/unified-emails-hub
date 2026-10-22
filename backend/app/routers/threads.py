import base64
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_
from sqlmodel import Session, select

from .. import ai
from ..config import settings
from ..database import get_session
from ..demo_data import OWNER_NAME
from ..models import Attachment, MailAccount, Message, Thread, User
from ..providers import AuthError, FlagChange, ProviderError, get_provider
from ..ratelimit import SlidingWindowLimiter
from ..schemas import (
    BulkResult,
    BulkUpdate,
    Category,
    DraftIn,
    DraftOut,
    Folder,
    MessageOut,
    SummaryOut,
    ThreadDetail,
    ThreadOut,
    ThreadPage,
    ThreadUpdate,
)
from ..search import filter_threads, sent_condition
from ..security import get_current_user
from ..sync import as_utc, refresh_threads

router = APIRouter(prefix="/api/threads", tags=["threads"])
ai_limiter = SlidingWindowLimiter(settings.ai_requests_per_hour)


# Keyset pagination: the cursor is the (date, id) of the last thread on the previous page, so
# pages stay correct while new mail arrives, and deep pages cost the same as the first one.
def encode_cursor(thread: Thread) -> str:
    raw = f"{as_utc(thread.last_message_at).isoformat()}|{thread.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        when, thread_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(when), int(thread_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor") from None


@router.get("", response_model=ThreadPage)
def list_threads(
    folder: Folder = "inbox",
    account_id: int | None = None,
    category: Category | None = None,
    q: str = Query(default="", max_length=300, description="Words and operators: from: to: is:unread is:starred before: after:"),
    cursor: str | None = None,
    limit: int = Query(default=settings.page_size, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ThreadPage:
    """The unified inbox: conversations from all accounts (or one), newest first."""
    query = select(Thread).where(Thread.user_id == user.id)
    if account_id is not None:
        query = query.where(Thread.account_id == account_id)
    if category is not None:
        query = query.where(Thread.category == category)
    if folder == "inbox":
        query = query.where(Thread.is_archived == False)  # noqa: E712
    elif folder == "unread":
        query = query.where(Thread.is_archived == False, Thread.unread_count > 0)  # noqa: E712
    elif folder == "starred":
        query = query.where(Thread.is_starred == True)  # noqa: E712
    elif folder == "archive":
        query = query.where(Thread.is_archived == True)  # noqa: E712
    elif folder == "sent":
        query = query.where(sent_condition())
    if q.strip():
        query = filter_threads(query, q, session.get_bind().dialect.name)
    if cursor:
        when, last_id = decode_cursor(cursor)
        query = query.where(
            or_(Thread.last_message_at < when, and_(Thread.last_message_at == when, Thread.id < last_id))
        )
    rows = session.exec(query.order_by(Thread.last_message_at.desc(), Thread.id.desc()).limit(limit + 1)).all()
    page = rows[:limit]
    return ThreadPage(
        threads=[ThreadOut.of(t) for t in page],
        next_cursor=encode_cursor(page[-1]) if len(rows) > limit else None,
    )


def _owned_thread(thread_id: int, user: User, session: Session) -> Thread:
    thread = session.get(Thread, thread_id)
    if not thread or thread.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return thread


def _messages(thread: Thread, session: Session) -> list[Message]:
    return list(session.exec(select(Message).where(Message.thread_id == thread.id).order_by(Message.sent_at, Message.id)).all())


@router.get("/{thread_id}", response_model=ThreadDetail)
def get_thread(thread_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> ThreadDetail:
    thread = _owned_thread(thread_id, user, session)
    messages = _messages(thread, session)
    files: dict[int, list[Attachment]] = {}
    for a in session.exec(select(Attachment).where(Attachment.message_id.in_([m.id for m in messages])).order_by(Attachment.id)):
        files.setdefault(a.message_id, []).append(a)
    return ThreadDetail(**ThreadOut.of(thread).model_dump(), messages=[MessageOut.of(m, files.get(m.id, [])) for m in messages])


def change_thread(session: Session, thread: Thread, change: FlagChange) -> None:
    """Apply a change to the real mailbox first, then to the hub's copy.

    The hub never shows a state the provider doesn't have: if the provider refuses, this raises
    ProviderError (or AuthError, after flagging the account for reconnecting) and nothing changes.
    """
    account = session.get(MailAccount, thread.account_id)
    messages = _messages(thread, session)
    if change == FlagChange() or not messages:
        return
    # Your own sent copies stay as they are (in Outlook they live in Sent Items, not the inbox).
    received = [m.remote_id for m in messages if not m.is_sent] or [m.remote_id for m in messages]
    try:
        provider = get_provider(account)
        if change.is_read is not None or change.is_archived is not None:
            provider.update_flags(thread.remote_id, received, FlagChange(is_read=change.is_read, is_archived=change.is_archived))
        if change.is_starred is not None:
            # Starring flags the latest message; unstarring clears every flag in the conversation.
            starred = [messages[-1].remote_id] if change.is_starred else [m.remote_id for m in messages]
            provider.update_flags(thread.remote_id, starred, FlagChange(is_starred=change.is_starred))
    except AuthError as exc:
        account.needs_reauth = True
        account.sync_error = str(exc)[:500]
        session.add(account)
        session.commit()
        raise

    if change.is_read is not None:
        for m in messages:
            m.is_read = change.is_read
    if change.is_starred is not None:
        for m in messages:
            m.is_starred = change.is_starred and m is messages[-1]
    if change.is_archived is not None:
        thread.is_archived = change.is_archived
    session.add_all([thread, *messages])
    session.flush()
    refresh_threads(session, {thread.id}, account.email)
    session.commit()


@router.patch("/{thread_id}", response_model=ThreadOut)
def update_thread(
    thread_id: int,
    data: ThreadUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ThreadOut:
    """Mark read or unread, star or unstar, archive or move back to the inbox."""
    thread = _owned_thread(thread_id, user, session)
    try:
        change_thread(session, thread, FlagChange(**data.model_dump()))
    except AuthError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except ProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
    session.refresh(thread)
    return ThreadOut.of(thread)


@router.post("/bulk", response_model=BulkResult)
def bulk_update(data: BulkUpdate, user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> BulkResult:
    """Apply one change to many conversations, e.g. archive everything from a newsletter.

    Each conversation succeeds or fails on its own; failures are reported, not fatal.
    """
    change = FlagChange(**data.change.model_dump())
    result = BulkResult()
    for thread_id in dict.fromkeys(data.thread_ids):
        thread = session.get(Thread, thread_id)
        if not thread or thread.user_id != user.id:
            result.failed.append(thread_id)
            continue
        try:
            change_thread(session, thread, change)
            result.updated.append(thread_id)
        except ProviderError:
            session.rollback()
            result.failed.append(thread_id)
    return result


# ------------------------------------------------------------------ AI, on request only


def _owner_name(account: MailAccount) -> str:
    return OWNER_NAME if account.provider == "demo" else (account.display_name if " " in account.display_name else "")


def _check_ai_quota(user: User) -> None:
    if not ai_limiter.hit(user.id):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "You've used your AI requests for this hour. Try again later.")


@router.post("/{thread_id}/summary", response_model=SummaryOut)
def summarize(
    thread_id: int,
    refresh: bool = False,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> SummaryOut:
    """A short summary and to-do list for the conversation. Cached until a new message arrives."""
    thread = _owned_thread(thread_id, user, session)
    if not refresh and thread.summary and thread.summary_for == thread.message_count:
        cached = json.loads(thread.summary)
        # A built-in summary is redone once Gemini is available; Gemini ones are kept.
        if cached["source"] == ai.provider() or cached["source"] == "gemini":
            return SummaryOut(**cached, cached=True)
    _check_ai_quota(user)
    account = session.get(MailAccount, thread.account_id)
    result = ai.summarize(_messages(thread, session), account.email, _owner_name(account))
    out = SummaryOut(summary=result.summary, action_items=result.action_items, source=result.source, notice=result.notice)
    if result.notice is None:  # don't cache a fallback caused by a temporary failure
        thread.summary = json.dumps({"summary": out.summary, "action_items": out.action_items, "source": out.source})
        thread.summary_for = thread.message_count
        session.add(thread)
        session.commit()
    return out


@router.post("/{thread_id}/draft", response_model=DraftOut)
def draft(thread_id: int, data: DraftIn, user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> DraftOut:
    """A reply draft for the user to edit. It is never sent automatically."""
    thread = _owned_thread(thread_id, user, session)
    _check_ai_quota(user)
    account = session.get(MailAccount, thread.account_id)
    result = ai.draft_reply(_messages(thread, session), account.email, _owner_name(account), data.instruction)
    return DraftOut(draft=result.draft, source=result.source, notice=result.notice)
