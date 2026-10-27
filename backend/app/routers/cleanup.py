"""Clean-up: who fills the mailbox, and moving their mail to the Trash in bulk.

Messages go to the provider's Trash (recoverable there for about 30 days), never straight to
permanent deletion, and starred messages are always kept.
"""

from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import case, func
from sqlmodel import Session, select

from ..database import get_session
from ..models import MailAccount, Message, User, utcnow
from ..providers import AuthError, ProviderError, SyncBatch, get_provider
from ..schemas import CleanupOut, CleanupRequest, CleanupResult, CleanupSender
from ..security import get_current_user
from ..sync import apply_batch

router = APIRouter(prefix="/api/cleanup", tags=["cleanup"])

TOP_SENDERS = 200
# Messages per provider call; each chunk is committed, so a failure keeps earlier progress.
CHUNK = 200
MAX_MESSAGES = 5000


def _count(condition):
    return func.sum(case((condition, 1), else_=0))


@router.get("", response_model=CleanupOut)
def cleanup_overview(user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> CleanupOut:
    """Senders ranked by how much space their mail takes, with how much of it was ever opened."""
    accounts = select(MailAccount.id).where(MailAccount.user_id == user.id)
    mine = (Message.account_id.in_(accounts)) & (Message.is_sent == False)  # noqa: E712
    sender = func.lower(Message.from_email)
    rows = session.exec(
        select(
            Message.account_id,
            sender,
            func.max(Message.from_name),
            func.count(),
            _count(Message.is_read == True),  # noqa: E712
            _count(Message.is_starred == True),  # noqa: E712
            func.sum(Message.size),
            func.min(Message.sent_at),
            func.max(Message.sent_at),
            _count(Message.list_unsubscribe != ""),
        )
        .where(mine)
        .group_by(Message.account_id, sender)
        .order_by(func.sum(Message.size).desc(), func.count().desc())
        .limit(TOP_SENDERS)
    ).all()
    total_count, total_size = session.exec(select(func.count(), func.coalesce(func.sum(Message.size), 0)).where(mine)).one()
    return CleanupOut(
        total_count=total_count,
        total_size=total_size,
        senders=[
            CleanupSender(
                account_id=account_id,
                email=email,
                name=name or "",
                count=count,
                read=read or 0,
                starred=starred or 0,
                size=size or 0,
                first_seen=first,
                last_seen=last,
                can_unsubscribe=bool(unsubscribe),
            )
            for account_id, email, name, count, read, starred, size, first, last, unsubscribe in rows
        ],
    )


@router.post("/trash", response_model=CleanupResult)
def trash_senders(data: CleanupRequest, user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> CleanupResult:
    """Move every message from the chosen senders to the real mailbox's Trash, then remove the
    hub's copies. Starred messages are kept."""
    wanted: dict[int, set[str]] = defaultdict(set)
    for target in data.senders:
        wanted[target.account_id].add(target.email.lower())
    accounts = session.exec(select(MailAccount).where(MailAccount.user_id == user.id, MailAccount.id.in_(wanted))).all()

    result = CleanupResult(trashed=0)
    budget = MAX_MESSAGES
    for account in accounts:
        query = select(Message.remote_id).where(
            Message.account_id == account.id,
            func.lower(Message.from_email).in_(wanted[account.id]),
            Message.is_starred == False,  # noqa: E712
            Message.is_sent == False,  # noqa: E712
        )
        if data.older_than_days:
            query = query.where(Message.sent_at < utcnow() - timedelta(days=data.older_than_days))
        remote_ids = session.exec(query.order_by(Message.sent_at).limit(budget)).all()
        try:
            provider = get_provider(account)
            for start in range(0, len(remote_ids), CHUNK):
                chunk = remote_ids[start : start + CHUNK]
                # Copies only the hub has (mail sent over SMTP) have nothing to delete remotely.
                provider.trash([rid for rid in chunk if not rid.startswith("local:")])
                apply_batch(session, account, SyncBatch(deleted=chunk))
                session.commit()
                result.trashed += len(chunk)
                budget -= len(chunk)
        except AuthError as exc:
            session.rollback()
            account.needs_reauth = True
            account.sync_error = str(exc)[:500]
            session.add(account)
            session.commit()
            result.failed.append(account.email)
        except ProviderError:
            session.rollback()
            result.failed.append(account.email)
        if budget <= 0:
            break
    return result
