"""In-memory stand-ins for the Gmail API, Microsoft Graph, IMAP and SMTP servers.

They implement just enough of each protocol for the adapters, so tests exercise real request
building and response parsing without a network or real accounts.
"""

import base64
import json
import re
from email.message import EmailMessage
from urllib.parse import parse_qs, urlparse

import httpx

TOKEN_URL_GOOGLE = "https://oauth2.googleapis.com/token"
GMAIL = "/gmail/v1/users/me"


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


class FakeTokens:
    """The token endpoint of Google or Microsoft."""

    def __init__(self) -> None:
        self.grants: list[dict] = []
        self.revoked: list[str] = []
        self.fail_refresh = False

    def handle(self, request: httpx.Request) -> httpx.Response | None:
        if request.url.path.endswith("/revoke"):
            self.revoked.append(parse_qs(request.content.decode())["token"][0])
            return httpx.Response(200)
        if not request.url.path.endswith("/token"):
            return None
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.grants.append(form)
        if form["grant_type"] == "refresh_token" and self.fail_refresh:
            return httpx.Response(400, json={"error": "invalid_grant"})
        n = len(self.grants)
        body = {"access_token": f"access-{n}", "expires_in": 3600, "token_type": "Bearer"}
        if form["grant_type"] == "authorization_code":
            body["refresh_token"] = "refresh-1"
        return httpx.Response(200, json=body)


def gmail_message(mid, thread, labels, subject="Hello", body="Hi there", html=None, sender="Priya Sharma <priya@example.net>", ts=1_760_000_000_000):
    parts = [{"mimeType": "text/plain", "headers": [{"name": "Content-Type", "value": "text/plain; charset=UTF-8"}], "body": {"data": b64(body)}}]
    if html:
        parts.append({"mimeType": "text/html", "body": {"data": b64(html)}})
    parts.append({"mimeType": "application/pdf", "filename": "invoice.pdf", "body": {"attachmentId": "att-1", "size": 1000}})
    return {
        "id": mid,
        "threadId": thread,
        "labelIds": labels,
        "internalDate": str(ts),
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": sender},
                {"name": "To", "value": "me@example.com"},
                {"name": "Subject", "value": subject},
                {"name": "Message-ID", "value": f"<{mid}@mail.example>"},
            ],
            "parts": parts,
        },
    }


class FakeGmail:
    def __init__(self, email: str = "me@example.com") -> None:
        self.email = email
        self.tokens = FakeTokens()
        self.messages: dict[str, dict] = {}
        self.history_id = "1000"
        self.history_pages: list[dict] | None = None  # served in order for /history; None = 404
        self.list_pages = 2
        self.requests: list[httpx.Request] = []
        self.modified: list[tuple[str, dict]] = []
        self.sent: list[dict] = []
        self.unauthorized_once = False

    def add(self, *messages: dict) -> None:
        for m in messages:
            self.messages[m["id"]] = m

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        token = self.tokens.handle(request)
        if token:
            return token
        if self.unauthorized_once:
            self.unauthorized_once = False
            return httpx.Response(401, json={"error": {"message": "expired"}})
        path = request.url.path.removeprefix(GMAIL)
        params = dict(request.url.params)
        if path == "/profile":
            return httpx.Response(200, json={"emailAddress": self.email, "historyId": self.history_id})
        if path == "/messages" and request.method == "GET":
            ids = sorted(self.messages)
            size = max(1, -(-len(ids) // self.list_pages))
            page = int(params.get("pageToken", "0"))
            chunk = ids[page * size : (page + 1) * size]
            body = {"messages": [{"id": i, "threadId": self.messages[i]["threadId"]} for i in chunk]}
            if (page + 1) * size < len(ids):
                body["nextPageToken"] = str(page + 1)
            return httpx.Response(200, json=body)
        if path == "/messages/send":
            self.sent.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "sent-1", "threadId": "t-1"})
        if match := re.fullmatch(r"/messages/([\w-]+)", path):
            message = self.messages.get(match.group(1))
            return httpx.Response(200, json=message) if message else httpx.Response(404, json={"error": {"message": "not found"}})
        if path == "/history":
            if self.history_pages is None:
                return httpx.Response(404, json={"error": {"message": "history expired"}})
            return httpx.Response(200, json=self.history_pages.pop(0))
        if match := re.fullmatch(r"/threads/([\w-]+)/modify", path):
            self.modified.append((match.group(1), json.loads(request.content)))
            return httpx.Response(200, json={})
        return httpx.Response(500, json={"error": {"message": f"unexpected {request.method} {path}"}})


