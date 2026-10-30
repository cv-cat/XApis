import pytest
from x_apis.login_api import LoginChallenge
from console import xbridge

VIEWER = {
    "data": {
        "viewer": {
            "user_results": {
                "result": {
                    "__typename": "User",
                    "rest_id": "456",
                    "core": {"name": "Alice", "screen_name": "alice"},
                    "avatar": {"image_url": "https://pbs.twimg.com/a.jpg"},
                }
            }
        }
    }
}


def test_proxy_required_and_no_secrets(admin, app, monkeypatch):
    assert (
        admin.post("/api/accounts", json={"name": "Alice", "proxy": ""}).status_code
        == 422
    )
    assert (
        admin.post(
            "/api/accounts", json={"name": "Alice", "proxy": "file:///etc/passwd"}
        ).status_code
        == 400
    )
    r = admin.post(
        "/api/accounts",
        json={"name": "Alice", "proxy": "http://u:top-secret@proxy.example:8080"},
    )
    assert r.status_code == 200 and r.json()["status"] == "pending"
    aid = r.json()["id"]
    assert r.json()["proxy"] == "http://proxy.example:8080"
    assert "top-secret" not in r.text
    assert (
        "top-secret"
        not in app.state.store.one("SELECT secret FROM accounts WHERE id=?", (aid,))[
            "secret"
        ]
    )
    assert admin.get("/api/accounts/" + aid + "/timeline").status_code == 409
    seen = []

    def viewer(auth):
        seen.append(
            {
                k: v
                for k, v in auth.proxies.items()
                if k in ("http", "https", "_account")
            }
        )
        assert auth.cookie["auth_token"] == "test-cookie"
        return VIEWER

    monkeypatch.setattr("console.app.XAPI.get_viewer", viewer)
    r = admin.post(
        "/api/accounts/" + aid + "/login",
        json={"cookies": "auth_token=test-cookie; ct0=csrf"},
    )
    assert r.status_code == 200 and r.json()["handle"] == "alice"
    assert seen == [
        {
            "http": "http://u:top-secret@proxy.example:8080",
            "https": "http://u:top-secret@proxy.example:8080",
            "_account": aid,
        }
    ]
    assert "test-cookie" not in admin.get("/api/accounts").text
    encrypted = app.state.store.one("SELECT secret FROM accounts WHERE id=?", (aid,))[
        "secret"
    ]
    assert "test-cookie" not in encrypted
    assert app.state.store.decrypt(encrypted)["cookies"].startswith(
        "auth_token=test-cookie"
    )


def test_password_login_uses_proxy_and_does_not_save_password(admin, app, monkeypatch):
    aid = admin.post(
        "/api/accounts", json={"name": "A", "proxy": "socks5://localhost:1080"}
    ).json()["id"]
    seen = {}

    class Login:
        def __init__(self, proxies, pure_rl_values):
            seen["proxies"] = proxies
            from builder.auth import XAuth

            self.auth = XAuth(proxies=proxies)

        def login(self, username, password):
            seen["login"] = (username, password)
            from builder.auth import XAuth

            return XAuth(proxies=seen["proxies"]).prepare_auth(
                "auth_token=test; ct0=csrf"
            )

    monkeypatch.setattr("console.app.XJetfuelLoginApi", Login)
    monkeypatch.setattr("console.app.XAPI.get_viewer", lambda a: VIEWER)
    assert (
        admin.post(
            "/api/accounts/" + aid + "/login",
            json={"username": "alice", "password": "X-password-secret"},
        ).status_code
        == 200
    )
    assert seen["proxies"]["https"] == "socks5://localhost:1080"
    assert seen["login"] == ("alice", "X-password-secret")
    assert "X-password-secret" not in str(
        app.state.store.decrypt(
            app.state.store.one("SELECT secret FROM accounts")["secret"]
        )
    )


def test_challenge_has_actionable_message(admin, monkeypatch):
    aid = admin.post(
        "/api/accounts", json={"name": "A", "proxy": "http://proxy.example:8080"}
    ).json()["id"]

    class Login:
        def __init__(self, **kwargs):
            from builder.auth import XAuth

            self.auth = XAuth()

        def login(self, *args):
            raise LoginChallenge(
                "LoginTwoFactorAuthChallenge", "secret data", "sensitive-flow"
            )

    monkeypatch.setattr("console.app.XJetfuelLoginApi", Login)
    r = admin.post(
        "/api/accounts/" + aid + "/login",
        json={"username": "alice", "password": "X-password-secret"},
    )
    assert r.status_code == 409 and "Cookie" in r.text
    assert "sensitive-flow" not in r.text
    assert admin.get("/api/accounts").json()[0]["status"] == "pending"


def test_proxy_change_invalidates_session_and_queued_jobs(admin, account, app):
    from tests_helpers import make_job

    jid = make_job(admin, account)["id"]
    r = admin.put(
        "/api/accounts/" + account + "/proxy",
        json={"proxy": "http://new-proxy.example:8080"},
    )
    assert r.status_code == 200
    assert admin.get("/api/accounts").json()[0]["status"] == "pending"
    assert "cookies" not in app.state.store.decrypt(
        app.state.store.one("SELECT secret FROM accounts")["secret"]
    )
    assert (
        app.state.store.one("SELECT state FROM jobs WHERE id=?", (jid,))["state"]
        == "draft"
    )


def test_timeline_and_nested_thread_parser():
    tweet = {
        "__typename": "Tweet",
        "rest_id": "42",
        "legacy": {"full_text": "hello", "favorite_count": 4},
        "core": {
            "user_results": {
                "result": VIEWER["data"]["viewer"]["user_results"]["result"]
            }
        },
    }
    result = xbridge.timeline(
        {
            "entries": [
                {
                    "content": {
                        "items": [
                            {
                                "item": {
                                    "itemContent": {"tweet_results": {"result": tweet}}
                                }
                            }
                        ]
                    }
                },
                {"content": {"itemContent": {"tweet_results": {"result": tweet}}}},
            ]
        }
    )
    assert len(result["posts"]) == 1
    assert result["posts"][0]["nickname"] == "Alice"
    assert result["posts"][0]["avatar"].startswith("https://pbs.twimg.com")


def test_relogin_cannot_rebind_existing_jobs_to_a_different_x_identity(
    admin, account, app, monkeypatch
):
    monkeypatch.setattr("console.app.XAPI.get_viewer", lambda *a: VIEWER)
    r = admin.post(
        "/api/accounts/" + account + "/login",
        json={"cookies": "auth_token=another; ct0=another"},
    )
    assert r.status_code == 409 and "不同" in r.text
    assert (
        app.state.store.one("SELECT x_id FROM accounts WHERE id=?", (account,))["x_id"]
        == "123"
    )
