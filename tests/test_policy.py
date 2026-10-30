from concurrent.futures import ThreadPoolExecutor
import time
import uuid
import pytest
from console import policy
from tests_helpers import make_job


def age(app, account, days):
    row = app.state.store.one("SELECT * FROM accounts WHERE id=?", (account,))
    first = time.time() - days * 86400
    app.state.store.run(
        "UPDATE account_policies SET first_login=?,warmup_until=?,limit_until=? WHERE id=?",
        (first, first + 4 * 86400, first + 7 * 86400, row["policy_id"]),
    )
    return app.state.store.one("SELECT * FROM accounts WHERE id=?", (account,))


def test_first_four_days_all_x_writes_blocked_but_reads_and_drafts_allowed(
    admin, account, app, monkeypatch
):
    age(app, account, 1)
    from console.xbridge import ACTIONS, READS

    for action in ACTIONS:
        r = admin.post(
            "/api/accounts/" + account + "/action",
            json={"action": action, "target": "42"},
        )
        assert r.status_code == 423, (action, r.text)
    assert (
        admin.post(
            "/api/accounts/" + account + "/media",
            files={"file": ("photo.png", b"image")},
        ).status_code
        == 423
    )
    for action in ["publish", "delete"]:
        assert (
            admin.post(
                "/api/accounts/" + account + "/article-action",
                json={"action": action, "article_id": "123"},
            ).status_code
            == 423
        )
    body = {
        "account_id": account,
        "request_id": str(uuid.uuid4()),
        "payload": {"text": "blocked"},
        "state": "queued",
    }
    assert admin.post("/api/jobs", json=body).status_code == 423
    body["state"] = "draft"
    assert admin.post("/api/jobs", json=body).status_code == 200
    monkeypatch.setattr("console.app.XAPI.search_work", lambda *a, **kw: {})
    assert (
        admin.get(
            "/api/accounts/" + account + "/timeline",
            params={"kind": "search", "q": "AI", "cursor": "next"},
        ).status_code
        == 200
    )
    fn, fields, label = READS["viewer"]
    monkeypatch.setitem(READS, "viewer", (lambda a: {}, fields, label))
    assert (
        admin.post(
            "/api/accounts/" + account + "/explore",
            json={"operation": "viewer", "params": {}},
        ).status_code
        == 200
    )


def test_exact_age_boundaries(admin, account, app):
    a = age(app, account, 1)
    store = app.state.store
    p = store.one("SELECT * FROM account_policies WHERE id=?", (a["policy_id"],))
    assert policy.status(store, a, p["warmup_until"] - 0.001)["stage"] == "warming"
    assert policy.status(store, a, p["warmup_until"])["stage"] == "limited"
    assert policy.status(store, a, p["limit_until"] - 0.001)["daily_limit"] == 2
    assert policy.status(store, a, p["limit_until"])["daily_limit"] is None


def test_daily_two_atomic_across_concurrent_publishers(admin, account, app):
    a = age(app, account, 5)

    def reserve(i):
        try:
            policy.reserve(app.state.store, a, "request-" + str(i), 1)
            return "ok"
        except policy.PolicyWait:
            return "limited"

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(reserve, range(3)))
    assert results.count("ok") == 2 and results.count("limited") == 1
    assert policy.status(app.state.store, a)["remaining"] == 0


def test_day_reset_and_release_after_seven_days(admin, account, app):
    a = age(app, account, 5)
    now = time.time()
    policy.reserve(app.state.store, a, "first", 2, now)
    with pytest.raises(policy.PolicyWait):
        policy.reserve(app.state.store, a, "third", 1, now)
    _, tomorrow = policy.day_bounds(now)
    policy.reserve(app.state.store, a, "next-day", 2, tomorrow + 0.001)
    p = app.state.store.one(
        "SELECT * FROM account_policies WHERE id=?", (a["policy_id"],)
    )
    policy.reserve(app.state.store, a, "mature", 10, p["limit_until"] + 0.001)
    assert policy.day_bounds(1792774800)[0].isoformat() == "2026-10-24"