def graph_message(mid, conversation, folder_id, subject="Status update", read=False, flagged=False, html=True, sender=("Jordan Blake", "jordan@northwind.example")):
    return {
        "id": mid,
        "conversationId": conversation,
        "subject": subject,
        "from": {"emailAddress": {"name": sender[0], "address": sender[1]}},
        "toRecipients": [{"emailAddress": {"name": "Me", "address": "me@contoso.example"}}],
        "ccRecipients": [],
        "receivedDateTime": "2026-10-20T09:30:00Z",
        "sentDateTime": "2026-10-20T09:29:00Z",
        "isRead": read,
        "isDraft": False,
        "flag": {"flagStatus": "flagged" if flagged else "notFlagged"},
        "body": {"contentType": "html" if html else "text", "content": "<p>Report <b>attached</b></p>" if html else "Plain body"},
        "parentFolderId": folder_id,
        "internetMessageId": f"<{mid}@contoso.example>",
    }


class FakeGraph:
    FOLDER_IDS = {"inbox": "F-INBOX", "archive": "F-ARCHIVE", "sentitems": "F-SENT"}

    def __init__(self) -> None:
        self.tokens = FakeTokens()
        # Pages per folder for the first delta call; later calls use the delta link pages.
        self.delta: dict[str, list[dict]] = {"inbox": [{"value": []}], "archive": [{"value": []}], "sentitems": [{"value": []}]}
        self.messages: dict[str, dict] = {}  # for GET /messages/{id}
        self.requests: list[httpx.Request] = []
        self.patches: list[tuple[str, dict]] = []
        self.moves: list[tuple[str, str]] = []
        self.posts: list[tuple[str, dict]] = []
        self.gone_links: set[str] = set()

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        token = self.tokens.handle(request)
        if token:
            return token
        url = str(request.url)
        path = request.url.path.removeprefix("/v1.0/me")
        if any(url.startswith(link) for link in self.gone_links):
            return httpx.Response(410, json={"error": {"code": "syncStateNotFound"}})
        if request.url.host == "delta.example":  # our fake next/delta links
            folder, index = request.url.path.strip("/").split("/")
            return self._page(folder, int(index))
        if path == "" and request.method == "GET":
            return httpx.Response(200, json={"mail": "me@contoso.example", "displayName": "Me Myself"})
        if match := re.fullmatch(r"/mailFolders/(\w+)", path):
            name = match.group(1)
            return httpx.Response(200, json={"id": self.FOLDER_IDS[name]}) if name in self.FOLDER_IDS else httpx.Response(404, json={})
        if match := re.fullmatch(r"/mailFolders/(\w+)/messages/delta", path):
            return self._page(match.group(1), 0)
        if match := re.fullmatch(r"/messages/([\w-]+)", path):
            if request.method == "PATCH":
                self.patches.append((match.group(1), json.loads(request.content)))
                return httpx.Response(200, json={})
            message = self.messages.get(match.group(1))
            return httpx.Response(200, json=message) if message else httpx.Response(404, json={})
        if match := re.fullmatch(r"/messages/([\w-]+)/move", path):
            self.moves.append((match.group(1), json.loads(request.content)["destinationId"]))
            return httpx.Response(201, json={})
        if request.method == "POST":
            self.posts.append((path, json.loads(request.content)))
            return httpx.Response(202)
        return httpx.Response(500, json={"error": {"message": f"unexpected {request.method} {path}"}})

    def _page(self, folder: str, index: int) -> httpx.Response:
        pages = self.delta[folder]
        body = dict(pages[index]) if index < len(pages) else {"value": []}
        if index + 1 < len(pages):
            body["@odata.nextLink"] = f"https://delta.example/{folder}/{index + 1}"
        else:
            body["@odata.deltaLink"] = f"https://delta.example/{folder}/{len(pages)}"
        return httpx.Response(200, json=body)


