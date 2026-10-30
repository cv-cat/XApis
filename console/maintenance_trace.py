"""Persist read-only maintenance progress without cookies, cursors or post bodies."""

import hashlib
import re
import time
import traceback
from pathlib import Path
from urllib.parse import urlsplit, unquote

from console.diagnostics import sanitize
from console.store import encode, uid
from utils.x_util import trans_cookies


def cursor_summary(value):
    return {"present": bool(value), "fingerprint": hashlib.sha256(value.encode()).hexdigest()[:12] if value else None}


class MaintenanceTrace:
    def __init__(self, store, account, task):
        self.store, self.account = store, account
        self.started = time.time()
        self.clock = time.monotonic()
        secret = store.decrypt(account["secret"])
        proxy = urlsplit(secret.get("proxy", ""))
        self.secrets = list(trans_cookies(secret.get("cookies", "")).values()) + [
            secret.get("proxy", ""), unquote(proxy.username or ""), unquote(proxy.password or "")
        ]
        self.details = {
            "step_id": uid(), "started_at": self.started,
            "scheduled_at": task["next_run"],
            "scheduler_lag_seconds": round(max(0, self.started - task["next_run"]), 2),
            "since_previous_step_seconds": round(self.started - task["last_run"], 2) if task["last_run"] else None,
            "requests": [],
        }
        with store.connect() as db:
            db.execute(
                "INSERT INTO maintenance_logs(account_id,keyword,operation,page,item_count,status,message,created,details) VALUES(?,?,?,1,0,'running',?,?,?)",
                (account["id"], "", "viewer", "调度器已领取，正在准备读取", self.started, encode(self.details)),
            )
            self.id = db.execute("SELECT LAST_INSERT_ID() AS id").fetchone()["id"]

    def save(self):
        self.store.run("UPDATE maintenance_logs SET details=? WHERE id=?", (encode(self.details), self.id))

    def plan(self, operation, page, keyword, state):
        self.details.update(cycle_id=state.get("cycle_id") or uid(),
                            source=state.get("source", operation),
                            cursor_in=cursor_summary(state.get("feed_cursor" if operation in ("home", "search") else "comment_cursor")),
                            tweet_id=state.get("tweet_id"))
        self.store.run(
            "UPDATE maintenance_logs SET operation=?,page=?,keyword=?,message=?,details=? WHERE id=?",
            (operation, page, keyword, "正在读取 X 返回结果", encode(self.details), self.id),
        )

    def request(self, method, url):
        parsed = urlsplit(url)
        request = {"method": method, "path": (parsed.hostname or "") + parsed.path,
                   "started_at": time.time(), "status": None}
        if len(self.details["requests"]) < 30:
            self.details["requests"].append(request)
        self.save()

    def response(self, method, url, response, elapsed, fields):
        self.secrets.extend(cookie.value for cookie in response.cookies)
        parsed = urlsplit(url)
        path = (parsed.hostname or "") + parsed.path
        request = next((r for r in reversed(self.details["requests"])
                        if r["path"] == path and r["status"] is None), None)
        if request is None:
            return
        request.update(status=response.status_code, duration_ms=int(elapsed * 1000))
        request["checks"] = getattr(response, "gateway_diagnostics", {})
        request["headers"] = {k: v for k, v in response.headers.items()
                              if k.lower() in ("content-type", "retry-after", "x-rate-limit-remaining", "x-rate-limit-reset")}
        try:
            body = response.json()
        except ValueError:
            title = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.I | re.S)
            request["result"] = {"bytes": len(response.content), "title": sanitize(title.group(1), self.secrets) if title else ""}
            if response.status_code >= 400:
                request["result"]["error_excerpt"] = sanitize(re.sub(r"<[^>]+>", " ", response.text[:6000]), self.secrets)[:2000]
        else:
            request["result"] = {"bytes": len(response.content)}
            if isinstance(body, dict):
                request["result"]["errors"] = sanitize(body.get("errors", []), self.secrets)
                request["result"]["data_present"] = bool(body.get("data"))
            if response.status_code >= 400:
                request["result"]["error_excerpt"] = encode(sanitize(body, self.secrets))[:4000]
        self.save()

    def failure(self, exc):
        # requests.HTTPError embeds the full URL, including opaque pagination values.
        message = re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?[query omitted]", str(exc))
        self.details["error"] = {
            "type": type(exc).__name__, "message": sanitize(message, self.secrets),
            "frames": [f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in traceback.extract_tb(exc.__traceback__)[-6:]],
        }

    def finish(self, db, status, message, count):
        self.details.update(finished_at=time.time(), duration_ms=int((time.monotonic() - self.clock) * 1000))
        db.execute(
            "UPDATE maintenance_logs SET status=?,message=?,item_count=?,details=? WHERE id=?",
            (status, message, count, encode(self.details), self.id),
        )
