import json
import time
from console.maintenance import MaintenanceRunner
from console.store import encode


def setup(admin, account):
    gid = admin.post(
        "/api/keyword-groups",
        json={"name": "AI", "keywords": ["人工智能", "AI research"]},
    ).json()["id"]
    r = admin.put(
        "/api/accounts/" + account + "/maintenance",
        json={
            "read_home": False, "group_ids": [gid],
            "pages_per_cycle": 2,
            "delay_min_seconds": 30,
            "delay_max_seconds": 90,
            "comment_pages": 2,
            "enabled": True,
        },
    )
    assert r.status_code == 200, r.text
    return gid


def data(tweet_id, cursor=None):
    entries = [
        {
            "entryId": "tweet-" + tweet_id,
            "content": {
                "itemContent": {
                    "tweet_results": {
                        "result": {
                            "__typename": "Tweet",
                            "rest_id": tweet_id,
                            "legacy": {"full_text": "Read only"},
                        }
                    }
                }
            },
        }
    ]
    if cursor:
        entries.append(
            {
                "entryId": "cursor-bottom",
                "content": {"cursorType": "Bottom", "value": cursor},
            }
        )
    return {"entries": entries}


def test_search_comments_pagination_and_random_delay_without_writes(
    admin, account, app, monkeypatch
):
    setup(admin, account)
    store = app.state.store
    runner = MaintenanceRunner(store)
    calls = []

    def search(auth, keyword, cursor=None, **kwargs):
        calls.append(("search", cursor))
        return data("42", "search-next" if not cursor else None)

    def comments(auth, tid, cursor=None):
        calls.append(("comments", cursor))
        return data("43", "comment-next" if not cursor else None)

    monkeypatch.setattr("console.maintenance.XAPI.search_work", search)
    monkeypatch.setattr("console.maintenance.XAPI.get_work_comments", comments)
    from console.xbridge import ACTIONS

    for name in ACTIONS:
        monkeypatch.setitem(
            ACTIONS,
            name,
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("maintenance must never write")
            ),
        )
    for step in range(6):
        store.run(
            "UPDATE account_maintenance SET next_run=? WHERE account_id=?",
            (time.time() - 1, account),
        )
        before = time.time()
        runner.tick()
        row = store.one(
            "SELECT * FROM account_maintenance WHERE account_id=?", (account,)
        )
        state = json.loads(row["state"])
        if state:
            assert before + 30 <= row["next_run"] <= time.time() + 90
            # A second tick does not bypass the stored random wait.
            n = len(calls)
            runner.tick()
            assert len(calls) == n
            assert (
                admin.post("/api/accounts/" + account + "/maintenance/run").status_code
                == 409
            )
        else:
            assert row["next_run"] >= before + 60 * 60 * 0.8
    assert calls == [
        ("search", None),
        ("comments", None),
        ("comments", "comment-next"),
        ("search", "search-next"),
        ("comments", None),
        ("comments", "comment-next"),
    ]
    logs = admin.get("/api/accounts/" + account + "/maintenance/logs").json()
    assert len(logs) == 6 and all(l["status"] == "ok" for l in logs)
    assert len({l["details"]["cycle_id"] for l in logs}) == 1
    assert logs[0]["details"]["delay_reason"] == "cycle_interval"
    assert all(30 <= l["details"]["delay_seconds"] <= 90 for l in logs[1:])
    assert logs[0]["details"]["cursor_in"]["present"]
    assert "comment-next" not in json.dumps(logs) and "search-next" not in json.dumps(logs)
    assert admin.get("/api/accounts/not-owned/maintenance/logs").status_code == 404
    assert admin.get("/api/jobs").json() == []


def test_no_keywords_keepalive_only_and_pause(admin, account, app, monkeypatch):
    admin.put("/api/accounts/" + account + "/maintenance", json={"read_home": False, "group_ids": []})
    calls = []
    monkeypatch.setattr(
        "console.maintenance.XAPI.get_viewer", lambda a: calls.append("viewer") or {"__typename": "User", "rest_id": "123", "legacy": {"screen_name": "test"}}
    )
    app.state.store.run("UPDATE account_maintenance SET next_run=?", (time.time() - 1,))
    MaintenanceRunner(app.state.store).tick()
    assert calls == ["viewer"]
    log = admin.get("/api/accounts/" + account + "/maintenance/logs").json()[0]
    assert log["status"] == "ok" and log["details"]["identity_verified"]
    admin.post("/api/accounts/" + account + "/maintenance/pause")
    app.state.store.run("UPDATE account_maintenance SET next_run=?", (time.time() - 1,))
    MaintenanceRunner(app.state.store).tick()
    assert calls == ["viewer"]