def rfc822(subject, sender="Neha Kapoor <neha@oldmail.example>", body="Hello!", msgid="<1@oldmail.example>", references="", in_reply_to="", html=None) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "me@oldmail.example"
    msg["Subject"] = subject
    msg["Date"] = "Mon, 20 Oct 2026 10:00:00 +0530"
    msg["Message-ID"] = msgid
    if references:
        msg["References"] = references
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg.as_bytes()


class FakeImap:
    """Enough of imaplib.IMAP4 for ImapProvider: SELECT, UID SEARCH/FETCH/STORE."""

    def __init__(self, validity: str = "7") -> None:
        self.validity = validity
        self.mail: dict[int, dict] = {}  # uid -> {"flags": set, "raw": bytes}
        self.stores: list[tuple[str, str, str]] = []
        self.readonly: list[bool] = []
        self.logged_out = 0

    def add(self, uid: int, raw: bytes, flags=()) -> None:
        self.mail[uid] = {"flags": set(flags), "raw": raw}

    def connect(self, credentials: dict) -> "FakeImap":
        return self

    def select(self, mailbox, readonly=False):
        self.readonly.append(readonly)
        return "OK", [str(len(self.mail)).encode()]

    def response(self, code):
        return code, [self.validity.encode()]

    def logout(self):
        self.logged_out += 1

    def _uids(self, spec: str) -> list[int]:
        result = []
        for part in spec.split(","):
            if ":" in part:
                lo, hi = part.split(":")
                top = max(self.mail, default=0)
                hi_n = top if hi == "*" else int(hi)
                lo_n = int(lo)
                result += [u for u in self.mail if min(lo_n, hi_n) <= u <= max(lo_n, hi_n)] or ([top] if hi == "*" and top else [])
            elif int(part) in self.mail:
                result.append(int(part))
        return sorted(set(result))

    def uid(self, command, *args):
        if command == "SEARCH":
            criteria = args[1]
            uids = self._uids(criteria[4:]) if criteria.startswith("UID ") else sorted(self.mail)
            return "OK", [" ".join(map(str, uids)).encode()]
        if command == "FETCH":
            spec, parts = args
            out = []
            for i, uid in enumerate(self._uids(spec), 1):
                item = self.mail[uid]
                flags = " ".join(sorted(item["flags"]))
                if "BODY.PEEK" in parts:
                    raw = item["raw"] if "[HEADER]" not in parts else item["raw"].split(b"\n\n")[0] + b"\n\n"
                    out.append((f"{i} (UID {uid} FLAGS ({flags}) BODY[] {{{len(raw)}}}".encode(), raw))
                    out.append(b")")
                elif "RFC822.SIZE" in parts:
                    out.append(f"{i} (UID {uid} RFC822.SIZE {item.get('size', len(item['raw']))})".encode())
                else:
                    out.append(f"{i} (UID {uid} FLAGS ({flags}))".encode())
            return "OK", out
        if command == "STORE":
            spec, op, flags = args
            self.stores.append((spec, op, flags))
            for uid in self._uids(spec):
                flag = flags.strip("()")
                (self.mail[uid]["flags"].add if op == "+FLAGS" else self.mail[uid]["flags"].discard)(flag)
            return "OK", [b""]
        raise AssertionError(f"unexpected IMAP command {command}")


class FakeSmtp:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def connect(self, credentials: dict) -> "FakeSmtp":
        return self

    def send_message(self, message):
        self.sent.append(message)

    def quit(self):
        pass


def query(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
