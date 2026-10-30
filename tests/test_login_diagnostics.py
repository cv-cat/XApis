import json
from types import SimpleNamespace
from urllib.parse import quote
import requests
from builder.gateway import CookieJar, GatewayError
from builder.auth import XAuth
from console.diagnostics import LoginTrace, sanitize
from x_apis.login_api import XJetfuelLoginApi


def test_redaction_keeps_errors_but_never_secrets():
    secret = "a<password>&!"
    data = {
        "errors": [{"code": 32, "message": "Could not authenticate you"}],
        "guest_token": "short-token",
        "session_token": "uuid",
        "detail": secret + " " + quote(secret, safe=""),
        "cookie": "ct0=x",
    }
    out = sanitize(data, [secret])
    text = json.dumps(out)
    assert "Could not authenticate you" in text and out["errors"][0]["code"] == 32
    assert (
        secret not in text
        and quote(secret, safe="") not in text
        and "short-token" not in text
        and "uuid" not in text
    )


def test_actual_response_logged_and_owner_scoped(admin, account, app):
    trace = LoginTrace(app.state.store, account, ["private-password"])
    response = requests.Response()
    response.status_code = 403
    response.headers["Content-Type"] = "application/json"
    response.cookies = CookieJar()
    response.cookies.set("auth_token", "sensitive-cookie", domain=".x.com")
    response._content = json.dumps(
        {
            "errors": [{"code": 239, "message": "Bad guest token"}],
            "session_token": "sensitive-cookie",
            "password": "private-password",
        }
    ).encode()
    trace.response(
        "POST",
        "https://jf.x.com/onboarding/web/actions/begin_login?session_token=do-not-log",
        response,
        0.25,
        ["username_or_email", "password", "$castle_token"],
    )
    rows = admin.get("/api/accounts/" + account + "/request-logs").json()
    assert rows[0]["status"] == 403 and rows[0]["duration_ms"] == 250
    assert "Bad guest token" in rows[0]["response_excerpt"]
    assert (
        "sensitive-cookie" not in str(rows)
        and "private-password" not in str(rows)
        and "do-not-log" not in str(rows)
    )
    assert rows[0]["response_headers"]["set-cookie-names"] == ["auth_token"]
    assert admin.get("/api/accounts/not-owned/request-logs").status_code == 404


def test_login_failure_has_actionable_gateway_message_and_trace(
    admin, app, monkeypatch
):
    aid = admin.post(
        "/api/accounts", json={"name": "Failing", "proxy": "http://proxy:8080"}
    ).json()["id"]

    class Login:
        def __init__(self, **kw):
            self.auth = XAuth()

        def login(self, *a):
            raise GatewayError(
                "proxy_timeout", "通过代理连接 X 超时；检查 HTTP / SOCKS5 协议"
            )

    monkeypatch.setattr("console.app.XJetfuelLoginApi", Login)
    r = admin.post(
        "/api/accounts/" + aid + "/login",
        json={"username": "someone", "password": "private-password"},
    )
    assert r.status_code == 502 and "SOCKS5" in r.text and "发布结果" not in r.text
    status = admin.get("/api/accounts/" + aid + "/login-status").json()
    assert status["stage"] == "failed"
    log = admin.get("/api/accounts/" + aid + "/request-logs").json()[0]
    assert log["error_type"] == "GatewayError" and "private-password" not in str(log)


def test_har_aligned_prime_routes_and_empty_password_field():
    api = XJetfuelLoginApi.__new__(XJetfuelLoginApi)
    api.auth = XAuth()
    api.proxies = {"https": "http://proxy:8080"}
    api.guest_token = ""
    calls = []

    class Session:
        cookies = CookieJar()

        def get(self, url, **kw):
            calls.append(url)
            return SimpleNamespace(status_code=200)

    api.session = Session()
    api.session.cookies.set("gt", "guest", domain=".x.com")
    api.auth.client_transaction_id = lambda *a: "transaction"
    api._prime()
    assert "/i/jf/onboarding/web?" in calls[0]
    assert (
        calls[1]
        == "https://jf.x.com/onboarding/web?redirect_after_login=%2Fhome&mode=login"
    )
    assert calls[2] == "https://jf.x.com/onboarding/web/remotes/passkey_one_fa"
    api._prime = lambda: None

    def action(name, fields):
        assert name == "begin_login" and fields == {
            "username_or_email": "test-user",
            "password": "",
        }
        api.session.cookies.set("auth_token", "authenticated", domain=".x.com")
        return {
            "status": 200,
            "strings": ["login_success"],
            "session_token": "session",
            "actions": [],
            "resp": SimpleNamespace(text="", headers={}),
        }

    api._post_action = action
    assert api.login("test-user", "never-put-in-first-step").is_logged_in
