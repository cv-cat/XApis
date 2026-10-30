"""Account age gates and an atomic, persistent per-account publication ledger."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import time
from fastapi import HTTPException
from console.store import uid

TIMEZONE = ZoneInfo("Asia/Shanghai")
DAY = 86400


class PolicyWait(HTTPException):
    def __init__(self, message, retry_at, status_code=423):
        super().__init__(status_code, message)
        self.retry_at = retry_at


def day_bounds(now):
    local = datetime.fromtimestamp(now, TIMEZONE)
    tomorrow = datetime.combine(
        local.date() + timedelta(days=1), datetime.min.time(), TIMEZONE
    )
    return local.date(), tomorrow.timestamp()


def bind_policy(db, account, x_id, now=None):
    now = time.time() if now is None else now
    p = db.execute(
        "SELECT * FROM account_policies WHERE x_id=?",
        (x_id,),
    ).fetchone()
    if not p:
        pid = uid()
        db.execute(
            "INSERT INTO account_policies VALUES(?,?,?,?,?,?)",
            (
                pid,
                account["owner"],
                x_id,
                now,
                now + account["warmup_days"] * DAY,
                now + 7 * DAY,
            ),
        )
        p = db.execute("SELECT * FROM account_policies WHERE id=?", (pid,)).fetchone()
    return dict(p)


def status(store, account, now=None):
    now = time.time() if now is None else now
    p = (
        store.one(
            "SELECT * FROM account_policies WHERE id=?", (account.get("policy_id"),)
        )
        if account.get("policy_id")
        else None
    )
    if not p:
        return {
            "stage": "not_started",
            "can_write": False,
            "warmup_days": account["warmup_days"],
            "first_login": None,
            "warmup_until": None,
            "limit_until": None,
            "daily_limit": 2,
            "today_used": 0,
            "remaining": 0,
            "timezone": "Asia/Shanghai",
        }
    today, _ = day_bounds(now)
    used = store.one(
        "SELECT COALESCE(SUM(units),0) n FROM publication_ledger WHERE policy_id=? AND day=? AND state!='rejected'",
        (p["id"], today),
    )["n"]
    warming = now < p["warmup_until"]
    limited = now < p["limit_until"]
    return {
        "stage": "warming" if warming else "limited" if limited else "ready",
        "can_write": not warming and account["status"] == "connected",
        "warmup_days": account["warmup_days"],
        "first_login": p["first_login"],
        "warmup_until": p["warmup_until"],
        "limit_until": p["limit_until"],
        "daily_limit": 2 if limited else None,
        "today_used": int(used),
        "remaining": max(0, 2 - int(used)) if limited else None,
        "timezone": "Asia/Shanghai",
    }


def ensure_write(store, account, at=None):
    at = time.time() if at is None else at
    if not account.get("policy_id"):
        raise PolicyWait("请先完成首次登录，养护周期从首次成功登录开始", at + 3600)
    p = store.one("SELECT * FROM account_policies WHERE id=?", (account["policy_id"],))
    if at < p["warmup_until"]:
        until = datetime.fromtimestamp(p["warmup_until"], TIMEZONE).strftime(
            "%m月%d日 %H:%M"
        )
        raise PolicyWait(
            f"账号处于只读养护期，{until}（北京时间）自动释放 X 写权限",
            p["warmup_until"],
        )
    return p


def reserve(store, account, request_id, units, now=None):
    now = time.time() if now is None else now
    today, tomorrow = day_bounds(now)
    with store.connect(immediate=True) as db:
        p = db.execute(
            "SELECT * FROM account_policies WHERE id=?", (account.get("policy_id"),)
        ).fetchone()
        if not p:
            raise PolicyWait("账号尚未完成首次登录", now + 3600)
        if now < p["warmup_until"]:
            raise PolicyWait(
                "账号仍在只读养护期，发布任务将在到期后继续", p["warmup_until"]
            )
        existing = db.execute(
            "SELECT id FROM publication_ledger WHERE id=?", (request_id,)
        ).fetchone()
        if existing:
            raise HTTPException(409, "发布请求已有记录，请先核对结果，不能重复发送")
        used = int(
            db.execute(
                "SELECT COALESCE(SUM(units),0) n FROM publication_ledger WHERE policy_id=? AND day=? AND state!='rejected'",
                (p["id"], today),
            ).fetchone()["n"]
        )
        if now < p["limit_until"] and used + units > 2:
            retry = p["limit_until"] if units > 2 else min(tomorrow, p["limit_until"])
            raise PolicyWait(
                "账号首次登录后 7 天内每天最多 2 篇，今天额度不足；串文按每条计数",
                retry,
                429,
            )
        db.execute(
            "INSERT INTO publication_ledger(id,policy_id,day,units,state,created,updated) VALUES(?,?,?,?,?,?,?)",
            (request_id, p["id"], today, units, "reserved", now, now),
        )


def confirm(store, request_id, confirmed):
    store.run(
        "UPDATE publication_ledger SET confirmed=?,updated=? WHERE id=?",
        (confirmed, time.time(), request_id),
    )


def finish(store, request_id, confirmed, uncertain=False):
    units = confirmed + (1 if uncertain else 0)
    state = "uncertain" if uncertain else "sent" if confirmed else "rejected"
    store.run(
        "UPDATE publication_ledger SET units=?,confirmed=?,state=?,updated=? WHERE id=?",
        (units, confirmed, state, time.time(), request_id),
    )
