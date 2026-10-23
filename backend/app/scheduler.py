"""Background sync: keeps every connected account up to date while nobody has the app open.

Every few seconds the scheduler looks for accounts whose next_sync_at has passed and syncs
them. Before syncing, it *claims* an account by moving next_sync_at forward in a conditional
UPDATE; only one claimer can win that update, so when several server processes run the
scheduler, an account is still synced by just one of them at a time. If a process dies
mid-sync, the claim (a lease) simply expires and another process picks the account up.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import or_, update
from sqlmodel import Session, select

from . import database
from .demo import purge_expired_guests
from .models import MailAccount, utcnow
from .sync import sync_account

logger = logging.getLogger("mailhub.scheduler")

TICK_SECONDS = 30
# How often expired demo accounts are deleted, so a busy demo can't fill the free database.
CLEANUP_EVERY = timedelta(hours=1)
LEASE = timedelta(minutes=10)
BATCH = 20


def _due(now: datetime):
    return (MailAccount.needs_reauth == False) & or_(MailAccount.next_sync_at == None, MailAccount.next_sync_at <= now)  # noqa: E711, E712


def claim(session: Session, account_id: int, now: datetime) -> bool:
    result = session.exec(
        update(MailAccount)
        .where(MailAccount.id == account_id, _due(now))
        .values(next_sync_at=now + LEASE)
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return result.rowcount == 1


def sync_due_accounts(now: datetime | None = None, limit: int = BATCH) -> int:
    """Sync the accounts that are due. Returns how many were synced."""
    now = now or utcnow()
    with Session(database.engine) as session:
        due = session.exec(
            select(MailAccount.id).where(_due(now)).order_by(MailAccount.next_sync_at.nulls_first()).limit(limit)
        ).all()
    synced = 0
    for account_id in due:
        with Session(database.engine) as session:
            if not claim(session, account_id, now):
                continue  # another process got it first
            account = session.get(MailAccount, account_id)
            sync_account(session, account)  # sets the real next_sync_at, replacing the lease
            synced += 1
    return synced


def cleanup() -> int:
    with Session(database.engine) as session:
        return purge_expired_guests(session)


async def run(stop: asyncio.Event) -> None:
    logger.info("Background sync started")
    last_cleanup = None
    while not stop.is_set():
        try:
            if last_cleanup is None or utcnow() - last_cleanup >= CLEANUP_EVERY:
                await asyncio.to_thread(cleanup)
                last_cleanup = utcnow()
            count = await asyncio.to_thread(sync_due_accounts)
            if count:
                logger.info("Background sync: %d account(s) synced", count)
        except Exception:  # noqa: BLE001  (keep the loop alive; the next tick tries again)
            logger.exception("Background sync tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
        except TimeoutError:
            pass
