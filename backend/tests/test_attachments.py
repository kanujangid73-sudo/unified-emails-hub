import base64
import time
from datetime import datetime, timezone

import httpx

from app.providers import Address, OutgoingAttachment, OutgoingMessage, ReplyContext
from app.providers.gmail import GmailProvider
from app.providers.imap import ImapProvider
from app.providers.mime import build_message
from app.providers.oauth import OAuthApp, OAuthSession
from app.providers.outlook import OutlookProvider
from app.routers.attachments import content_disposition, safe_type
from tests.fakes import FakeGmail, FakeGraph, FakeImap, FakeSmtp, gmail_message, graph_message, rfc822
from tests.test_threads import all_pages, inbox


def oauth(fake, provider):
    app = OAuthApp(provider, "c", "s", "https://auth.example", "https://oauth2.googleapis.com/token", ("x",))
    credentials = {"access_token": "a", "refresh_token": "r", "expires_at": int(time.time()) + 3600}
    return OAuthSession(app, credentials, httpx.Client(transport=fake.transport()), lambda _: None)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# ------------------------------------------------------------------ adapters


def test_gmail_lists_files_by_stable_part_id_and_downloads_them():
    fake = FakeGmail()
    fake.add(gmail_message("m1", "t1", ["INBOX"]))
    provider = GmailProvider(oauth(fake, "gmail"))
    message = provider.fetch_changes(None).messages[0]
    (attachment,) = message.attachments
    assert (attachment.filename, attachment.mime_type, attachment.ref) == ("invoice.pdf", "application/pdf", "2")
    assert provider.fetch_attachment("m1", attachment.ref) == b"%PDF-1.4 invoice"


def test_gmail_sends_files_as_mime_parts():
    fake = FakeGmail()
    GmailProvider(oauth(fake, "gmail")).send(
        OutgoingMessage(Address("me@example.com"), (Address("a@example.org"),), "Report", "See attached", attachments=(OutgoingAttachment("r.csv", "text/csv", b"a,b\n1,2"),))
    )
    from email import message_from_bytes, policy

    mime = message_from_bytes(base64.urlsafe_b64decode(fake.sent[0]["raw"]), policy=policy.default)
    (part,) = list(mime.iter_attachments())
    assert part.get_filename() == "r.csv" and part.get_content() == "a,b\n1,2"


def test_outlook_lists_downloadable_files_only():
    fake = FakeGraph()
    fake.delta["inbox"] = [{"value": [graph_message("i1", "c1", "F-INBOX", files=True), graph_message("i2", "c2", "F-INBOX")]}]
    provider = OutlookProvider(oauth(fake, "outlook"))
    batch = provider.fetch_changes(None)
    with_files, without = batch.messages
    assert [(a.filename, a.inline) for a in with_files.attachments] == [("report.xlsx", False), ("logo.png", True)]  # cloud link skipped
    assert without.attachments == ()
    assert sum("/attachments" in r.url.path for r in fake.requests) == 1  # only asked for the message that has some
    assert provider.fetch_attachment("i1", "A1") == b"spreadsheet bytes"


def test_outlook_reply_with_files_goes_through_a_draft():
    fake = FakeGraph()
    OutlookProvider(oauth(fake, "outlook")).send(
        OutgoingMessage(
            Address("me@contoso.example"),
            (Address("jordan@northwind.example"),),
            "Re: x",
            "Here it is",
            reply_to=ReplyContext("i1", "c1"),
            attachments=(OutgoingAttachment("notes.txt", "text/plain", b"hello"),),
        )
    )
    paths = [p for p, _ in fake.posts]
    assert paths == ["/messages/i1/createReply", "/messages/draft-1/attachments", "/messages/draft-1/send"]
    assert fake.posts[1][1]["contentBytes"] == b64(b"hello")


def test_imap_attachments_are_parsed_and_fetched_again_on_demand():
    server = FakeImap()
    server.add(4, rfc822("Photos", msgid="<p@x>", attachment=("trek.png", "image/png", b"\x89PNG fake")))
    provider = ImapProvider({}, "me@oldmail.example", connect=server.connect, now=lambda: datetime.now(timezone.utc))
    (attachment,) = provider.fetch_changes(None).messages[0].attachments
    assert (attachment.filename, attachment.size, attachment.ref) == ("trek.png", 9, "0")
    assert provider.fetch_attachment("7:4", "0") == b"\x89PNG fake"


def test_smtp_copy_keeps_the_files():
    smtp = FakeSmtp()
    provider = ImapProvider({}, "me@oldmail.example", connect=FakeImap().connect, smtp=smtp.connect)
    stored = provider.send(
        OutgoingMessage(Address("me@oldmail.example"), (Address("a@example.org"),), "Doc", "Attached", attachments=(OutgoingAttachment("a.pdf", "application/pdf", b"%PDF"),))
    )
    assert stored.attachments[0].data == b"%PDF"
    assert [p.get_filename() for p in smtp.sent[0].iter_attachments()] == ["a.pdf"]


