import io
import json
import time
import pytest
from console import xbridge
from tests_helpers import make_job


def test_all_interaction_routes_dispatch(admin, account, monkeypatch):
    called = []
    for name in xbridge.ACTIONS:
        monkeypatch.setitem(
            xbridge.ACTIONS,
            name,
            lambda auth, target, n=name: (
                called.append((n, target, auth.proxies["_account"])) or {}
            ),
        )
        assert (
            admin.post(
                "/api/accounts/" + account + "/action",
                json={"action": name, "target": "42"},
            ).status_code
            == 200
        )
    assert len(called) == len(xbridge.ACTIONS)
    assert all(a[1] == "42" and a[2] == account for a in called)


@pytest.mark.parametrize(
    "kind,method,params",
    [
        ("home", "get_home_timeline", {}),
        ("mine", "get_user_post_note", {}),
        ("search", "search_work", {"q": "AI"}),
        ("detail", "get_work_info", {"q": "42"}),
    ],
)
def test_timeline_routes(admin, account, monkeypatch, kind, method, params):
    called = []
    monkeypatch.setattr(
        "console.app.XAPI." + method, lambda *a, **k: called.append((a, k)) or {}
    )
    r = admin.get(
        "/api/accounts/" + account + "/timeline",
        params={"kind": kind, "cursor": "page2", **params},
    )
    assert r.status_code == 200 and r.json() == {
        "posts": [],
        "users": [],
        "cursor": None,
    }
    assert called[0][1]["cursor"] == "page2"


def test_explorer_allowlist_and_chat_secret_redaction(admin, account, monkeypatch):
    fn, fields, label = xbridge.READS["chat_inbox"]
    monkeypatch.setitem(
        xbridge.READS,
        "chat_inbox",
        (
            lambda auth: {
                "chat_token": "secret",
                "inbox": [
                    {"id": "42", "juicebox_tokens": ["sensitive"], "text": "ciphertext"}
                ],
            },
            fields,
            label,
        ),
    )
    r = admin.post(
        "/api/accounts/" + account + "/explore",
        json={"operation": "chat_inbox", "params": {}},
    )
    assert r.status_code == 200 and "secret" not in r.text and "sensitive" not in r.text
    assert r.json()["inbox"][0]["id"] == "42"
    assert (
        admin.post(
            "/api/accounts/" + account + "/explore",
            json={"operation": "__dict__", "params": {}},
        ).status_code
        == 400
    )
    assert (
        admin.post(
            "/api/accounts/" + account + "/explore",
            json={"operation": "chat_inbox", "params": {"file_path": "/etc/passwd"}},
        ).status_code
        == 400
    )


def test_upload_owner_and_expiry(admin, account, app, monkeypatch):
    called = []

    def upload(auth, path, **kwargs):
        with open(path, "rb") as f:
            called.append(f.read())
        return "x-media-id"

    monkeypatch.setattr("console.app.XMediaAPI.upload", upload)
    r = admin.post(
        "/api/accounts/" + account + "/media",
        files={"file": ("photo.png", b"fixture-image", "image/png")},
    )
    assert r.status_code == 200 and called == [b"fixture-image"]
    mid = r.json()["id"]
    assert (
        admin.post(
            "/api/accounts/" + account + "/media",
            files={"file": ("file.exe", b"bad", "application/octet-stream")},
        ).status_code
        == 400
    )
    r = admin.post(
        "/api/jobs",
        json={
            "account_id": account,
            "request_id": "request-with-expired-media",
            "state": "queued",
            "scheduled": time.time() + 25 * 3600,
            "payload": {"text": "image", "media": [mid]},
        },
    )
    assert r.status_code == 400 and "过期" in r.text


def test_rest_errors_do_not_report_false_success(monkeypatch):
    from builder.auth import XAuth
    from x_apis.x_write_api import XWriteAPI
    from x_apis.errors import GraphQLError

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"errors": [{"code": 32, "message": "Expired"}]}

    monkeypatch.setattr("x_apis.x_write_api.client.post", lambda *a, **k: Response())
    auth = XAuth().prepare_auth("auth_token=a; ct0=b")
    monkeypatch.setattr(auth, "client_transaction_id", lambda *a: "test")
    with pytest.raises(GraphQLError):
        XWriteAPI.follow_user(auth, "123")