def test_failed_post_releases_slot_but_ambiguous_attempt_counts(admin, account, app):
    a = age(app, account, 5)
    policy.reserve(app.state.store, a, "thread", 2)
    policy.confirm(app.state.store, "thread", 1)
    policy.finish(app.state.store, "thread", 1, uncertain=True)
    assert policy.status(app.state.store, a)["remaining"] == 0
    app.state.store.run("DELETE FROM publication_ledger")
    policy.reserve(app.state.store, a, "failed", 1)
    policy.finish(app.state.store, "failed", 0)
    assert policy.status(app.state.store, a)["remaining"] == 2


def test_queue_defers_third_post_and_three_part_thread(
    admin, account, app, monkeypatch
):
    a = age(app, account, 5)
    calls = []

    def send(*args, **kwargs):
        calls.append(1)
        return {
            "data": {
                "create_tweet": {
                    "tweet_results": {"result": {"rest_id": str(len(calls))}}
                }
            }
        }

    monkeypatch.setattr("console.jobs.XWriteAPI.create_tweet", send)
    for _ in range(3):
        make_job(admin, account)
    for _ in range(3):
        app.state.queue.tick()
    rows = admin.get("/api/jobs").json()
    assert len(calls) == 2 and sorted(r["state"] for r in rows) == [
        "queued",
        "sent",
        "sent",
    ]
    deferred = next(r for r in rows if r["state"] == "queued")
    assert deferred["scheduled"] > time.time()
    assert policy.status(app.state.store, a)["today_used"] == 2
    make_job(
        admin, account, payload={"kind": "thread", "texts": ["one", "two", "three"]}
    )
    app.state.queue.tick()
    assert len(calls) == 2
    thread = admin.get("/api/jobs").json()[0]
    assert thread["scheduled"] == policy.status(app.state.store, a)["limit_until"]


def test_readding_same_x_account_preserves_age_and_ledger(
    admin, account, app, monkeypatch
):
    a = age(app, account, 5)
    old = policy.status(app.state.store, a)
    policy.reserve(app.state.store, a, "already-posted", 2)
    assert admin.delete("/api/accounts/" + account).status_code == 200
    aid = admin.post(
        "/api/accounts", json={"name": "Again", "proxy": "http://proxy.example:8080"}
    ).json()["id"]
    monkeypatch.setattr(
        "console.app.XAPI.get_viewer",
        lambda *a: {
            "__typename": "User",
            "rest_id": "123",
            "core": {"screen_name": "test", "name": "Test"},
        },
    )
    r = admin.post(
        "/api/accounts/" + aid + "/login", json={"cookies": "auth_token=a; ct0=b"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["policy"]["first_login"] == old["first_login"]
    assert r.json()["policy"]["today_used"] == 2


def test_same_physical_account_shares_limit_across_console_users(
    admin, account, app, monkeypatch
):
    from fastapi.testclient import TestClient

    a = age(app, account, 5)
    policy.reserve(app.state.store, a, "two-posts", 2)
    assert (
        admin.post(
            "/api/users",
            json={
                "username": "another",
                "password": "Another-password-2026",
                "role": "member",
            },
        ).status_code
        == 200
    )
    monkeypatch.setattr(
        "console.app.XAPI.get_viewer",
        lambda *a: {
            "__typename": "User",
            "rest_id": "123",
            "core": {"screen_name": "test", "name": "Test"},
        },
    )
    with TestClient(app) as other:
        other.headers["X-Requested-With"] = "XApis"
        auth = other.post(
            "/api/auth/login",
            json={"username": "another", "password": "Another-password-2026"},
        ).json()
        other.headers["X-CSRF-Token"] = auth["csrf"]
        aid = other.post(
            "/api/accounts", json={"name": "Same X", "proxy": "http://proxy:8080"}
        ).json()["id"]
        r = other.post(
            "/api/accounts/" + aid + "/login", json={"cookies": "auth_token=a; ct0=b"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["policy"]["remaining"] == 0
        assert (
            r.json()["policy"]["first_login"]
            == policy.status(app.state.store, a)["first_login"]
        )
        assert len(other.get("/api/accounts").json()) == 1
