import time

from console import xbridge


def tweet(tid, parent=None, conversation=None):
    return {"__typename": "Tweet", "rest_id": tid, "legacy": {
        "full_text": "post " + tid, "in_reply_to_status_id_str": parent,
        "conversation_id_str": conversation or tid,
    }}


def thread():
    return {"data": {"entries": [
        tweet("10"), tweet("42", "10", "10"), tweet("43", "42", "10"),
        tweet("44", "43", "10"), tweet("99"), tweet("100", "99", "99"),
        {"entryId": "cursor-bottom-0", "content": {"cursorType": "Bottom", "value": "next-comments"}},
    ]}}


def test_detail_separates_ancestors_focal_and_replies():
    result = xbridge.discussion(thread(), "42")
    assert result["post"]["work_id"] == "42"
    assert [p["work_id"] for p in result["context"]] == ["10"]
    assert [p["work_id"] for p in result["replies"]] == ["43", "44"]
    assert result["cursor"] == "next-comments"


def test_comment_page_without_focal_still_returns_replies():
    result = xbridge.discussion({"data": [tweet("45", "42", "42")]}, "42")
    assert result["post"] is None and result["context"] == []
    assert result["replies"][0]["work_id"] == "45"


def test_detail_read_during_warmup_and_pagination(admin, account, app, monkeypatch):
    app.state.store.run("UPDATE account_policies SET warmup_until=?", (time.time() + 86400,))
    calls = []

    def read(auth, post_id, cursor=None):
        calls.append((post_id, cursor, auth.proxies["_account"]))
        return thread()

    monkeypatch.setattr("console.app.XAPI.get_work_info", read)
    response = admin.get(f"/api/accounts/{account}/posts/42", params={"cursor": "comments-page-2"})
    assert response.status_code == 200
    assert response.json()["post"]["work_id"] == "42"
    assert calls == [("42", "comments-page-2", account)]
    assert admin.get(f"/api/accounts/{account}/posts/not-a-post").status_code == 400
    assert admin.get("/api/accounts/not-owned/posts/42").status_code == 404
    assert admin.get("/api/jobs").json() == []