def test_keyword_binding_validation_and_group_deletion(admin, account, app):
    gid = setup(admin, account)
    assert admin.delete("/api/keyword-groups/" + gid).status_code == 409
    assert (
        admin.put(
            "/api/accounts/" + account + "/maintenance",
            json={"read_home": False, "group_ids": ["not-owned"]},
        ).status_code
        == 404
    )
    assert (
        admin.put(
            "/api/accounts/" + account + "/maintenance",
            json={"delay_min_seconds": 80, "delay_max_seconds": 20},
        ).status_code
        == 400
    )
    assert (
        admin.put(
            "/api/accounts/" + account + "/maintenance", json={"read_home": False, "group_ids": []}
        ).status_code
        == 200
    )
    assert admin.delete("/api/keyword-groups/" + gid).status_code == 200


def test_repeated_cursor_stops_cycle(admin, account, app, monkeypatch):
    gid = setup(admin, account)
    admin.put(
        "/api/accounts/" + account + "/maintenance",
        json={"read_home": False, "group_ids": [gid], "read_comments": False, "pages_per_cycle": 10},
    )
    monkeypatch.setattr(
        "console.maintenance.XAPI.search_work",
        lambda *a, **kw: data("42", "same-cursor"),
    )
    runner = MaintenanceRunner(app.state.store)
    for _ in range(2):
        app.state.store.run(
            "UPDATE account_maintenance SET next_run=?", (time.time() - 1,)
        )
        runner.tick()
    assert (
        json.loads(
            app.state.store.one("SELECT state FROM account_maintenance")["state"]
        )
        == {}
    )
    log = admin.get("/api/accounts/" + account + "/maintenance/logs").json()[0]
    assert log["details"]["stop_reason"] == "repeated_cursor"


def test_restart_does_not_skip_read_cooldown(admin, account, app, monkeypatch):
    setup(admin, account)
    store = app.state.store
    runner = MaintenanceRunner(store)
    store.run("UPDATE account_maintenance SET next_run=?", (time.time() - 1,))
    # Simulate a process dying after an atomic claim, before a network response.
    monkeypatch.setattr(runner, "step", lambda task: None)
    runner.tick()
    claimed = store.one("SELECT * FROM account_maintenance")
    assert claimed["running"] == 1 and claimed["next_run"] > time.time() + 90
    app.state.queue.recover()
    calls = []
    monkeypatch.setattr(runner, "step", lambda task: calls.append(task))
    runner.tick()
    assert calls == []
    assert (
        admin.post("/api/accounts/" + account + "/maintenance/run").status_code == 409
    )


def test_live_progress_http_error_and_cookie_result_are_persisted(admin, account, app, monkeypatch):
    from builder import gateway
    from requests import Response
    import base64
    setup(admin, account)
    monkeypatch.setenv("X_GATEWAY_URL", "http://gateway:8090")
    monkeypatch.setenv("X_GATEWAY_TOKEN", "internal-only")
    body = {"errors": [{"code": 353, "message": "CSRF mismatch"}], "secret": "test-auth"}

    def transport(*args, **kwargs):
        log = admin.get("/api/accounts/" + account + "/maintenance/logs").json()[0]
        assert log["status"] == "running"
        assert log["details"]["requests"][0]["status"] is None
        r = Response()
        r.status_code = 200
        r._content = json.dumps({"status": 403, "body": base64.b64encode(json.dumps(body).encode()).decode(),
                                "headers": {"Content-Type": ["application/json"], "Set-Cookie": ["ct0=rotated-private; Domain=.x.com; Path=/"]}}).encode()
        return r

    monkeypatch.setattr("requests.Session.post", transport)

    def search(auth, *args, **kwargs):
        r = gateway.request("GET", "https://x.com/i/api/graphql/example/SearchTimeline?cursor=private-cursor", proxies=auth.proxies,
                            cookies=auth.cookie, headers={"x-csrf-token": auth.ct0})
        r.raise_for_status()
        return r.json()

    monkeypatch.setattr("console.maintenance.XAPI.search_work", search)
    store = app.state.store
    store.run("UPDATE account_maintenance SET next_run=?", (time.time() - 1,))
    MaintenanceRunner(store).tick()
    log = admin.get("/api/accounts/" + account + "/maintenance/logs").json()[0]
    assert log["status"] == "error"
    req = log["details"]["requests"][0]
    assert req["status"] == 403 and req["result"]["errors"][0]["code"] == 353
    assert req["checks"]["csrf_matches_cookie"] is True
    sync = req["checks"]["cookie_sync_result"]
    assert sync["status"] == "applied" and sync["changed"] == ["ct0"]
    assert log["details"]["delay_reason"] == "error_backoff"
    for secret in ("test-auth", "rotated-private", "proxy-secret", "private-cursor"):
        assert secret not in json.dumps(log)
    assert "rotated-private" in store.decrypt(store.one("SELECT secret FROM accounts WHERE id=?", (account,))["secret"])["cookies"]


