"""OAuth 2.0 for Gmail and Outlook: authorization URLs, code exchange and token refresh.

Uses the authorization code flow with PKCE. Access tokens last about an hour; the refresh
token is kept (encrypted) and used to get new ones without bothering the user. If the user
revokes access, refreshing fails with invalid_grant and the account is flagged for reconnect.
"""

import base64
import hashlib
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx

from ..config import settings
from .base import AuthError, ProviderError

TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def make_http() -> httpx.Client:
    """The HTTP client adapters use. Tests replace this to talk to fake APIs."""
    return httpx.Client(timeout=TIMEOUT)


@dataclass(frozen=True)
class OAuthApp:
    provider: str
    client_id: str
    client_secret: str
    auth_url: str
    token_url: str
    scopes: tuple[str, ...]
    extra_auth_params: dict = field(default_factory=dict)
    revoke_url: str | None = None


def oauth_app(provider: str) -> OAuthApp | None:
    """The configured OAuth app for a provider, or None when the server has no credentials for it."""
    if provider == "gmail" and settings.google_client_id and settings.google_client_secret:
        return OAuthApp(
            provider="gmail",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            auth_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            # Read, label (read/star/archive) and send. Never permanent deletion.
            scopes=("https://www.googleapis.com/auth/gmail.modify",),
            # offline + consent: always return a refresh token, even when reconnecting.
            extra_auth_params={"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"},
            revoke_url="https://oauth2.googleapis.com/revoke",
        )
    if provider == "outlook" and settings.microsoft_client_id and settings.microsoft_client_secret:
        base = f"https://login.microsoftonline.com/{settings.microsoft_tenant}/oauth2/v2.0"
        return OAuthApp(
            provider="outlook",
            client_id=settings.microsoft_client_id,
            client_secret=settings.microsoft_client_secret,
            auth_url=f"{base}/authorize",
            token_url=f"{base}/token",
            scopes=("offline_access", "User.Read", "Mail.ReadWrite", "Mail.Send"),
            extra_auth_params={"prompt": "select_account"},
        )
    return None


def redirect_uri(provider: str) -> str:
    return f"{settings.public_api_url}/api/oauth/{provider}/callback"


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorization_url(app: OAuthApp, state: str, challenge: str) -> str:
    params = {
        "client_id": app.client_id,
        "redirect_uri": redirect_uri(app.provider),
        "response_type": "code",
        "scope": " ".join(app.scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        **app.extra_auth_params,
    }
    return f"{app.auth_url}?{urlencode(params)}"


def _token_request(app: OAuthApp, http: httpx.Client, data: dict) -> dict:
    try:
        res = http.post(app.token_url, data={"client_id": app.client_id, "client_secret": app.client_secret, **data})
    except httpx.TransportError as exc:
        raise ProviderError(f"Couldn't reach {app.provider}: {exc}", retryable=True) from exc
    body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
    if res.status_code in (400, 401) and body.get("error") in {"invalid_grant", "invalid_client", "unauthorized_client"}:
        raise AuthError(f"{app.provider} access was revoked or expired. Reconnect the account.")
    if res.status_code >= 500 or res.status_code == 429:
        raise ProviderError(f"{app.provider} sign-in is unavailable (HTTP {res.status_code})", retryable=True)
    if res.status_code != 200 or "access_token" not in body:
        raise ProviderError(f"{app.provider} sign-in failed: {body.get('error_description') or body.get('error') or res.status_code}")
    return body


def _credentials(body: dict, previous: dict | None = None) -> dict:
    return {
        "access_token": body["access_token"],
        # Google returns a refresh token only on the first exchange; Microsoft rotates it.
        "refresh_token": body.get("refresh_token") or (previous or {}).get("refresh_token"),
        "expires_at": int(time.time()) + int(body.get("expires_in", 3600)),
    }


def exchange_code(app: OAuthApp, code: str, verifier: str, http: httpx.Client) -> dict:
    body = _token_request(
        app,
        http,
        {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(app.provider), "code_verifier": verifier},
    )
    credentials = _credentials(body)
    if not credentials["refresh_token"]:
        raise ProviderError(f"{app.provider} didn't grant offline access. Try connecting again.")
    return credentials


class OAuthSession:
    """Makes API calls with a valid access token, refreshing it when needed."""

    def __init__(self, app: OAuthApp, credentials: dict, http: httpx.Client, on_refresh: Callable[[dict], None]) -> None:
        self.app = app
        self.credentials = credentials
        self.http = http
        self.on_refresh = on_refresh

    def refresh(self) -> None:
        if not self.credentials.get("refresh_token"):
            raise AuthError(f"No refresh token for {self.app.provider}. Reconnect the account.")
        body = _token_request(self.app, self.http, {"grant_type": "refresh_token", "refresh_token": self.credentials["refresh_token"]})
        self.credentials = _credentials(body, self.credentials)
        self.on_refresh(self.credentials)

    def request(self, method: str, url: str, *, allow: tuple[int, ...] = (404,), **kwargs) -> httpx.Response:
        """Returns the response for 2xx and the `allow`ed statuses (e.g. 404: callers decide what
        a missing item means). Other errors raise ProviderError or AuthError."""
        if self.credentials.get("expires_at", 0) < time.time() + 60:
            self.refresh()
        res = self._send(method, url, **kwargs)
        if res.status_code == 401:  # revoked early, or clock skew: refresh once and retry
            self.refresh()
            res = self._send(method, url, **kwargs)
            if res.status_code == 401:
                raise AuthError(f"{self.app.provider} rejected the account's access. Reconnect it.")
        if res.status_code == 429 or res.status_code >= 500:
            raise ProviderError(f"{self.app.provider} is busy (HTTP {res.status_code})", retryable=True)
        if res.status_code == 403:
            raise ProviderError(f"{self.app.provider} refused the request: {_error(res)}", retryable="rateLimit" in res.text)
        if res.status_code >= 400 and res.status_code not in allow:
            raise ProviderError(f"{self.app.provider} error (HTTP {res.status_code}): {_error(res)}")
        return res

    def _send(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = {**kwargs.pop("headers", {}), "Authorization": f"Bearer {self.credentials['access_token']}"}
        try:
            return self.http.request(method, url, headers=headers, **kwargs)
        except httpx.TransportError as exc:
            raise ProviderError(f"Couldn't reach {self.app.provider}: {exc}", retryable=True) from exc

    def revoke(self) -> None:
        if not self.app.revoke_url:
            return
        token = self.credentials.get("refresh_token") or self.credentials.get("access_token")
        try:
            self.http.post(self.app.revoke_url, data={"token": token})
        except httpx.TransportError:
            pass  # best effort


def _error(res: httpx.Response) -> str:
    try:
        error = res.json().get("error")
    except ValueError:
        return res.text[:200]
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or error)[:200]
    return str(error)[:200]
