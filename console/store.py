"""MySQL 8.4 state, transactional claims, and encrypted account credentials."""

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time
import pymysql
from pymysql.cursors import DictCursor
from cryptography.fernet import Fernet

IntegrityError = pymysql.IntegrityError


def uid():
    return secrets.token_hex(16)


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Row(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class Result:
    def __init__(self, cursor):
        self.rowcount = cursor.rowcount
        self.rows = (
            [Row(row) for row in cursor.fetchall()] if cursor.description else []
        )
        self.index = 0

    def fetchone(self):
        if self.index >= len(self.rows):
            return None
        row = self.rows[self.index]
        self.index += 1
        return row

    def fetchall(self):
        rows = self.rows[self.index :]
        self.index = len(self.rows)
        return rows


class Connection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, args=()):
        # All SQL comes from application sources. User values are always bound.
        sql = sql.replace("?", "%s")
        with self.raw.cursor() as cursor:
            cursor.execute(sql, args)
            return Result(cursor)


class Store:
    def __init__(self, directory=None):
        self.directory = Path(
            directory or os.getenv("CONSOLE_DATA_DIR", "data")
        ).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cipher = Fernet(self._secret_file("encryption.key", Fernet.generate_key))
        self.setup_token = (
            os.getenv("CONSOLE_SETUP_TOKEN")
            or self._secret_file(
                "setup.token", lambda: secrets.token_urlsafe(32).encode()
            ).decode()
        )
        password = os.getenv("CONSOLE_DB_PASSWORD")
        if password is None:
            password = (
                Path(os.getenv("CONSOLE_DB_PASSWORD_FILE", "/secrets/mysql/password"))
                .read_text()
                .strip()
            )
        self.database = os.getenv("CONSOLE_DB_NAME", "xapis")
        if not re.fullmatch(r"[A-Za-z0-9_]+", self.database):
            raise ValueError("Invalid database name")
        self.config = dict(
            host=os.getenv("CONSOLE_DB_HOST", "mysql"),
            port=int(os.getenv("CONSOLE_DB_PORT", "3306")),
            user=os.getenv("CONSOLE_DB_USER", "xapis"),
            password=password,
            database=self.database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
        )
        self.worker_connection = None
        self.worker_required = False
        with self.connect() as db:
            schema = (Path(__file__).parent / "mysql.sql").read_text()
            for statement in schema.split(";"):
                if statement.strip():
                    db.execute(statement)
            index = db.execute(
                "SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA=? AND TABLE_NAME=? AND INDEX_NAME=?",
                (self.database, "account_policies", "physical_xid"),
            ).fetchone()
            if not index:
                db.execute(
                    "ALTER TABLE account_policies ADD UNIQUE KEY physical_xid(x_id)"
                )
            if not db.execute(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=? AND TABLE_NAME='maintenance_logs' AND COLUMN_NAME='details'",
                (self.database,),
            ).fetchone():
                db.execute(
                    "ALTER TABLE maintenance_logs ADD COLUMN details JSON NOT NULL DEFAULT (JSON_OBJECT())"
                )
            for name, definition in (
                ("read_home", "TINYINT NOT NULL DEFAULT 1"),
                ("home_pages_per_cycle", "INT NOT NULL DEFAULT 2"),
            ):
                if not db.execute(
                    "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=? AND TABLE_NAME='account_maintenance' AND COLUMN_NAME=?",
                    (self.database, name),
                ).fetchone():
                    db.execute("ALTER TABLE account_maintenance ADD COLUMN " + name + " " + definition)

    def _secret_file(self, name, factory):
        path = self.directory / name
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return path.read_bytes().strip()
        with os.fdopen(fd, "wb") as f:
            value = factory()
            f.write(value)
        return value

    def _raw(self):
        conn = pymysql.connect(**self.config)
        with conn.cursor() as c:
            c.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            c.execute("SET SESSION innodb_lock_wait_timeout=20")
        return conn

    @contextlib.contextmanager
    def connect(self, immediate=False):
        raw = self._raw()
        db = Connection(raw)
        try:
            if immediate:
                # Shared transaction mutex covers setup, queue claims and rate counters.
                # InnoDB releases this row lock at commit/rollback, including disconnects.
                db.execute("SELECT id FROM transaction_lock WHERE id=1 FOR UPDATE")
            yield db
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally:
            raw.close()

    def all(self, sql, args=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        with self.connect() as db:
            row = db.execute(sql, args).fetchone()
            return dict(row) if row else None

    def run(self, sql, args=()):
        with self.connect() as db:
            return db.execute(sql, args).rowcount

    def encrypt(self, value):
        return self.cipher.encrypt(encode(value).encode()).decode()

    def decrypt(self, value):
        return json.loads(self.cipher.decrypt(value.encode()))

    def audit(self, owner, action, detail=""):
        self.run(
            "INSERT INTO audit(owner,action,detail,created) VALUES(?,?,?,?)",
            (owner, action, detail[:500], time.time()),
        )

    def throttle(self, key, limit=10, seconds=900):
        key = hashlib.sha256(key.encode()).hexdigest()
        now = time.time()
        with self.connect(immediate=True) as db:
            db.execute("DELETE FROM attempts WHERE until<?", (now,))
            row = db.execute("SELECT * FROM attempts WHERE `key`=?", (key,)).fetchone()
            if row and row["count"] >= limit:
                return False
            db.execute(
                "INSERT INTO attempts VALUES(?,1,?) ON DUPLICATE KEY UPDATE count=count+1",
                (key, now + seconds),
            )
        return True

    def acquire_worker(self):
        self.worker_required = True
        conn = self._raw()
        result = (
            Connection(conn)
            .execute(
                "SELECT GET_LOCK(?,0) AS acquired", (self.database + ":scheduler",)
            )
            .fetchone()
        )
        if result["acquired"] != 1:
            conn.close()
            raise RuntimeError("A scheduler already owns this MySQL database")
        self.worker_connection = conn

    def check_worker(self):
        if self.worker_required and self.worker_connection is None:
            raise RuntimeError("Scheduler lock is not held")
        if self.worker_connection:
            self.worker_connection.ping(reconnect=False)

    def release_worker(self):
        if self.worker_connection:
            connection = self.worker_connection
            self.worker_connection = None
            if connection.open:
                connection.close()
