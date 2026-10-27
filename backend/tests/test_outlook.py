import json
import time
from datetime import datetime, timezone

import httpx

from app.providers import Address, FlagChange, OutgoingMessage, ReplyContext
from app.providers.oauth import OAuthApp, OAuthSession
from app.providers.outlook import OutlookProvider
from tests.fakes import FakeGraph, graph_message

APP = OAuthApp("outlook", "client", "secret", "https://login.example/authorize", "https://login.microsoftonline.com/common/oauth2/v2.0/token", ("Mail.ReadWrite",))
NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)


def provider_for(fake: FakeGraph) -> OutlookProvider:
    credentials = {"access_token": "a", "refresh_token": "r", "expires_at": int(time.time()) + 3600}
    return OutlookProvider(OAuthSession(APP, credentials, httpx.Client(transport=fake.transport()), lambda _: None), now=lambda: NOW)


def run_round(provider: OutlookProvider, cursor=None):
    batches = []
    while True:
        batch = provider.fetch_changes(cursor)
        batches.append(batch)
        cursor = batch.cursor
        if not batch.has_more:
            return batches, cursor


def test_first_round_walks_every_folder_and_page():
    fake = FakeGraph()
    fake.delta["inbox"] = [
        {"value": [graph_message("i1", "c1", "F-INBOX")]},
        {"value": [graph_message("i2", "c2", "F-INBOX", read=True, flagged=True, html=False)]},
    ]
    fake.delta["archive"] = [{"value": [graph_message("a1", "c3", "F-ARCHIVE", read=True)]}]
    fake.delta["sentitems"] = [{"value": [graph_message("s1", "c1", "F-SENT", read=True, sender=("Me", "me@contoso.example"))]}]

    batches, cursor = run_round(provider_for(fake))

    messages = {m.remote_id: m for b in batches for m in b.messages}
    assert set(messages) == {"i1", "i2", "a1", "s1"}
    assert messages["i1"].is_archived is False and messages["i1"].body_html.startswith("<p>")
    assert messages["i2"].is_starred and messages["i2"].body_text == "Plain body"
    assert messages["a1"].is_archived is True
    assert messages["s1"].thread_id == "c1"  # your reply joins the conversation
    state = json.loads(cursor)
    assert state["pending"] == [] and set(state["links"]) == {"inbox", "archive", "sentitems"}
    first = next(r for r in fake.requests if r.url.path.endswith("/inbox/messages/delta"))
    assert first.url.params["$filter"] == "receivedDateTime ge 2026-09-22T00:00:00Z"
    assert 'IdType="ImmutableId"' in first.headers["Prefer"]


def test_next_round_uses_delta_links_and_resolves_removed_messages():
    fake = FakeGraph()
    _, cursor = run_round(provider_for(fake))
    fake.delta["inbox"].append({"value": [{"id": "gone", "@removed": {"reason": "deleted"}}, {"id": "moved", "@removed": {"reason": "deleted"}}]})
    fake.messages["moved"] = {"id": "moved", "isRead": True, "flag": {"flagStatus": "notFlagged"}, "parentFolderId": "F-ARCHIVE"}

    batches, _ = run_round(provider_for(fake), cursor)

    assert batches[0].deleted == ["gone"]
    assert [(f.remote_id, f.is_archived) for f in batches[0].flags] == [("moved", True)]
    assert any(str(r.url).startswith("https://delta.example/inbox/1") for r in fake.requests)


def test_expired_delta_link_restarts_that_folder():
    fake = FakeGraph()
    _, cursor = run_round(provider_for(fake))
    fake.gone_links.add("https://delta.example/inbox/")
    batches, _ = run_round(provider_for(fake), cursor)
    assert not any(b.reset for b in batches)
    assert sum(r.url.path.endswith("/inbox/messages/delta") for r in fake.requests) == 2


def test_flags_and_archive_are_written_back():
    fake = FakeGraph()
    provider = provider_for(fake)
    provider.update_flags("c1", ["i1", "i2"], FlagChange(is_read=True, is_archived=True))
    provider.update_flags("c1", ["i2"], FlagChange(is_starred=True))
    assert fake.patches == [("i1", {"isRead": True}), ("i2", {"isRead": True}), ("i2", {"flag": {"flagStatus": "flagged"}})]
    assert fake.moves == [("i1", "archive"), ("i2", "archive")]


def test_send_new_and_reply():
    fake = FakeGraph()
    provider = provider_for(fake)
    me = Address("me@contoso.example")
    provider.send(OutgoingMessage(sender=me, to=(Address("ravi@contoso.example", "Ravi"),), subject="Design doc", body_text="Draft attached"))
    provider.send(OutgoingMessage(sender=me, to=(Address("jordan@northwind.example"),), subject="Re: x", body_text="Thanks!", reply_to=ReplyContext("i1", "c1")))
    (path1, new), (path2, reply) = fake.posts
    assert path1 == "/sendMail" and new["message"]["subject"] == "Design doc" and new["saveToSentItems"] is True
    assert new["message"]["toRecipients"] == [{"emailAddress": {"address": "ravi@contoso.example", "name": "Ravi"}}]
    assert path2 == "/messages/i1/reply" and reply["comment"] == "Thanks!"


def test_identity():
    assert provider_for(FakeGraph()).identity() == Address("me@contoso.example", "Me Myself")


def test_trash_moves_to_deleted_items():
    fake = FakeGraph()
    provider_for(fake).trash(["msg-1", "msg-2"])
    assert fake.moves == [("msg-1", "deleteditems"), ("msg-2", "deleteditems")]
