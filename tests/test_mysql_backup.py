import sqlite3
from pathlib import Path
import pytest
from console.store import Store
from console.backup import export_backup, restore_backup, migrate_sqlite


def test_mysql_worker_lock_and_lost_lock_fail_closed(app, tmp_path):
    first = app.state.store
    second = Store(tmp_path / "other")
    first.acquire_worker()
    try:
        with pytest.raises(RuntimeError):
            second.acquire_worker()
        with pytest.raises(RuntimeError):
            second.check_worker()
    finally:
        first.release_worker()
    second.acquire_worker()
    second.check_worker()
    second.release_worker()
    with pytest.raises(RuntimeError):
        second.check_worker()


def test_mysql_snapshot_contains_encrypted_state(admin, account, app, tmp_path):
    store = app.state.store
    folder = export_backup(store, tmp_path / "backup")
    import json

    data = json.loads((folder / "mysql-backup.json").read_text())
    assert len(data["tables"]["accounts"]) == 1
    assert "proxy-secret" not in (folder / "mysql-backup.json").read_text()
    assert (folder / "encryption.key").read_bytes() == (
        store.directory / "encryption.key"
    ).read_bytes()
    with pytest.raises(ValueError, match="已有用户"):
        restore_backup(store, folder)


def test_migrate_legacy_sqlite_into_mysql_keeps_source_and_credentials(app, tmp_path):
    from console.security import password_hash

    source = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(source) as db:
        db.execute(
            "CREATE TABLE users(id TEXT,username TEXT,password TEXT,role TEXT,disabled INT,created REAL)"
        )
        db.execute(
            "INSERT INTO users VALUES(?,?,?,?,?,?)",
            ("u" * 32, "legacy", password_hash("Legacy-password-123"), "admin", 0, 1.0),
        )
        db.execute(
            "CREATE TABLE accounts(id TEXT,owner TEXT,x_id TEXT,handle TEXT,name TEXT,avatar TEXT,secret TEXT,status TEXT,created REAL)"
        )
        db.execute(
            "INSERT INTO accounts VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "a" * 32,
                "u" * 32,
                "123",
                "legacy",
                "Legacy",
                "",
                app.state.store.encrypt(
                    {"proxy": "http://proxy:8080", "cookies": "auth_token=a; ct0=b"}
                ),
                "connected",
                1.0,
            ),
        )
    counts = migrate_sqlite(app.state.store, source)
    assert counts["users"] == 1 and source.exists()
    account = app.state.store.one("SELECT * FROM accounts")
    assert account["policy_id"] is not None
    assert (
        app.state.store.decrypt(account["secret"])["cookies"] == "auth_token=a; ct0=b"
    )
    assert (
        app.state.store.one("SELECT first_login FROM account_policies")["first_login"]
        > 1.0
    )
    with pytest.raises(ValueError, match="已有用户"):
        migrate_sqlite(app.state.store, source)


def test_mysql_backup_restores_rows_and_key(admin, account, app, tmp_path):
    from console.backup import TABLES
    from cryptography.fernet import Fernet

    store = app.state.store
    folder = export_backup(store, tmp_path / "restore-fixture")
    expected = store.decrypt(store.one("SELECT secret FROM accounts")["secret"])
    with store.connect(immediate=True) as db:
        for table in reversed(TABLES):
            db.execute("DELETE FROM `" + table + "`")
    store.cipher = Fernet(Fernet.generate_key())
    restore_backup(store, folder)
    actual = store.one("SELECT * FROM accounts WHERE id=?", (account,))
    assert store.decrypt(actual["secret"]) == expected
    assert store.one("SELECT username FROM users")["username"] == "admin"
