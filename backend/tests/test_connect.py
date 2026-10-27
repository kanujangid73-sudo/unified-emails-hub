import httpx
import pytest
from sqlmodel import select

from app.config import settings
from app.crypto import decrypt_json
from app.models import MailAccount
from app.providers import AuthError, oauth
from app.providers.imap import ImapProvider
from tests.conftest import register
from tests.fakes import FakeGmail, gmail_message, query


@pytest.fixture()
def google(monkeypatch):
    """Configure Google sign-in and route all HTTP to a fake Gmail."""
    fake = FakeGmail("real.person@example.com")
    fake.add(gmail_message("m1", "t1", ["INBOX", "UNREAD"], subject="Welcome to your new inbox"))
    monkeypatch.setattr(settings, "google_client_id", "client-123")
    monkeypatch.setattr(settings, "google_client_secret", "secret")
    monkeypatch.setattr(oauth, "make_http", lambda: httpx.Client(transport=fake.transport()))
    return fake


def start(client, auth, provider="gmail"):
    res = client.post(f"/api/oauth/{provider}/start", headers=auth)
    assert res.status_code == 200, res.text
    return query(res.json()["url"])


def test_providers_reflect_server_configuration(client, google):
    assert client.get("/api/oauth/providers").json() == {"gmail": True, "outlook": False, "imap": True}


def test_start_builds_a_pkce_authorization_url(client, auth, google):
    params = start(client, auth)
    assert params["client_id"] == "client-123"
    assert params["redirect_uri"] == "http://localhost:8000/api/oauth/gmail/callback"
    assert params["code_challenge_method"] == "S256" and params["access_type"] == "offline"
    assert "gmail.modify" in params["scope"]
    assert params["state"]


def test_unconfigured_provider_and_guests_are_refused(client, auth, demo, google):
    assert client.post("/api/oauth/outlook/start", headers=auth).status_code == 404
    assert client.post("/api/oauth/gmail/start", headers=demo).status_code == 403


def test_callback_connects_the_account_and_syncs_it(client, auth, google):
    state = start(client, auth)["state"]
    res = client.get("/api/oauth/gmail/callback", params={"code": "the-code", "state": state}, follow_redirects=False)

    assert res.status_code == 303
    assert res.headers["location"] == "http://localhost:5173/?connected=real.person%40example.com"
    exchange = google.tokens.grants[0]
    assert exchange["grant_type"] == "authorization_code" and exchange["code_verifier"]

    account = client.get("/api/accounts", headers=auth).json()[0]
    assert (account["provider"], account["email"], account["needs_reauth"]) == ("gmail", "real.person@example.com", False)
    # The first sync ran in the background after the redirect.
    threads = client.get("/api/threads", headers=auth).json()["threads"]
    assert [t["subject"] for t in threads] == ["Welcome to your new inbox"]


def test_tokens_are_stored_encrypted(client, auth, google, session):
    state = start(client, auth)["state"]
    client.get("/api/oauth/gmail/callback", params={"code": "c", "state": state}, follow_redirects=False)
    stored = session.exec(select(MailAccount)).one().credentials
    assert "refresh-1" not in stored
    assert decrypt_json(stored)["refresh_token"] == "refresh-1"