def test_mime_round_trip():
    msg = build_message(OutgoingMessage(Address("a@x.example"), (Address("b@x.example"),), "s", "body", attachments=(OutgoingAttachment("x", "bogus", b"1"),)))
    (part,) = list(msg.iter_attachments())
    assert part.get_content_type() == "application/octet-stream"  # invalid type made safe


# ------------------------------------------------------------------ API


def trek(client, headers):
    return inbox(client, headers, folder="all", q="Photos from the trek")["threads"][0]


def test_demo_attachments_are_listed_and_downloadable(client, demo):
    thread = trek(client, demo)
    assert thread["attachment_count"] == 2
    detail = client.get(f"/api/threads/{thread['id']}", headers=demo).json()
    files = detail["messages"][0]["attachments"]
    assert [f["filename"] for f in files] == ["summit-sunrise.png", "trail-group-photo.png"]

    res = client.get(f"/api/attachments/{files[0]['id']}", headers=demo)
    assert res.status_code == 200 and res.content.startswith(b"\x89PNG")
    assert res.headers["content-type"] == "image/png"
    assert res.headers["content-disposition"].startswith('attachment; filename="summit-sunrise.png"')
    assert res.headers["x-content-type-options"] == "nosniff"

    invoice = inbox(client, demo, folder="all", q="has:attachment Order SK")["threads"][0]
    pdf = client.get(f"/api/threads/{invoice['id']}", headers=demo).json()["messages"][0]["attachments"][0]
    assert client.get(f"/api/attachments/{pdf['id']}", headers=demo).content.startswith(b"%PDF-1.4")


def test_has_attachment_search(client, demo):
    with_files = all_pages(client, demo, folder="all", q="has:attachment")
    assert len(with_files) == 8 and all(t["attachment_count"] > 0 for t in with_files)


def test_other_users_cannot_download(client, demo, auth):
    thread = trek(client, demo)
    file_id = client.get(f"/api/threads/{thread['id']}", headers=demo).json()["messages"][0]["attachments"][0]["id"]
    assert client.get(f"/api/attachments/{file_id}", headers=auth).status_code == 404
    assert client.get("/api/attachments/999999", headers=demo).status_code == 404


def test_send_and_reply_with_attachments(client, demo):
    account = next(a for a in client.get("/api/accounts", headers=demo).json() if a["brand"] == "gmail")
    files = [{"filename": "notes.txt", "mime_type": "text/plain", "data": b64(b"bring bats")}]
    thread = client.post(
        "/api/messages", headers=demo, json={"account_id": account["id"], "to": ["sam@example.org"], "subject": "Kit", "body": "List attached", "attachments": files}
    ).json()
    assert thread["attachment_count"] == 1
    sent = client.get(f"/api/threads/{thread['id']}", headers=demo).json()["messages"][0]["attachments"][0]
    assert client.get(f"/api/attachments/{sent['id']}", headers=demo).content == b"bring bats"

    cricket = inbox(client, demo, q="Cricket this Saturday")["threads"][0]
    replied = client.post(
        "/api/messages",
        headers=demo,
        json={"account_id": cricket["account_id"], "to": ["rohan.mehta@example.net"], "body": "In!", "reply_to_thread_id": cricket["id"], "attachments": files},
    ).json()
    assert replied["attachment_count"] == 1 and replied["message_count"] == cricket["message_count"] + 1


def test_attachment_validation(client, demo):
    account_id = client.get("/api/accounts", headers=demo).json()[0]["id"]
    base = {"account_id": account_id, "to": ["a@example.org"], "body": "x"}

    bad = client.post("/api/messages", headers=demo, json={**base, "attachments": [{"filename": "a.txt", "data": "not base64!"}]})
    assert bad.status_code == 422
    big = b64(b"x" * (10 * 1024 * 1024 + 1))
    assert client.post("/api/messages", headers=demo, json={**base, "attachments": [{"filename": "big.bin", "data": big}]}).status_code == 413

    evil = client.post("/api/messages", headers=demo, json={**base, "attachments": [{"filename": "../../etc/passwd", "mime_type": "text/html", "data": b64(b"<script>x</script>")}]}).json()
    file = client.get(f"/api/threads/{evil['id']}", headers=demo).json()["messages"][0]["attachments"][0]
    assert file["filename"] == "_.._etc_passwd"
    download = client.get(f"/api/attachments/{file['id']}", headers=demo)
    assert download.headers["content-type"] == "application/octet-stream"  # HTML is never rendered
    assert "sandbox" in download.headers["content-security-policy"]


def test_download_headers():
    assert safe_type("image/svg+xml") == "application/octet-stream"
    assert safe_type("application/pdf; name=x") == "application/pdf"
    assert content_disposition('बिल "1".pdf') == "attachment; filename=\"___ _1_.pdf\"; filename*=UTF-8''%E0%A4%AC%E0%A4%BF%E0%A4%B2%20%221%22.pdf"


def test_disconnecting_removes_attachments(client, demo, session):
    from sqlmodel import select

    from app.models import Attachment

    assert session.exec(select(Attachment)).all()
    for account in client.get("/api/accounts", headers=demo).json():
        client.delete(f"/api/accounts/{account['id']}", headers=demo)
    session.expire_all()
    assert session.exec(select(Attachment)).all() == []
