from tests.conftest import register


def inbox(client, headers, **params):
    res = client.get("/api/threads", headers=headers, params=params)
    assert res.status_code == 200, res.text
    return res.json()


def all_pages(client, headers, **params):
    threads, cursor = [], None
    while True:
        page = inbox(client, headers, **params, **({"cursor": cursor} if cursor else {}))
        threads += page["threads"]
        cursor = page["next_cursor"]
        if not cursor:
            return threads


def test_unified_inbox_mixes_accounts_newest_first(client, demo):
    threads = inbox(client, demo, limit=30)["threads"]
    assert len({t["account_id"] for t in threads}) == 3
    dates = [t["last_message_at"] for t in threads]
    assert dates == sorted(dates, reverse=True)
    assert not any(t["is_archived"] for t in threads)


def test_pagination_covers_every_thread_exactly_once(client, demo):
    paged = all_pages(client, demo, folder="all", limit=7)
    everything = inbox(client, demo, folder="all", limit=100)
    ids = [t["id"] for t in paged]
    assert len(ids) == len(set(ids))
    assert len(ids) > 100
    assert ids[:100] == [t["id"] for t in everything["threads"]]


def test_folders_and_account_filter(client, demo):
    accounts = client.get("/api/accounts", headers=demo).json()
    work = next(a for a in accounts if a["brand"] == "outlook")

    unread = all_pages(client, demo, folder="unread")
    assert unread and all(t["unread_count"] > 0 and not t["is_archived"] for t in unread)
    assert all(t["is_starred"] for t in all_pages(client, demo, folder="starred"))
    assert all(t["is_archived"] for t in all_pages(client, demo, folder="archive"))
    work_threads = all_pages(client, demo, account_id=work["id"])
    assert work_threads and all(t["account_id"] == work["id"] for t in work_threads)
    assert len([t for t in unread if t["account_id"] == work["id"]]) == work["unread_count"]


def test_search_matches_subject_body_and_sender(client, demo):
    assert any("Weekend trip" in t["subject"] for t in inbox(client, demo, q="homestay")["threads"])  # body text
    assert all("Zestro" in t["participants"] for t in all_pages(client, demo, folder="all", q="from:zestro.example"))
    assert inbox(client, demo, q="roadmap Q4")["threads"][0]["subject"] == "Q4 roadmap review"
    assert inbox(client, demo, q="zq_%x")["threads"] == []  # % and _ are not wildcards


def test_open_thread_and_change_flags(client, demo):
    thread = next(t for t in inbox(client, demo, folder="unread")["threads"] if t["message_count"] > 1)
    detail = client.get(f"/api/threads/{thread['id']}", headers=demo).json()
    assert len(detail["messages"]) == thread["message_count"]
    assert detail["messages"][0]["sent_at"] <= detail["messages"][-1]["sent_at"]

    res = client.patch(f"/api/threads/{thread['id']}", headers=demo, json={"is_read": True, "is_starred": True})
    assert res.json()["unread_count"] == 0 and res.json()["is_starred"] is True
    assert thread["id"] not in [t["id"] for t in all_pages(client, demo, folder="unread")]
    assert thread["id"] in [t["id"] for t in all_pages(client, demo, folder="starred")]

    client.patch(f"/api/threads/{thread['id']}", headers=demo, json={"is_archived": True})
    assert thread["id"] not in [t["id"] for t in all_pages(client, demo)]
    assert thread["id"] in [t["id"] for t in all_pages(client, demo, folder="archive")]

    res = client.patch(f"/api/threads/{thread['id']}", headers=demo, json={"is_read": False, "is_starred": False, "is_archived": False})
    body = res.json()
    assert body["unread_count"] == body["message_count"] and not body["is_starred"] and not body["is_archived"]


def test_users_cannot_see_each_others_mail(client, demo):
    thread = inbox(client, demo)["threads"][0]
    other = register(client, "mallory", "secret123")
    assert inbox(client, other)["threads"] == []
    assert client.get(f"/api/threads/{thread['id']}", headers=other).status_code == 404
    assert client.patch(f"/api/threads/{thread['id']}", headers=other, json={"is_read": True}).status_code == 404
    account_id = thread["account_id"]
    assert client.delete(f"/api/accounts/{account_id}", headers=other).status_code == 404


def test_bad_cursor_is_rejected(client, demo):
    assert client.get("/api/threads", headers=demo, params={"cursor": "not-a-cursor"}).status_code == 400


def test_registered_user_can_add_sample_mailboxes_once(client, auth):
    assert client.get("/api/accounts", headers=auth).json() == []
    assert len(client.post("/api/accounts/demo", headers=auth).json()) == 3
    assert len(client.post("/api/accounts/demo", headers=auth).json()) == 3
    assert inbox(client, auth)["threads"]


def test_sync_is_incremental(client, demo):
    results = client.post("/api/sync", headers=demo).json()
    assert len(results) == 3
    assert all(r["new_messages"] == 0 and r["error"] is None for r in results)


def test_disconnect_removes_the_accounts_mail(client, demo):
    accounts = client.get("/api/accounts", headers=demo).json()
    old = next(a for a in accounts if a["brand"] == "imap")
    assert client.delete(f"/api/accounts/{old['id']}", headers=demo).status_code == 204
    assert [a["brand"] for a in client.get("/api/accounts", headers=demo).json()] == ["gmail", "outlook"]
    assert all(t["account_id"] != old["id"] for t in all_pages(client, demo, folder="all"))
