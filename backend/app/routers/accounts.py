from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlmodel import Session, delete, func, select

from ..database import get_session
from ..demo import add_sample_accounts
from ..models import MailAccount, Message, Thread, User
from ..providers import AuthError, ProviderError, get_provider
from ..providers.imap import ImapProvider
from ..schemas import AccountOut, ImapConnect, SyncOut
from ..security import get_current_user
from ..sync import sync_account
from .oauth import first_sync, require_real_user, save_account

router = APIRouter(prefix="/api", tags=["accounts"])


def _accounts(session: Session, user: User) -> list[AccountOut]:
    accounts = session.exec(select(MailAccount).where(MailAccount.user_id == user.id).order_by(MailAccount.id)).all()
    unread = dict(
        session.exec(
            select(Thread.account_id, func.count())
            .where(Thread.user_id == user.id, Thread.unread_count > 0, Thread.is_archived == False)  # noqa: E712
            .group_by(Thread.account_id)
        ).all()
    )
    return [AccountOut.of(a, unread.get(a.id, 0)) for a in accounts]


def owned_account(account_id: int, user: User, session: Session) -> MailAccount:
    account = session.get(MailAccount, account_id)
    if not account or account.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return account


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> list[AccountOut]:
    return _accounts(session, user)


@router.post("/accounts/demo", response_model=list[AccountOut], status_code=status.HTTP_201_CREATED)
def connect_sample_accounts(user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> list[AccountOut]:
    """Connect the three sample mailboxes, for trying the app before connecting real ones."""
    add_sample_accounts(session, user)
    return _accounts(session, user)


@router.post("/accounts/imap", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def connect_imap(
    data: ImapConnect,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> AccountOut:
    """Connect any mailbox over IMAP (reading) and SMTP (sending). The password is stored encrypted."""
    require_real_user(user)
    credentials = {
        "username": data.username or data.email,
        "password": data.password,
        "imap_host": data.imap_host.lower(),
        "imap_port": data.imap_port,
        "smtp_host": data.smtp_host.lower(),
        "smtp_port": data.smtp_port,
    }
    try:
        ImapProvider(credentials, data.email).verify()
    except AuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    except ProviderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Couldn't connect: {exc}") from None
    account = save_account(session, user.id, "imap", data.email.lower(), data.display_name, credentials)
    background.add_task(first_sync, account.id)
    return AccountOut.of(account)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_account(account_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> None:
    """Remove an account and everything the hub stored for it. The real mailbox is untouched;
    for Gmail, the hub's access is also revoked at Google."""
    account = owned_account(account_id, user, session)
    try:
        get_provider(account).disconnect()
    except ProviderError:
        pass  # credentials already invalid: nothing to revoke
    session.exec(delete(Message).where(Message.account_id == account.id))
    session.exec(delete(Thread).where(Thread.account_id == account.id))
    session.delete(account)
    session.commit()


@router.post("/sync", response_model=list[SyncOut])
def sync_all(user: User = Depends(get_current_user), session: Session = Depends(get_session)) -> list[SyncOut]:
    """Fetch new mail for every connected account now. Only changes since the last sync are
    transferred. Accounts that need reconnecting are skipped."""
    accounts = session.exec(
        select(MailAccount).where(MailAccount.user_id == user.id, MailAccount.needs_reauth == False).order_by(MailAccount.id)  # noqa: E712
    ).all()
    return [SyncOut.of(sync_account(session, account)) for account in accounts]
