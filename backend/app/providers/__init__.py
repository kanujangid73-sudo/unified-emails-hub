"""Provider adapters. get_provider() builds the right one for a connected account."""

from sqlmodel import Session, update

from .. import database
from ..config import settings
from ..crypto import CryptoError, decrypt_json, encrypt_json
from ..models import MailAccount
from . import oauth
from .base import (
    Address,
    AuthError,
    FlagChange,
    MailProvider,
    OutgoingAttachment,
    OutgoingMessage,
    ProviderError,
    RemoteAttachment,
    RemoteFlags,
    RemoteMessage,
    ReplyContext,
    SyncBatch,
)
from .demo import DemoProvider
from .gmail import GmailProvider
from .imap import ImapProvider
from .outlook import OutlookProvider

__all__ = [
    "Address",
    "AuthError",
    "FlagChange",
    "MailProvider",
    "OutgoingAttachment",
    "OutgoingMessage",
    "ProviderError",
    "RemoteAttachment",
    "RemoteFlags",
    "RemoteMessage",
    "ReplyContext",
    "SyncBatch",
    "get_provider",
    "oauth_provider",
]


def credentials_of(account: MailAccount) -> dict:
    if not account.credentials:
        raise AuthError("This account has no saved sign-in. Reconnect it.")
    try:
        return decrypt_json(account.credentials)
    except CryptoError as exc:
        raise AuthError("The saved sign-in can't be read (the encryption key changed). Reconnect the account.") from exc


def _saver(account: MailAccount):
    """Persist refreshed OAuth tokens at once, in their own transaction.

    Microsoft rotates refresh tokens, so a new one must not be lost even if the request that
    triggered the refresh fails afterwards and its transaction is rolled back.
    """

    def save(credentials: dict) -> None:
        sealed = encrypt_json(credentials)
        account.credentials = sealed
        with Session(database.engine) as session:
            session.exec(update(MailAccount).where(MailAccount.id == account.id).values(credentials=sealed))
            session.commit()

    return save


def oauth_provider(provider: str, credentials: dict, on_refresh=lambda _: None) -> GmailProvider | OutlookProvider:
    app = oauth.oauth_app(provider)
    if app is None:
        raise ProviderError(f"Signing in with {provider} isn't configured on this server")
    session = oauth.OAuthSession(app, credentials, oauth.make_http(), on_refresh)
    cls = GmailProvider if provider == "gmail" else OutlookProvider
    return cls(session, backfill_days=settings.sync_backfill_days)


def get_provider(account: MailAccount) -> MailProvider:
    if account.provider == "demo":
        return DemoProvider(account.brand, account.email, account.created_at)
    if account.provider in ("gmail", "outlook"):
        return oauth_provider(account.provider, credentials_of(account), _saver(account))
    if account.provider == "imap":
        return ImapProvider(credentials_of(account), account.email, backfill_days=settings.sync_backfill_days)
    raise ProviderError(f"Unknown provider {account.provider!r}")