def test_bad_or_cancelled_callbacks_go_back_with_an_error(client, auth, google):
    res = client.get("/api/oauth/gmail/callback", params={"code": "c", "state": "forged"}, follow_redirects=False)
    assert "connect_error=That+sign-in+link+expired" in res.headers["location"]
    res = client.get("/api/oauth/gmail/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert "connect_error=You+cancelled" in res.headers["location"]
    # A state minted for Gmail can't be replayed against another provider's callback.
    state = start(client, auth)["state"]
    res = client.get("/api/oauth/outlook/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert "connect_error" in res.headers["location"]
    assert client.get("/api/accounts", headers=auth).json() == []


def test_reconnecting_refreshes_credentials_and_clears_the_error(client, auth, google, session):
    for _ in range(2):
        state = start(client, auth)["state"]
        client.get("/api/oauth/gmail/callback", params={"code": "c", "state": state}, follow_redirects=False)
    accounts = session.exec(select(MailAccount)).all()
    assert len(accounts) == 1


def test_disconnecting_gmail_revokes_access(client, auth, google):
    state = start(client, auth)["state"]
    client.get("/api/oauth/gmail/callback", params={"code": "c", "state": state}, follow_redirects=False)
    account_id = client.get("/api/accounts", headers=auth).json()[0]["id"]
    assert client.delete(f"/api/accounts/{account_id}", headers=auth).status_code == 204
    assert google.tokens.revoked == ["refresh-1"]


IMAP_FORM = {
    "email": "me@oldmail.example",
    "password": "app-password",
    "imap_host": "imap.oldmail.example",
    "smtp_host": "smtp.oldmail.example",
}


def test_imap_connect_checks_the_login_first(client, auth, monkeypatch):
    def refuse(self):
        raise AuthError("The mail server rejected the username or password.")

    monkeypatch.setattr(ImapProvider, "verify", refuse)
    res = client.post("/api/accounts/imap", headers=auth, json=IMAP_FORM)
    assert res.status_code == 400 and "rejected" in res.json()["detail"]
    assert client.get("/api/accounts", headers=auth).json() == []


def test_imap_connect_stores_the_password_encrypted(client, auth, monkeypatch, session):
    monkeypatch.setattr(ImapProvider, "verify", lambda self: None)
    monkeypatch.setattr("app.routers.accounts.first_sync", lambda account_id: None)
    res = client.post("/api/accounts/imap", headers=auth, json={**IMAP_FORM, "display_name": "Old mail"})
    assert res.status_code == 201, res.text
    assert res.json()["brand"] == "imap" and res.json()["display_name"] == "Old mail"
    stored = session.exec(select(MailAccount)).one().credentials
    assert "app-password" not in stored
    assert decrypt_json(stored)["imap_host"] == "imap.oldmail.example"


def test_each_account_gets_its_own_colour(client, auth, monkeypatch):
    monkeypatch.setattr(ImapProvider, "verify", lambda self: None)
    monkeypatch.setattr("app.routers.accounts.first_sync", lambda account_id: None)
    for email in ("a@oldmail.example", "b@oldmail.example"):
        assert client.post("/api/accounts/imap", headers=auth, json={**IMAP_FORM, "email": email}).status_code == 201
    colours = [a["color"] for a in client.get("/api/accounts", headers=auth).json()]
    assert colours[0] == "#7c3aed" and len(set(colours)) == 2


def test_gmail_app_password_spaces_are_removed(client, auth, monkeypatch, session):
    monkeypatch.setattr(ImapProvider, "verify", lambda self: None)
    monkeypatch.setattr("app.routers.accounts.first_sync", lambda account_id: None)
    form = {**IMAP_FORM, "email": "me@gmail.com", "password": "abcd efgh ijkl mnop", "imap_host": "imap.gmail.com", "smtp_host": "smtp.gmail.com"}
    assert client.post("/api/accounts/imap", headers=auth, json=form).status_code == 201
    assert decrypt_json(session.exec(select(MailAccount)).one().credentials)["password"] == "abcdefghijklmnop"


def test_imap_form_is_validated(client, auth):
    assert client.post("/api/accounts/imap", headers=auth, json={**IMAP_FORM, "imap_port": 143}).status_code == 422  # TLS only
    assert client.post("/api/accounts/imap", headers=auth, json={**IMAP_FORM, "imap_host": "evil host;"}).status_code == 422
    assert client.post("/api/accounts/imap", headers=auth, json={**IMAP_FORM, "email": "not-an-email"}).status_code == 422


def test_private_hosts_are_refused_in_production(monkeypatch):
    from app.net import UnsafeHostError, check_public_host

    monkeypatch.setattr(settings, "allow_private_hosts", False)
    for host in ("localhost", "127.0.0.1", "10.0.0.5", "169.254.169.254"):
        with pytest.raises(UnsafeHostError):
            check_public_host(host, 993)
    check_public_host("8.8.8.8", 993)


def test_guests_cannot_connect_imap(client, demo):
    assert client.post("/api/accounts/imap", headers=demo, json=IMAP_FORM).status_code == 403


def test_registered_user_imap_is_independent_of_other_users(client):
    a = register(client, "first", "secret123")
    b = register(client, "second", "secret123")
    assert client.get("/api/accounts", headers=a).json() == client.get("/api/accounts", headers=b).json() == []
