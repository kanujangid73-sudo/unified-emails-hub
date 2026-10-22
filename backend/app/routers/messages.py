from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..config import settings
from ..database import get_session
from ..models import Message, Thread, User
from ..providers import Address, AuthError, OutgoingAttachment, OutgoingMessage, ProviderError, ReplyContext, get_provider
from ..providers.mime import reply_subject
from ..ratelimit import SlidingWindowLimiter
from ..schemas import MAX_ATTACHMENT_BYTES, SendIn, ThreadOut
from ..security import get_current_user
from ..sync import store_message, sync_account
from .accounts import owned_account

router = APIRouter(prefix="/api/messages", tags=["messages"])
send_limiter = SlidingWindowLimiter(settings.sends_per_hour)


@router.post("", response_model=ThreadOut | None, status_code=status.HTTP_201_CREATED)
def send(data: SendIn, user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> ThreadOut | None:
    """Send a new email, or a reply when reply_to_thread_id is given.

    Returns the conversation the message landed in, or null if the provider hasn't reported
    it yet (it appears with the next sync).
    """
    account = owned_account(data.account_id, user, session)
    if account.needs_reauth:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Reconnect {account.email} before sending from it")

    reply = None
    subject = data.subject
    if data.reply_to_thread_id is not None:
        thread = session.get(Thread, data.reply_to_thread_id)
        if not thread or thread.user_id != user.id or thread.account_id != account.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found in that account")
        last = session.exec(select(Message).where(Message.thread_id == thread.id).order_by(Message.sent_at.desc(), Message.id.desc())).first()
        reply = ReplyContext(
            remote_id=last.remote_id,
            thread_remote_id=thread.remote_id,
            message_id_header=last.message_id_header,
            references=last.references_header,
        )
        subject = reply_subject(subject or thread.subject)
    if not subject:
        subject = "(no subject)"

    try:
        files = tuple(OutgoingAttachment(a.filename, a.mime_type, a.content()) for a in data.attachments)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if sum(len(f.data) for f in files) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(413, "Attachments can be at most 10 MB in total")

    if not send_limiter.hit(user.id):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "You've reached the hourly sending limit. Try again later.")

    outgoing = OutgoingMessage(
        sender=Address(account.email, account.display_name if account.provider != "demo" else ""),
        to=tuple(Address(e) for e in data.to),
        cc=tuple(Address(e) for e in data.cc),
        subject=subject,
        body_text=data.body,
        reply_to=reply,
        attachments=files,
    )
    try:
        stored = get_provider(account).send(outgoing)
    except AuthError as exc:
        account.needs_reauth = True
        account.sync_error = str(exc)[:500]
        session.add(account)
        session.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except ProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Not sent: {exc}") from None

    if stored is not None:
        return ThreadOut.of(store_message(session, account, stored))
    sync_account(session, account)  # Gmail and Outlook report the sent message on the next sync
    if reply:
        return ThreadOut.of(session.get(Thread, data.reply_to_thread_id))
    return None
