import base64
import json
import pytest
from requests import Response
from builder import gateway, client


def reply(body=b"ok", status=200, headers=None):
    r = Response()
    r.status_code = 200
    r._content = json.dumps(
        {
            "status": status,
            "headers": headers or {},
            "body": base64.b64encode(body).decode(),
        }
    ).encode()
    return r


def test_gateway_prepares_body_cookie_proxy_and_session(monkeypatch):
    monkeypatch.setenv("X_GATEWAY_URL", "http://gateway:8090")
    monkeypatch.setenv("X_GATEWAY_TOKEN", "internal-secret-token-that-is-long-enough")
    seen = []

    def post(self, url, **kw):
        seen.append((url, kw))
        return reply(
            b'{"ok":true}',
            headers={
                "Set-Cookie": [
                    "auth_token=abc; Domain=.x.com; Path=/; Secure",
                    "ct0=csrf; Domain=.x.com; Path=/; Secure",
                ]
            },
        )

    monkeypatch.setattr("requests.Session.post", post)
    with gateway.Session() as s:
        s.cookies.set("guest", "g", domain=".x.com", path="/")
        response = s.post(
            "https://x.com/endpoint",
            json={"text": "你好"},
            params={"test": "a b"},
            proxies={"https": "http://u:p@proxy:8080", "_account": "account-a"},
        )
        assert response.json() == {"ok": True}
        assert s.cookies.get("auth_token") == "abc"
        assert list(s.cookies.jar)
        s.get(
            "https://x.com/next",
            proxies={"https": "http://u:p@proxy:8080", "_account": "account-a"},
        )
    first = seen[0][1]["json"]
    second = seen[1][1]["json"]
    assert first["proxy"] == "http://u:p@proxy:8080" and first["account"] == "account-a"
    assert first["url"].endswith("?test=a+b")
    assert json.loads(base64.b64decode(first["body"])) == {"text": "你好"}
    assert "guest=g" in first["headers"]["Cookie"]
    assert "auth_token=abc" in second["headers"]["Cookie"]
    assert seen[0][1]["headers"]["Authorization"].startswith("Bearer internal-")
    assert "internal-secret" not in str(first)


def test_gateway_fails_closed_no_proxy_or_down(monkeypatch):
    monkeypatch.setenv("X_GATEWAY_URL", "http://gateway:8090")
    monkeypatch.setenv("X_GATEWAY_TOKEN", "internal-secret")
    with pytest.raises(ValueError):
        gateway.Session().get("https://x.com/")
    monkeypatch.setattr(
        "builder.client._cffi.get",
        lambda *a, **k: pytest.fail("must not fall back to direct traffic"),
    )

    def bad(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr("requests.Session.post", bad)
    with pytest.raises(ConnectionError):
        client.get("https://x.com/", proxies={"https": "http://proxy:8080"})


def test_gateway_multipart_encodes_without_filesystem_paths(monkeypatch):
    monkeypatch.setenv("X_GATEWAY_URL", "http://gateway:8090")
    monkeypatch.setenv("X_GATEWAY_TOKEN", "secret")
    seen = []
    monkeypatch.setattr(
        "requests.Session.post",
        lambda self, url, **kw: seen.append(kw["json"]) or reply(),
    )
    from x_apis.x_media_api import XMediaAPI
    from builder.auth import XAuth

    auth = XAuth(proxies={"https": "http://proxy:8080", "_account": "a"}).prepare_auth(
        "auth_token=a; ct0=b"
    )
    XMediaAPI.append(auth, "123", b"video chunk", 0)
    body = base64.b64decode(seen[0]["body"])
    assert b"video chunk" in body and b'name="media"' in body
    assert seen[0]["headers"]["Content-Type"].startswith("multipart/form-data;")


def test_gateway_cross_host_redirect_does_not_leak_auth(monkeypatch):
    monkeypatch.setenv("X_GATEWAY_URL", "http://gateway:8090")
    monkeypatch.setenv("X_GATEWAY_TOKEN", "secret")
    seen = []

    def post(self, url, **kw):
        seen.append(kw["json"])
        if len(seen) == 1:
            return reply(
                status=302, headers={"Location": ["https://abs.twimg.com/file.js"]}
            )
        return reply()

    monkeypatch.setattr("requests.Session.post", post)
    gateway.Session().get(
        "https://x.com/",
        headers={"Authorization": "sensitive", "x-csrf-token": "sensitive"},
        cookies={"auth_token": "secret-cookie"},
        proxies={"https": "http://proxy:8080"},
    )
    assert "authorization" not in {k.lower() for k in seen[1]["headers"]}
    assert "auth_token" not in seen[1]["headers"].get("Cookie", "")


def test_gateway_never_replays_post_redirect(monkeypatch):
    monkeypatch.setenv("X_GATEWAY_URL", "http://gateway:8090")
    monkeypatch.setenv("X_GATEWAY_TOKEN", "secret")
    calls = []
    monkeypatch.setattr(
        "requests.Session.post",
        lambda self, url, **kw: (
            calls.append(1)
            or reply(status=302, headers={"Location": ["https://x.com/other"]})
        ),
    )
    gateway.Session().post(
        "https://x.com/write", proxies={"https": "http://proxy:8080"}
    )
    assert len(calls) == 1


def test_gateway_cookie_expiration_and_domain_scope(monkeypatch):
    monkeypatch.setenv("X_GATEWAY_URL", "http://gateway:8090")
    monkeypatch.setenv("X_GATEWAY_TOKEN", "secret")
    calls = []

    def post(self, url, **kw):
        calls.append(kw["json"])
        return reply(
            headers={
                "Set-Cookie": [
                    "auth_token=deleted; Max-Age=0; Domain=.x.com; Path=/",
                    "invalid=bad; Domain=other.example; Path=/",
                ]
            }
        )

    monkeypatch.setattr("requests.Session.post", post)
    with gateway.Session() as s:
        s.cookies.set("auth_token", "old", domain=".x.com", path="/")
        s.get("https://x.com/", proxies={"https": "http://proxy:8080"})
        assert s.cookies.get("auth_token") is None
        assert s.cookies.get("invalid") is None


def test_cookie_storage_failure_still_records_actual_http_response(monkeypatch):
    monkeypatch.setenv("X_GATEWAY_URL", "http://gateway:8090")
    monkeypatch.setenv("X_GATEWAY_TOKEN", "secret")
    monkeypatch.setattr("requests.Session.post", lambda *a, **kw: reply(b'{"data":{}}', headers={"Set-Cookie": ["ct0=fresh; Domain=.x.com; Path=/"]}))
    observed = []

    def failed_save(*args):
        raise RuntimeError("storage failed")

    def observe(method, url, response, elapsed, fields):
        observed.append((response.status_code, response.gateway_diagnostics["cookie_sync_result"]))

    with pytest.raises(RuntimeError, match="storage failed"):
        gateway.request("GET", "https://x.com/", proxies={"https": "http://proxy:8080", "_on_cookies": failed_save, "_on_response": observe})
    assert observed == [(200, {"status": "failed", "error_type": "RuntimeError"})]
