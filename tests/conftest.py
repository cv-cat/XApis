import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
import pymysql
import time
import os
from fastapi.testclient import TestClient
from console.app import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("CONSOLE_SETUP_TOKEN", raising=False)
    monkeypatch.delenv("CONSOLE_PUBLIC_URL", raising=False)
    monkeypatch.delenv("CONSOLE_COOKIE_SECURE", raising=False)
    config = dict(
        host=os.getenv("XAPIS_TEST_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("XAPIS_TEST_DB_PORT", "3307")),
        user="xapis",
        password="disposable-test-password",
        database="xapis_test",
    )
    with pymysql.connect(**config) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS=0")
            cursor.execute("SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]
            for table in tables:
                assert table.replace("_", "").isalnum()
                cursor.execute("DROP TABLE `" + table + "`")
            cursor.execute("SET FOREIGN_KEY_CHECKS=1")
        connection.commit()
    for key, value in [
        ("HOST", config["host"]),
        ("PORT", str(config["port"])),
        ("USER", config["user"]),
        ("PASSWORD", config["password"]),
        ("NAME", config["database"]),
    ]:
        monkeypatch.setenv("CONSOLE_DB_" + key, value)
    return create_app(tmp_path, start_worker=False)


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        c.headers["X-Requested-With"] = "XApis"
        yield c


@pytest.fixture
def admin(client, app):
    r = client.post(
        "/api/auth/setup",
        json={
            "token": app.state.store.setup_token,
            "username": "admin",
            "password": "Admin-test-password!",
        },
    )
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = r.json()["csrf"]
    return client


@pytest.fixture
def account(admin, app):
    r = admin.post(
        "/api/accounts",
        json={
            "name": "My account",
            "proxy": "http://alice:proxy-secret@proxy.example:8080",
        },
    )
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    store = app.state.store
    secret = store.encrypt(
        {
            "proxy": "http://alice:proxy-secret@proxy.example:8080",
            "cookies": "auth_token=test-auth; ct0=test-csrf; twid=u%3D123",
        }
    )
    store.run(
        "UPDATE accounts SET status='connected',x_id='123',handle='test',secret=? WHERE id=?",
        (secret, aid),
    )
    from console.store import uid

    pid = uid()
    now = time.time()
    store.run(
        "INSERT INTO account_policies VALUES(?,?,?,?,?,?)",
        (
            pid,
            r.json().get("owner")
            or store.one("SELECT owner FROM accounts WHERE id=?", (aid,))["owner"],
            "123",
            now - 8 * 86400,
            now - 4 * 86400,
            now - 86400,
        ),
    )
    store.run("UPDATE accounts SET policy_id=? WHERE id=?", (pid, aid))
    return aid