def test_partial_errors_and_cookie_no_update_are_explicit(admin, account, app, monkeypatch):
    from builder import gateway
    from requests import Response
    import base64
    setup(admin, account)
    monkeypatch.setenv("X_GATEWAY_URL", "http://gateway:8090")
    monkeypatch.setenv("X_GATEWAY_TOKEN", "internal-only")
    payload = {"data": data("42"), "errors": [{"code": 179, "message": "Not authorized to see one result"}]}

    def transport(*a, **kw):
        response = Response()
        response.status_code = 200
        response._content = json.dumps({"status": 200, "headers": {"Content-Type": ["application/json"]},
                                      "body": base64.b64encode(json.dumps(payload).encode()).decode()}).encode()
        return response

    monkeypatch.setattr("requests.Session.post", transport)
    monkeypatch.setattr("console.maintenance.XAPI.search_work", lambda auth, *a, **kw: gateway.request("GET", "https://x.com/search", proxies=auth.proxies).json())
    app.state.store.run("UPDATE account_maintenance SET next_run=?", (time.time() - 1,))
    MaintenanceRunner(app.state.store).tick()
    log = admin.get("/api/accounts/" + account + "/maintenance/logs").json()[0]
    assert log["status"] == "warning" and log["item_count"] == 1
    assert log["details"]["requests"][0]["checks"]["cookie_sync_result"]["status"] == "no_set_cookie"


def test_empty_viewer_is_not_reported_as_success(admin, account, app, monkeypatch):
    admin.put("/api/accounts/" + account + "/maintenance", json={"read_home": False, "group_ids": []})
    monkeypatch.setattr("console.maintenance.XAPI.get_viewer", lambda a: {})
    app.state.store.run("UPDATE account_maintenance SET next_run=?", (time.time() - 1,))
    MaintenanceRunner(app.state.store).tick()
    log = admin.get("/api/accounts/" + account + "/maintenance/logs").json()[0]
    assert log["status"] == "error" and "identity_verified" not in log["details"]


def test_old_logs_survive_schema_upgrade_and_running_logs_recover(admin, account, app):
    from console.store import Store
    s = app.state.store
    s.run("INSERT INTO maintenance_logs(account_id,keyword,operation,page,item_count,status,message,created) VALUES(?,'','viewer',1,0,'running','legacy',?)", (account, time.time()))
    s.run("ALTER TABLE maintenance_logs DROP COLUMN details")
    upgraded = Store(s.directory)
    assert json.loads(upgraded.one("SELECT details FROM maintenance_logs")["details"]) == {}
    app.state.queue.recover()
    row = upgraded.one("SELECT * FROM maintenance_logs")
    assert row["status"] == "interrupted" and json.loads(row["details"])["interrupted"]


