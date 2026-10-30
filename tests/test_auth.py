from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from console.security import password_check


def test_first_user_and_token(client, app):
    assert client.get("/api/auth/status").json() == {"initialized": False}
    payload = {
        "username": "root",
        "password": "Long-password-2026!",
        "token": "invalid-token-123456",
    }
    assert client.post("/api/auth/setup", json=payload).status_code == 403
    payload["token"] = app.state.store.setup_token
    r = client.post("/api/auth/setup", json=payload)
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "admin"
    assert (
        "httponly" in r.headers["set-cookie"].lower()
        and "samesite=strict" in r.headers["set-cookie"].lower()
    )
    assert "password" not in r.text
    assert client.post("/api/auth/setup", json=payload).status_code == 409
    stored = app.state.store.one("SELECT * FROM users")
    assert stored["password"] != payload["password"] and password_check(
        payload["password"], stored["password"]
    )
    assert (
        not app.state.store.one("SELECT * FROM sessions")["token"]
        in r.headers["set-cookie"]
    )


def test_atomic_first_admin(app):
    def signup(n):
        with TestClient(app) as c:
            return c.post(
                "/api/auth/setup",
                headers={"X-Requested-With": "XApis"},
                json={
                    "token": app.state.store.setup_token,
                    "username": "user" + str(n),
                    "password": "Long-password-2026!",
                },
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(signup, [1, 2]))
    assert sorted(statuses) == [200, 409]
    assert len(app.state.store.all("SELECT * FROM users")) == 1


def test_auth_and_csrf(admin, app):
    assert admin.get("/api/accounts").status_code == 200
    assert (
        admin.post(
            "/api/accounts",
            json={"name": "a", "proxy": "http://p:8080"},
            headers={"X-CSRF-Token": "wrong"},
        ).status_code
        == 403
    )
    assert (
        admin.post(
            "/api/accounts",
            json={"name": "a", "proxy": "http://p:8080"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert (
        admin.post(
            "/api/accounts",
            json={"name": "a", "proxy": "http://p:8080"},
            headers={"X-Requested-With": ""},
        ).status_code
        == 403
    )
    with TestClient(app) as outsider:
        assert outsider.get("/api/accounts").status_code == 401
        assert outsider.get("/api/ai").status_code == 401
    assert admin.post("/api/auth/logout").status_code == 200
    assert admin.get("/api/accounts").status_code == 401


def test_last_admin_and_revocation(admin, app):
    me = admin.get("/api/auth/me").json()["user"]["id"]
    assert (
        admin.patch(
            "/api/users/" + me, json={"role": "member", "disabled": False}
        ).status_code
        == 409
    )
    assert (
        admin.patch(
            "/api/users/" + me, json={"role": "admin", "disabled": True}
        ).status_code
        == 409
    )
    assert (
        admin.post(
            "/api/auth/password",
            json={"current": "wrong", "new": "A-new-password-2026"},
        ).status_code
        == 403
    )
    assert (
        admin.post(
            "/api/auth/password",
            json={"current": "Admin-test-password!", "new": "A-new-password-2026"},
        ).status_code
        == 200
    )
    assert admin.get("/api/auth/me").status_code == 401
    assert (
        admin.post(
            "/api/auth/login",
            json={"username": "admin", "password": "Admin-test-password!"},
        ).status_code
        == 401
    )
    assert (
        admin.post(
            "/api/auth/login",
            json={"username": "admin", "password": "A-new-password-2026"},
        ).status_code
        == 200
    )


def test_no_input_secrets_in_validation(client):
    r = client.post(
        "/api/auth/login",
        json={
            "username": "invalid!",
            "password": "secret-secret",
            "extra": "sensitive",
        },
    )
    assert r.status_code == 422
    assert "secret-secret" not in r.text and "sensitive" not in r.text


def test_login_checks_existing_password_without_applying_creation_policy(admin, app):
    import pytest
    from pydantic import ValidationError
    from console import models
    from console.security import password_hash

    app.state.store.run("UPDATE users SET password=? WHERE username='admin'", (password_hash("short!"),))
    assert admin.post("/api/auth/logout").status_code == 200
    assert admin.post("/api/auth/login", json={"username": "admin", "password": "wrong!"}).status_code == 401
    assert admin.post("/api/auth/login", json={"username": "admin", "password": ""}).status_code == 422
    response = admin.post("/api/auth/login", json={"username": "admin", "password": "short!"})
    assert response.status_code == 200 and response.json()["user"]["role"] == "admin"
    assert admin.get("/api/auth/me").status_code == 200
    with pytest.raises(ValidationError):
        models.UserCreate(username="member", password="short!")
    with pytest.raises(ValidationError):
        models.Setup(username="admin", password="short!", token="x" * 32)


def test_login_throttled(client):
    for _ in range(20):
        r = client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": "Invalid-test-password!"},
        )
        assert r.status_code == 401
    assert (
        client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": "Invalid-test-password!"},
        ).status_code
        == 429
    )


def test_users_are_isolated(admin, account, app):
    assert (
        admin.post(
            "/api/users",
            json={
                "username": "member",
                "password": "Member-password-123!",
                "role": "member",
            },
        ).status_code
        == 200
    )
    with TestClient(app) as member:
        member.headers["X-Requested-With"] = "XApis"
        r = member.post(
            "/api/auth/login",
            json={"username": "member", "password": "Member-password-123!"},
        )
        member.headers["X-CSRF-Token"] = r.json()["csrf"]
        assert member.get("/api/accounts").json() == []
        assert member.get("/api/users").status_code == 403
        assert member.get("/api/accounts/" + account + "/timeline").status_code == 404
        assert member.delete("/api/accounts/" + account).status_code == 404
        assert (
            member.post(
                "/api/accounts/" + account + "/login",
                json={"cookies": "auth_token=foo; ct0=bar"},
            ).status_code
            == 404
        )


def test_chunked_body_is_bounded(client):
    def content():
        for _ in range(3):
            yield b"x" * (1024 * 1024)

    r = client.post(
        "/api/auth/login",
        content=content(),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413
