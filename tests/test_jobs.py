import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from console.jobs import Queue
from x_apis.errors import GraphQLError
from tests_helpers import make_job


def result(tweet_id):
    return {
        "data": {"create_tweet": {"tweet_results": {"result": {"rest_id": tweet_id}}}}
    }


def test_idempotency_and_scheduled_claim(admin, account, app, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "console.jobs.XWriteAPI.create_tweet",
        lambda *a, **kw: calls.append(a) or result("42"),
    )
    request_id = str(uuid.uuid4())
    future = time.time() + 3600
    one = make_job(admin, account, request_id=request_id, scheduled=future)
    two = make_job(admin, account, request_id=request_id, scheduled=future)
    assert one["id"] == two["id"] and two["duplicate"]
    app.state.queue.tick()
    assert not calls
    app.state.store.run("UPDATE jobs SET scheduled=?", (time.time() - 1,))
    app.state.queue.tick()
    app.state.queue.tick()
    assert len(calls) == 1
    job = admin.get("/api/jobs").json()[0]
    assert job["state"] == "sent" and job["result"]["tweet_ids"] == ["42"]


def test_cancel_and_edit_are_state_guarded(admin, account, app):
    j = make_job(admin, account)
    assert admin.post("/api/jobs/" + j["id"] + "/cancel").status_code == 200
    assert admin.get("/api/jobs").json()[0]["state"] == "draft"
    app.state.store.run("UPDATE jobs SET state='sending' WHERE id=?", (j["id"],))
    assert admin.post("/api/jobs/" + j["id"] + "/cancel").status_code == 409
    assert admin.delete("/api/jobs/" + j["id"]).status_code == 409
    assert admin.delete("/api/accounts/" + account).status_code == 409
    assert (
        admin.put(
            "/api/accounts/" + account + "/proxy", json={"proxy": "http://new:8080"}
        ).status_code
        == 409
    )


def test_thread_partial_result_and_no_retry(admin, account, app, monkeypatch):
    calls = []

    def send(auth, text, **kw):
        calls.append((text, kw.get("reply_to")))
        if len(calls) == 2:
            raise TimeoutError("proxy-password-must-not-leak")
        return result("101")

    monkeypatch.setattr("console.jobs.XWriteAPI.create_tweet", send)
    make_job(
        admin,
        account,
        payload={"kind": "thread", "text": "", "texts": ["first", "second", "third"]},
    )
    app.state.queue.tick()
    app.state.queue.tick()
    j = admin.get("/api/jobs").json()[0]
    assert calls == [("first", None), ("second", "101")]
    assert j["state"] == "uncertain" and j["result"]["tweet_ids"] == ["101"]
    assert "proxy-password" not in j["error"]


def test_explicit_graphql_rejection_is_failed(admin, account, app, monkeypatch):
    def send(*a, **kw):
        raise GraphQLError(
            "CreateTweet", [{"code": 187, "message": "Duplicate secret data"}]
        )

    monkeypatch.setattr("console.jobs.XWriteAPI.create_tweet", send)
    make_job(admin, account)
    app.state.queue.tick()
    job = admin.get("/api/jobs").json()[0]
    assert job["state"] == "failed" and "重复" in job["error"]
    assert "secret data" not in job["error"]


def test_worker_claim_is_atomic(admin, account, app, monkeypatch):
    calls = []

    def send(*a, **k):
        calls.append(1)
        time.sleep(0.1)
        return result("42")

    monkeypatch.setattr("console.jobs.XWriteAPI.create_tweet", send)
    make_job(admin, account)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: Queue(app.state.store).tick(), range(2)))
    assert len(calls) == 1


def test_crash_recovery_marks_uncertain(admin, account, app):
    j = make_job(admin, account)
    app.state.store.run(
        "UPDATE jobs SET state='sending',result=? WHERE id=?",
        (json.dumps({"tweet_ids": ["known"]}), j["id"]),
    )
    q = Queue(app.state.store)
    q.start()
    q.close()
    job = admin.get("/api/jobs").json()[0]
    assert job["state"] == "uncertain" and job["result"]["tweet_ids"] == ["known"]


def test_content_limits_and_media_ownership(admin, account):
    body = {
        "account_id": account,
        "request_id": str(uuid.uuid4()),
        "state": "queued",
        "payload": {"text": "中" * 141},
    }
    assert admin.post("/api/jobs", json=body).status_code == 400
    body["payload"]["long"] = True
    assert admin.post("/api/jobs", json=body).status_code == 200
    body["request_id"] = str(uuid.uuid4())
    body["payload"] = {"text": "hello", "media": ["someone-elses-media"]}
    assert admin.post("/api/jobs", json=body).status_code == 400


def test_article_no_local_file_access_and_publish_modes(
    admin, account, app, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        "console.jobs.XArticleAPI.create_draft",
        lambda *a, **k: calls.append("create") or {},
    )
    make_job(
        admin,
        account,
        payload={"kind": "article", "text": "![](/etc/passwd)", "title": "Article"},
    )
    app.state.queue.tick()
    assert calls == []
    assert admin.get("/api/jobs").json()[0]["state"] == "failed"
    monkeypatch.setattr("console.jobs.XArticleAPI.extract_article_id", lambda _: "1234")
    monkeypatch.setattr(
        "console.jobs.XArticleAPI.update_title", lambda *a: calls.append("title")
    )
    monkeypatch.setattr(
        "console.jobs.XArticleAPI.update_content", lambda *a: calls.append("content")
    )
    monkeypatch.setattr(
        "console.jobs.XArticleAPI.publish",
        lambda *a, **k: calls.append(k["reply_mode"]) or {},
    )
    monkeypatch.setattr("console.jobs.XArticleAPI.extract_tweet_id", lambda _: "5678")
    make_job(
        admin,
        account,
        payload={
            "kind": "article",
            "text": "正文",
            "title": "Article",
            "publish_article": True,
            "reply_mode": "Community",
        },
    )
    app.state.queue.tick()
    assert calls == ["create", "title", "content", "Community"]
    j = admin.get("/api/jobs").json()[0]
    assert (
        j["state"] == "sent"
        and j["result"]["article_id"] == "1234"
        and j["result"]["tweet_ids"] == ["5678"]
    )


def test_expired_x_session_pauses_pending_work(admin, account, app, monkeypatch):
    def send(*a, **kw):
        raise GraphQLError("CreateTweet", [{"code": 32, "message": "expired"}])

    monkeypatch.setattr("console.jobs.XWriteAPI.create_tweet", send)
    make_job(admin, account)
    make_job(admin, account)
    app.state.queue.tick()
    assert admin.get("/api/accounts").json()[0]["status"] == "expired"
    assert sorted(j["state"] for j in admin.get("/api/jobs").json()) == [
        "draft",
        "failed",
    ]


def test_queue_waits_while_account_is_reauthenticating(
    admin, account, app, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        "console.jobs.XWriteAPI.create_tweet",
        lambda *a, **k: calls.append(1) or result("42"),
    )
    make_job(admin, account)
    app.state.store.run(
        "UPDATE accounts SET status='logging_in' WHERE id=?", (account,)
    )
    app.state.queue.tick()
    assert calls == [] and admin.get("/api/jobs").json()[0]["state"] == "queued"
    app.state.store.run("UPDATE accounts SET status='connected' WHERE id=?", (account,))
    app.state.queue.tick()
    assert calls == [1]
