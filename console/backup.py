"""Portable consistent MySQL backups and one-time legacy SQLite migration."""

import json
import os
from pathlib import Path
import time
from cryptography.fernet import Fernet
from console import policy

TABLES = [
    "users",
    "sessions",
    "attempts",
    "account_policies",
    "accounts",
    "account_logins",
    "request_logs",
    "ai_settings",
    "sources",
    "entries",
    "rules",
    "jobs",
    "publication_ledger",
    "rule_entries",
    "media",
    "keyword_groups",
    "account_maintenance",
    "maintenance_logs",
    "audit",
]


def write_private(path, data):
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def export_backup(store, output):
    folder = Path(output).resolve()
    folder.mkdir(mode=0o700, exist_ok=False)
    snapshot = {}
    with store.connect() as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        db.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
        for table in TABLES:
            rows = [
                dict(r) for r in db.execute("SELECT * FROM `" + table + "`").fetchall()
            ]
            if table == "entries":
                for row in rows:
                    row.pop("url_hash", None)
            snapshot[table] = rows
    write_private(
        folder / "mysql-backup.json",
        json.dumps(
            {"version": 1, "created": time.time(), "tables": snapshot},
            ensure_ascii=False,
            default=str,
        ).encode(),
    )
    for name in ("encryption.key", "setup.token"):
        if (store.directory / name).exists():
            write_private(folder / name, (store.directory / name).read_bytes())
    return folder


def import_rows(store, tables):
    with store.connect(immediate=True) as db:
        if db.execute("SELECT id FROM users LIMIT 1").fetchone():
            raise ValueError("目标数据库已有用户，拒绝覆盖")
        for table in TABLES:
            for row in tables.get(table, []):
                row.pop("url_hash", None)
                columns = list(row)
                if not all(c.replace("_", "").isalnum() for c in columns):
                    raise ValueError("备份字段无效")
                db.execute(
                    "INSERT INTO `"
                    + table
                    + "` ("
                    + ",".join("`" + c + "`" for c in columns)
                    + ") VALUES("
                    + ",".join("?" for _ in columns)
                    + ")",
                    tuple(row[c] for c in columns),
                )
        # Legacy connected accounts start a fresh protected period on migration.
        for account in db.execute(
            "SELECT * FROM accounts WHERE status='connected' AND policy_id IS NULL"
        ).fetchall():
            p = policy.bind_policy(db, account, account["x_id"])
            db.execute(
                "UPDATE accounts SET policy_id=? WHERE id=?", (p["id"], account["id"])
            )
            db.execute(
                "INSERT IGNORE INTO account_maintenance(account_id,next_run) VALUES(?,?)",
                (account["id"], time.time() + 30),
            )


def restore_backup(store, folder):
    folder = Path(folder).resolve()
    if store.one("SELECT id FROM users LIMIT 1"):
        raise ValueError("目标数据库已有用户，拒绝覆盖")
    document = json.loads((folder / "mysql-backup.json").read_text())
    if document.get("version") != 1:
        raise ValueError("备份版本不支持")
    key = (folder / "encryption.key").read_bytes().strip()
    cipher = Fernet(key)
    for row in document["tables"].get("accounts", []):
        cipher.decrypt(row["secret"].encode())
    import_rows(store, document["tables"])
    write_private(store.directory / "encryption.key", key)
    if (folder / "setup.token").exists():
        write_private(
            store.directory / "setup.token", (folder / "setup.token").read_bytes()
        )
    store.cipher = cipher


def migrate_sqlite(store, path):
    # The old database is read-only and is retained after a successful migration.
    import sqlite3

    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError("SQLite 文件不存在")
    if store.one("SELECT id FROM users LIMIT 1"):
        raise ValueError("目标 MySQL 数据库已有用户，拒绝覆盖")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        names = {
            r[0]
            for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        tables = {
            table: [dict(row) for row in connection.execute("SELECT * FROM " + table)]
            for table in TABLES
            if table in names
        }
    finally:
        connection.close()
    # The old encryption key must be retained in CONSOLE_DATA_DIR.
    for row in tables.get("accounts", []):
        store.decrypt(row["secret"])
    import_rows(store, tables)
    return {table: len(rows) for table, rows in tables.items()}
