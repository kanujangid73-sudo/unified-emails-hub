"""Connecting Gmail and Outlook accounts with OAuth.

1. The app calls POST /api/oauth/{provider}/start and sends the browser to the returned URL.
2. The user signs in with Google or Microsoft and approves access.
3. The provider redirects to GET /api/oauth/{provider}/callback with a one-time code.
4. The server exchanges the code for tokens, stores them encrypted, and sends the browser
   back to the app, which shows the new account while its first sync runs in the background.

The `state` parameter is an encrypted, time-limited token carrying the user id and the PKCE
verifier, so a callback can't be forged or replayed for another user, and no server-side
session is needed.
"""

import logging
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from .. import database
from ..config import settings
from ..crypto import CryptoError, decrypt_json, encrypt_json
from ..database import get_session
from ..models import MailAccount, User, utcnow
from ..providers import ProviderError, oauth, oauth_provider
from ..schemas import OAuthStartOut, ProvidersOut
from ..security import get_current_user
from ..sync import sync_account

logger = logging.getLogger("mailhub.oauth")
router = APIRouter(prefix="/api/oauth", tags=["connect accounts"])

STATE_TTL_SECONDS = 600
COLORS = {"gmail": "#ea4335", "outlook": "#0078d4", "imap": "#7c3aed"}


def _app(provider: str) -> oauth.OAuthApp:
    app = oauth.oauth_app(provider) if provider in ("gmail", "outlook") else None
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Connecting {provider} accounts isn't set up on this server")
    return app


def require_real_user(user: User) -> None:
    if user.is_guest:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Create a free account to connect your own mailboxes. Demo accounts are deleted after 24 hours.")


@router.get("/providers", response_model=ProvidersOut)
def providers() -> ProvidersOut:
    """Which account types this server can connect."""
    return ProvidersOut(gmail=oauth.oauth_app("gmail") is not None, outlook=oauth.oauth_app("outlook") is not None)


@router.post("/{provider}/start", response_model=OAuthStartOut)
def start(provider: str, user: User = Depends(get_current_user)) -> OAuthStartOut:
    app = _app(provider)
    require_real_user(user)
    verifier, challenge = oauth.pkce_pair()
    state = encrypt_json({"uid": user.id, "provider": provider, "verifier": verifier, "nonce": secrets.token_hex(8)})
    return OAuthStartOut(url=oauth.authorization_url(app, state, challenge))


def _back_to_app(**params: str) -> RedirectResponse:
    return RedirectResponse(f"{settings.frontend_url}/?{urlencode(params)}", status_code=status.HTTP_303_SEE_OTHER)


def save_account(session: Session, user_id: int, provider: str, email: str, name: str, credentials: dict) -> MailAccount:
    """Create the account, or refresh the sign-in of one already connected (reconnect)."""
    account = session.exec(select(MailAccount).where(MailAccount.user_id == user_id, MailAccount.email == email)).first()
    if account is None:
        account = MailAccount(user_id=user_id, provider=provider, brand=provider, email=email, display_name=name or email.split("@")[0], color=COLORS[provider])
    elif account.provider != provider:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{email} is already connected another way")
    account.credentials = encrypt_json(credentials)
    account.needs_reauth = False
    account.sync_error = None
    account.failure_count = 0
    account.next_sync_at = utcnow()
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def first_sync(account_id: int) -> None:
    """Runs after the response, so the user sees the app at once while mail starts arriving."""
    with Session(database.engine) as session:
        account = session.get(MailAccount, account_id)
        if account:
            sync_account(session, account)


@router.get("/{provider}/callback", include_in_schema=False)
def callback(
    provider: str,
    background: BackgroundTasks,
    code: str = "",
    state: str = "",
    error: str = "",
    session: Session = Depends(get_session),
) -> RedirectResponse:
    if error:  # the user pressed Cancel, or the provider refused
        return _back_to_app(connect_error="You cancelled, or the provider refused access." if error == "access_denied" else error[:200])
    try:
        data = decrypt_json(state, max_age_seconds=STATE_TTL_SECONDS)
    except CryptoError:
        return _back_to_app(connect_error="That sign-in link expired. Please try again.")
    if data.get("provider") != provider or not code:
        return _back_to_app(connect_error="Invalid sign-in response.")
    user = session.get(User, data["uid"])
    if user is None or user.is_guest:
        return _back_to_app(connect_error="Please sign in to the hub again.")

    try:
        credentials = oauth.exchange_code(_app(provider), code, data["verifier"], oauth.make_http())
        identity = oauth_provider(provider, credentials).identity()
        account = save_account(session, user.id, provider, identity.email, identity.name, credentials)
    except ProviderError as exc:
        logger.warning("Connecting %s failed: %s", provider, exc)
        return _back_to_app(connect_error=str(exc)[:200])
    except HTTPException as exc:
        return _back_to_app(connect_error=exc.detail)
    background.add_task(first_sync, account.id)
    return _back_to_app(connected=account.email)
