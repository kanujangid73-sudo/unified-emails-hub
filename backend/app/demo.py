"""One-click demo accounts.

A visitor gets a temporary guest user with three sample mailboxes (personal Gmail, work
Outlook, old IMAP), synced through the same engine real accounts use. Guests and everything
they own are deleted after settings.guest_ttl_hours.
"""

import logging
import secrets
from datetime import timedelta

from sqlmodel import Session, delete, select

from .config import settings
from .demo_data import DEMO_ACCOUNTS
from .models import MailAccount, User, utcnow
from .security import hash_password
from .sync import delete_account_mail, sync_account

logger = logging.getLogger("mailhub.demo")


def _guest_name(session: Session) -> str:
    while True:
        name = f"guest_{secrets.token_hex(3)}"
        if not session.exec(select(User).where(User.username == name)).first():
            return name


def add_sample_accounts(session: Session, user: User) -> list[MailAccount]:
    """Connect the three sample mailboxes to a user (skipping any already connected) and sync them."""
    connected = {a.email for a in session.exec(select(MailAccount).where(MailAccount.user_id == user.id))}
    accounts = [
        MailAccount(user_id=user.id, provider="demo", brand=brand, email=email, display_name=name, color=color)
        for brand, email, name, color in DEMO_ACCOUNTS
        if email not in connected
    ]
    session.add_all(accounts)
    session.commit()
    for account in accounts:
        session.refresh(account)
        sync_account(session, account)
    return accounts


def create_guest(session: Session) -> User:
    # Nobody knows this password, so the account can only be used through the issued token.
    user = User(username=_guest_name(session), password_hash=hash_password(secrets.token_urlsafe(32)), is_guest=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    add_sample_accounts(session, user)
    return user


def delete_users(session: Session, user_ids: list[int]) -> None:
    account_ids = list(session.exec(select(MailAccount.id).where(MailAccount.user_id.in_(user_ids))))
    if account_ids:
        delete_account_mail(session, account_ids)
        session.exec(delete(MailAccount).where(MailAccount.id.in_(account_ids)))
    session.exec(delete(User).where(User.id.in_(user_ids)))
    session.commit()


def purge_expired_guests(session: Session) -> int:
    """Delete guests older than the TTL, with their accounts and mail."""
    cutoff = utcnow() - timedelta(hours=settings.guest_ttl_hours)
    guest_ids = list(session.exec(select(User.id).where(User.is_guest == True, User.created_at < cutoff)))  # noqa: E712
    if guest_ids:
        delete_users(session, guest_ids)
        logger.info("Removed %d expired guest accounts", len(guest_ids))
    return len(guest_ids)
