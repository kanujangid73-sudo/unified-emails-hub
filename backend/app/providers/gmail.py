"""Gmail adapter, using the Gmail REST API.

First sync: the newest SYNC_BACKFILL_DAYS of mail, page by page, remembering the mailbox's
historyId from before the first page. Later syncs: history.list from that historyId, which
lists exactly what changed (new messages, label changes, deletions). Gmail keeps history for
about a week; when it has expired the API answers 404 and the account is synced afresh.

Gmail labels map onto the hub's flags: UNREAD, STARRED, and INBOX (no INBOX = archived).
"""

import base64
import json
import re
from datetime import datetime, timezone

from .base import Address, FlagChange, MailProvider, OutgoingMessage, ProviderError, RemoteAttachment, RemoteFlags, RemoteMessage, SyncBatch
from .mime import addresses, build_message, parse_date
from .oauth import OAuthSession

API = "https://gmail.googleapis.com/gmail/v1/users/me"
HIDDEN = {"DRAFT", "SPAM", "TRASH"}  # labels whose messages don't belong in the hub


def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _charset(headers: dict[str, str]) -> str:
    match = re.search(r'charset="?([\w.-]+)', headers.get("content-type", ""), re.I)
    return match.group(1) if match else "utf-8"


def _headers(part: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in part.get("headers", [])}


def _bodies(part: dict, found: dict[str, str]) -> None:
    """Collect the first text/plain and text/html parts that aren't attachments."""
    mime = part.get("mimeType", "")
    data = part.get("body", {}).get("data")
    if data and not part.get("filename") and mime in ("text/plain", "text/html") and mime not in found:
        try:
            found[mime] = _b64decode(data).decode(_charset(_headers(part)), errors="replace")
        except LookupError:  # unknown charset name
            found[mime] = _b64decode(data).decode("utf-8", errors="replace")
    for child in part.get("parts", []):
        _bodies(child, found)


def _files(part: dict, found: list[RemoteAttachment]) -> None:
    """Parts with a file name. Their part id is stable, unlike Gmail's attachmentId."""
    body = part.get("body", {})
    if part.get("filename") and (body.get("attachmentId") or body.get("data")):
        headers = _headers(part)
        found.append(
            RemoteAttachment(
                filename=part["filename"][:255],
                mime_type=part.get("mimeType") or "application/octet-stream",
                size=int(body.get("size", 0)),
                ref=part.get("partId", ""),
                content_id=headers.get("content-id", "").strip("<> ")[:255],
                inline=headers.get("content-disposition", "").lower().startswith("inline"),
            )
        )
    for child in part.get("parts", []):
        _files(child, found)


def _find_part(part: dict, part_id: str) -> dict | None:
    if part.get("partId") == part_id:
        return part
    for child in part.get("parts", []):
        if found := _find_part(child, part_id):
            return found
    return None


def parse_gmail_message(data: dict) -> RemoteMessage:
    payload = data.get("payload", {})
    headers = _headers(payload)
    labels = set(data.get("labelIds", []))
    received = datetime.fromtimestamp(int(data.get("internalDate", "0")) / 1000, tz=timezone.utc)
    bodies: dict[str, str] = {}
    _bodies(payload, bodies)
    files: list[RemoteAttachment] = []
    _files(payload, files)
    senders = addresses(headers.get("from"))
    return RemoteMessage(
        remote_id=data["id"],
        thread_id=data["threadId"],
        sender=senders[0] if senders else Address(""),
        to=addresses(headers.get("to")),
        cc=addresses(headers.get("cc")),
        subject=headers.get("subject", "").strip(),
        # internalDate is when Gmail received it, which is what Gmail sorts by.
        sent_at=received if data.get("internalDate") else parse_date(headers.get("date"), received),
        body_text=bodies.get("text/plain", ""),
        body_html=bodies.get("text/html", ""),
        is_read="UNREAD" not in labels,
        is_starred="STARRED" in labels,
        is_archived="INBOX" not in labels,
        message_id_header=headers.get("message-id", "").strip(),
        references=" ".join(headers.get("references", "").split()),
        list_unsubscribe=" ".join(headers.get("list-unsubscribe", "").split()),
        attachments=tuple(files),
        size=data.get("sizeEstimate"),
    )


def _flags(message: dict) -> RemoteFlags:
    labels = set(message.get("labelIds", []))
    return RemoteFlags(
        remote_id=message["id"],
        is_read="UNREAD" not in labels,
        is_starred="STARRED" in labels,
        is_archived="INBOX" not in labels,
    )