def test_home_then_search_with_comment_pages_and_shared_delay(admin, account, app, monkeypatch):
    gid = setup(admin, account)
    assert admin.put(f"/api/accounts/{account}/maintenance", json={
        "group_ids": [gid], "read_home": True, "home_pages_per_cycle": 2,
        "pages_per_cycle": 1, "comment_pages": 1,
    }).status_code == 200
    calls = []
    def home(auth, cursor=None, count=20):
        calls.append(("home", cursor))
        return data("10", "home-next" if not cursor else None)
    def search(auth, keyword, cursor=None, **kw):
        calls.append(("search", cursor))
        return data("20")
    def comments(auth, tid, cursor=None):
        calls.append(("comments", tid))
        return data("30")
    monkeypatch.setattr("console.maintenance.XAPI.get_home_timeline", home)
    monkeypatch.setattr("console.maintenance.XAPI.search_work", search)
    monkeypatch.setattr("console.maintenance.XAPI.get_work_comments", comments)
    runner = MaintenanceRunner(app.state.store)
    for _ in range(6):
        app.state.store.run("UPDATE account_maintenance SET next_run=?", (time.time() - 1,))
        runner.tick()
    assert calls == [("home", None), ("comments", "10"), ("home", "home-next"),
                     ("comments", "10"), ("search", None), ("comments", "20")]
    logs = admin.get(f"/api/accounts/{account}/maintenance/logs").json()
    assert len({r["details"]["cycle_id"] for r in logs}) == 1
    assert all(r["status"] == "ok" for r in logs)
    assert all(30 <= r["details"]["delay_seconds"] <= 90 for r in logs[1:])
    assert logs[0]["details"]["cycle_complete"]
    assert logs[-1]["operation"] == "home" and logs[-1]["keyword"] == ""
    assert logs[-2]["details"]["source"] == "home"
    assert admin.get("/api/jobs").json() == []


def test_home_only_default_without_keywords(admin, account, app, monkeypatch):
    admin.put(f"/api/accounts/{account}/maintenance", json={"home_pages_per_cycle": 1, "read_comments": False})
    calls = []
    monkeypatch.setattr("console.maintenance.XAPI.get_home_timeline", lambda *a, **kw: calls.append(kw["cursor"]) or data("10"))
    monkeypatch.setattr("console.maintenance.XAPI.get_viewer", lambda *a: (_ for _ in ()).throw(AssertionError("home is enabled")))
    app.state.store.run("UPDATE account_maintenance SET next_run=?", (time.time() - 1,))
    MaintenanceRunner(app.state.store).tick()
    log = admin.get(f"/api/accounts/{account}/maintenance/logs").json()[0]
    assert calls == [None] and log["operation"] == "home" and log["status"] == "ok"
    assert log["details"]["cycle_complete"]


def test_repeated_home_cursor_advances_to_search(admin, account, app, monkeypatch):
    gid = setup(admin, account)
    admin.put(f"/api/accounts/{account}/maintenance", json={"group_ids": [gid], "read_home": True, "home_pages_per_cycle": 10, "pages_per_cycle": 1, "read_comments": False})
    monkeypatch.setattr("console.maintenance.XAPI.get_home_timeline", lambda *a, **kw: data("10", "same-home-cursor"))
    calls = []
    monkeypatch.setattr("console.maintenance.XAPI.search_work", lambda *a, **kw: calls.append(kw["cursor"]) or data("20"))
    runner = MaintenanceRunner(app.state.store)
    for _ in range(3):
        app.state.store.run("UPDATE account_maintenance SET next_run=?", (time.time() - 1,))
        runner.tick()
    logs = admin.get(f"/api/accounts/{account}/maintenance/logs").json()
    assert logs[1]["details"]["stop_reason"] == "repeated_cursor"
    assert logs[1]["details"]["next_operation"] == "search"
    assert calls == [None] and logs[0]["details"]["cycle_complete"]


def test_upgrade_preserves_inflight_search_and_adds_home_next_cycle(admin, account, app, monkeypatch):
    from console.store import Store
    gid = setup(admin, account)
    s = app.state.store
    legacy = {"keyword": "AI", "phase": "comments", "search_page": 2,
              "search_cursor": "search-next", "search_done": True,
              "tweet_id": "42", "comment_page": 0, "comment_cursor": None, "cycle_id": "old-cycle"}
    s.run("UPDATE account_maintenance SET state=?", (encode(legacy),))
    s.run("ALTER TABLE account_maintenance DROP COLUMN read_home, DROP COLUMN home_pages_per_cycle")
    upgraded = Store(s.directory)
    row = upgraded.one("SELECT * FROM account_maintenance")
    assert row["read_home"] == 1 and row["home_pages_per_cycle"] == 2
    assert json.loads(row["state"]) == legacy
    calls = []
    monkeypatch.setattr("console.maintenance.XAPI.get_work_comments", lambda *a, **kw: calls.append("comments") or data("43"))
    monkeypatch.setattr("console.maintenance.XAPI.get_home_timeline", lambda *a, **kw: calls.append("home") or data("10"))
    for _ in range(2):
        s.run("UPDATE account_maintenance SET next_run=?", (time.time() - 1,))
        MaintenanceRunner(upgraded).tick()
    assert calls == ["comments", "home"]
