"""Outlook adapter, using Microsoft Graph delta queries.

Graph tracks changes per folder, so the adapter follows three: Inbox, Archive and Sent
Items. Each has a delta link (the folder's cursor); one sync round walks every folder's
pages until it reaches a fresh delta link. The first round only asks for the last
SYNC_BACKFILL_DAYS of mail.

Archiving in Outlook means moving the message to the Archive folder. Immutable ids keep a
message's id stable across moves, so the hub can follow it. A message that disappears from
a folder's delta was either moved or deleted; the adapter asks Graph which one.
"""

import json
from datetime import datetime, timedelta, timezone

from .base import Address, FlagChange, MailProvider, OutgoingMessage, RemoteFlags, RemoteMessage, SyncBatch
from .oauth import OAuthSession

API = "https://graph.microsoft.com/v1.0/me"
FOLDERS = ("inbox", "archive", "sentitems")
FIELDS = (
    "id,conversationId,subject,from,toRecipients,ccRecipients,receivedDateTime,sentDateTime,"
    "isRead,isDraft,flag,body,parentFolderId,internetMessageId"
)
HEADERS = {"Prefer": 'IdType="ImmutableId", odata.maxpagesize=50'}


def _address(item: dict | None) -> Address:
    email = (item or {}).get("emailAddress") or {}
    return Address(email.get("address", ""), email.get("name", ""))


def _time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _recipients(addresses: tuple[Address, ...]) -> list[dict]:
    return [{"emailAddress": {"address": a.email, **({"name": a.name} if a.name else {})}} for a in addresses]


class OutlookProvider(MailProvider):
    def __init__(self, session: OAuthSession, backfill_days: int = 30, now=None) -> None:
        self.api = session
        self.backfill_days = backfill_days
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _call(self, method: str, url: str, **kwargs):
        # 410 Gone: an expired delta link, handled by restarting that folder.
        return self.api.request(method, url if url.startswith("http") else f"{API}{url}", headers=HEADERS, allow=(404, 410), **kwargs)

    def identity(self) -> Address:
        me = self._call("GET", "", params={"$select": "mail,userPrincipalName,displayName"}).json()
        return Address(me.get("mail") or me["userPrincipalName"], me.get("displayName", ""))

    def _folder_ids(self) -> dict[str, str]:
        ids = {}
        for name in FOLDERS:
            res = self._call("GET", f"/mailFolders/{name}", params={"$select": "id"})
            if res.status_code != 404:  # some accounts have no Archive folder
                ids[name] = res.json()["id"]
        return ids

    def _convert(self, item: dict, folder: str) -> RemoteMessage:
        body = item.get("body") or {}
        html = body.get("contentType") == "html"
        return RemoteMessage(
            remote_id=item["id"],
            thread_id=item.get("conversationId") or item["id"],
            sender=_address(item.get("from")),
            to=tuple(_address(r) for r in item.get("toRecipients", [])),
            cc=tuple(_address(r) for r in item.get("ccRecipients", [])),
            subject=(item.get("subject") or "").strip(),
            sent_at=_time(item.get("sentDateTime") if folder == "sentitems" else item.get("receivedDateTime")),
            body_text="" if html else body.get("content", ""),
            body_html=body.get("content", "") if html else "",
            is_read=bool(item.get("isRead")),
            is_starred=(item.get("flag") or {}).get("flagStatus") == "flagged",
            is_archived=folder != "inbox",
            message_id_header=item.get("internetMessageId") or "",
        )

    def fetch_changes(self, cursor: str | None) -> SyncBatch:
        state = json.loads(cursor) if cursor else {}
        ids = state.get("ids") or self._folder_ids()
        links: dict[str, str] = state.get("links", {})
        # Folders still to walk in this round; a new round starts with all of them.
        pending = state.get("pending") or [f for f in FOLDERS if f in ids]
        folder = pending[0]

        url = links.get(folder)
        if url:
            res = self._call("GET", url)
            if res.status_code in (404, 410):  # delta link expired: walk this folder again
                url = None
        if not url:
            since = (self._now() - timedelta(days=self.backfill_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
            res = self._call(
                "GET",
                f"/mailFolders/{folder}/messages/delta",
                params={"$select": FIELDS, "$filter": f"receivedDateTime ge {since}"},
            )
        page = res.json()

        batch = SyncBatch()
        removed = []
        for item in page.get("value", []):
            if "@removed" in item:
                removed.append(item["id"])
            elif not item.get("isDraft"):
                batch.messages.append(self._convert(item, folder))
        self._resolve_removed(removed, ids, batch)

        if "@odata.nextLink" in page:
            links[folder] = page["@odata.nextLink"]
        else:
            links[folder] = page.get("@odata.deltaLink", links.get(folder))
            pending = pending[1:]
        batch.cursor = json.dumps({"ids": ids, "links": links, "pending": pending})
        batch.has_more = bool(pending)
        return batch

    def _resolve_removed(self, removed: list[str], ids: dict[str, str], batch: SyncBatch) -> None:
        """A message left a folder: if it still exists it was moved, so update where it lives."""
        names = {folder_id: name for name, folder_id in ids.items()}
        for message_id in removed:
            res = self._call("GET", f"/messages/{message_id}", params={"$select": "id,isRead,flag,parentFolderId"})
            if res.status_code == 404:
                batch.deleted.append(message_id)
                continue
            item = res.json()
            folder = names.get(item.get("parentFolderId"))
            if folder is None and item.get("parentFolderId"):
                # Moved somewhere the hub doesn't follow (e.g. Deleted Items or a custom folder).
                batch.deleted.append(message_id)
                continue
            batch.flags.append(
                RemoteFlags(
                    remote_id=message_id,
                    is_read=bool(item.get("isRead")),
                    is_starred=(item.get("flag") or {}).get("flagStatus") == "flagged",
                    is_archived=folder != "inbox",
                )
            )

    def update_flags(self, thread_remote_id: str, message_remote_ids: list[str], change: FlagChange) -> None:
        patch = {}
        if change.is_read is not None:
            patch["isRead"] = change.is_read
        if change.is_starred is not None:
            patch["flag"] = {"flagStatus": "flagged" if change.is_starred else "notFlagged"}
        for message_id in message_remote_ids:
            if patch:
                self._call("PATCH", f"/messages/{message_id}", json=patch)
            if change.is_archived is not None:
                destination = "archive" if change.is_archived else "inbox"
                self._call("POST", f"/messages/{message_id}/move", json={"destinationId": destination})

    def send(self, message: OutgoingMessage) -> None:
        recipients = {"toRecipients": _recipients(message.to), "ccRecipients": _recipients(message.cc)}
        if message.reply_to:
            # Graph threads the reply and sets In-Reply-To/References itself.
            self._call("POST", f"/messages/{message.reply_to.remote_id}/reply", json={"message": recipients, "comment": message.body_text})
        else:
            payload = {"subject": message.subject, "body": {"contentType": "Text", "content": message.body_text}, **recipients}
            self._call("POST", "/sendMail", json={"message": payload, "saveToSentItems": True})
        return None  # it appears in Sent Items, which the next sync reads