class GmailProvider(MailProvider):
    page_size = 50

    def __init__(self, session: OAuthSession, backfill_days: int = 30) -> None:
        self.api = session
        self.backfill_days = backfill_days

    def _get(self, path: str, **params):
        return self.api.request("GET", f"{API}{path}", params=params)

    def identity(self) -> Address:
        profile = self._get("/profile").json()
        return Address(profile["emailAddress"])

    def _fetch(self, ids: list[str], batch: SyncBatch) -> None:
        for message_id in ids:
            res = self._get(f"/messages/{message_id}", format="full")
            if res.status_code == 404:
                batch.deleted.append(message_id)
                continue
            data = res.json()
            if HIDDEN & set(data.get("labelIds", [])):
                batch.deleted.append(message_id)
            else:
                batch.messages.append(parse_gmail_message(data))

    def fetch_changes(self, cursor: str | None) -> SyncBatch:
        state = json.loads(cursor) if cursor else {}
        if "history" not in state or "backfill" in state:
            return self._backfill(state)
        return self._history(state)

    def _backfill(self, state: dict) -> SyncBatch:
        # Remember where history starts *before* listing, so nothing that arrives during the
        # backfill is missed: it shows up in history afterwards (and upserts make overlap harmless).
        history = state.get("history") or self._get("/profile").json()["historyId"]
        params = {"maxResults": self.page_size, "q": f"newer_than:{self.backfill_days}d", "includeSpamTrash": "false"}
        if state.get("backfill"):
            params["pageToken"] = state["backfill"]
        page = self._get("/messages", **params).json()
        batch = SyncBatch()
        self._fetch([m["id"] for m in page.get("messages", [])], batch)
        token = page.get("nextPageToken")
        batch.cursor = json.dumps({"history": history, "backfill": token} if token else {"history": history})
        batch.has_more = bool(token)
        return batch

    def _history(self, state: dict) -> SyncBatch:
        params = {"startHistoryId": state["history"], "maxResults": 100}
        if state.get("page"):
            params["pageToken"] = state["page"]
        res = self._get("/history", **params)
        if res.status_code == 404:
            # History this old is gone: start again from a fresh backfill.
            return SyncBatch(reset=True, cursor=None, has_more=True)
        data = res.json()

        added: dict[str, None] = {}  # ordered set
        flags: dict[str, RemoteFlags] = {}
        deleted: set[str] = set()
        for record in data.get("history", []):
            for item in record.get("messagesAdded", []):
                added[item["message"]["id"]] = None
            for key in ("labelsAdded", "labelsRemoved"):
                for item in record.get(key, []):
                    message = item["message"]
                    if HIDDEN & set(message.get("labelIds", [])):
                        deleted.add(message["id"])
                    else:
                        flags[message["id"]] = _flags(message)
            for item in record.get("messagesDeleted", []):
                deleted.add(item["message"]["id"])

        batch = SyncBatch(deleted=sorted(deleted))
        new_ids = [i for i in added if i not in deleted]
        self._fetch(new_ids, batch)
        # A full fetch already carries the latest labels.
        batch.flags = [f for i, f in flags.items() if i not in deleted and i not in added]

        token = data.get("nextPageToken")
        if token:
            batch.cursor = json.dumps({"history": state["history"], "page": token})
        else:
            batch.cursor = json.dumps({"history": data.get("historyId", state["history"])})
        batch.has_more = bool(token)
        return batch

    def update_flags(self, thread_remote_id: str, message_remote_ids: list[str], change: FlagChange) -> None:
        add, remove = [], []

        def label(name: str, present: bool) -> None:
            (add if present else remove).append(name)

        if change.is_read is not None:
            label("UNREAD", not change.is_read)
        if change.is_starred is not None:
            label("STARRED", change.is_starred)
        if change.is_archived is not None:
            label("INBOX", not change.is_archived)
        if add or remove:
            self.api.request("POST", f"{API}/threads/{thread_remote_id}/modify", json={"addLabelIds": add, "removeLabelIds": remove})

    def trash(self, message_remote_ids: list[str]) -> None:
        for message_id in message_remote_ids:
            self.api.request("POST", f"{API}/messages/{message_id}/trash")  # 404 (already gone) is fine

    def send(self, message: OutgoingMessage) -> None:
        raw = base64.urlsafe_b64encode(build_message(message).as_bytes()).decode()
        body = {"raw": raw}
        if message.reply_to:
            body["threadId"] = message.reply_to.thread_remote_id
        self.api.request("POST", f"{API}/messages/send", json=body)
        return None  # the next sync picks it up from history

    def fetch_attachment(self, message_remote_id: str, ref: str) -> bytes:
        res = self._get(f"/messages/{message_remote_id}", format="full")
        part = _find_part(res.json().get("payload", {}), ref) if res.status_code == 200 else None
        if part is None:
            raise ProviderError("That attachment no longer exists in Gmail")
        body = part.get("body", {})
        if body.get("data"):
            return _b64decode(body["data"])
        res = self._get(f"/messages/{message_remote_id}/attachments/{body['attachmentId']}")
        if res.status_code == 404:
            raise ProviderError("That attachment no longer exists in Gmail")
        return _b64decode(res.json()["data"])

    def disconnect(self) -> None:
        self.api.revoke()
