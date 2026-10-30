"""Read-only account maintenance, with persisted cursor steps and jittered timing."""

import json
import random
import time
from fastapi import HTTPException
from console.store import encode, uid
from console.xbridge import auth_for, safe_error, timeline, profile
from console.maintenance_trace import MaintenanceTrace, cursor_summary
from x_apis.x_api import XAPI
from x_apis.errors import GraphQLError

_rng = random.SystemRandom()


def advance_source(state):
    """Finish sampled comments, then resume the current feed or the next source."""
    for key in ("tweet_id", "comment_page", "comment_cursor"):
        state.pop(key, None)
    if not state["feed_done"]:
        state["phase"] = state["source"]
        return state
    index = state["source_index"] + 1
    if index >= len(state["sources"]):
        return {}
    source = state["sources"][index]
    state.update(source_index=index, source=source, phase=source,
                 feed_page=0, feed_cursor=None, feed_done=False)
    return state


class MaintenanceRunner:
    def __init__(self, store):
        self.store = store

    def tick(self):
        now = time.time()
        with self.store.connect(immediate=True) as db:
            row = db.execute(
                "SELECT m.* FROM account_maintenance m JOIN accounts a ON a.id=m.account_id JOIN users u ON u.id=a.owner WHERE m.enabled=1 AND m.running=0 AND m.next_run<=? AND a.status='connected' AND u.disabled=0 ORDER BY m.next_run LIMIT 1",
                (now,),
            ).fetchone()
            if not row:
                return
            task = dict(row)
            db.execute(
                "UPDATE account_maintenance SET running=1,last_run=?,next_run=? WHERE account_id=?",
                (now, now + 180 + task["delay_max_seconds"], task["account_id"]),
            )
        self.step(task)

    def step(self, task):
        account = self.store.one(
            "SELECT * FROM accounts WHERE id=?", (task["account_id"],)
        )
        if not account:
            return
        state = json.loads(task["state"])
        operation = "viewer"
        page = 1
        count = 0
        message = ""
        status = "ok"
        next_run = 0
        delay = 0
        keyword = state.get("keyword", "")
        trace = MaintenanceTrace(self.store, account, task)
        delay_reason = "error_backoff"
        try:
            auth = auth_for(self.store, account)
            auth.proxies.update(_on_request=trace.request, _on_response=trace.response,
                                _deadline=time.monotonic() + 180)
            keywords = []
            for gid in json.loads(task["group_ids"]):
                group = self.store.one(
                    "SELECT keywords FROM keyword_groups WHERE id=? AND owner=?",
                    (gid, account["owner"]),
                )
                if group:
                    keywords.extend(json.loads(group["keywords"]))
            if state and "sources" not in state:
                # Continue an in-flight search cycle from earlier deployments.
                state.update(sources=["search"], source_index=0, source="search",
                             feed_page=state.get("search_page", 0),
                             feed_cursor=state.get("search_cursor"),
                             feed_done=state.get("search_done", False))
            if not state:
                sources = (["home"] if task.get("read_home", True) else [])
                if keywords:
                    sources.append("search")
                if sources:
                    state = {
                        "keyword": _rng.choice(list(dict.fromkeys(keywords))) if keywords else "",
                        "sources": sources, "source_index": 0, "source": sources[0],
                        "phase": sources[0], "feed_page": 0, "feed_cursor": None,
                        "feed_done": False, "cycle_id": uid(),
                    }
            operation = state.get("phase", "viewer")
            source = state.get("source", "viewer")
            keyword = state.get("keyword", "") if source == "search" else ""
            source_label = f"关键词「{keyword}」" if source == "search" else "首页推荐"
            page = state.get("comment_page" if operation == "comments" else "feed_page", 0) + 1
            trace.plan(operation, page, keyword, state)
            if not state:
                identity = profile(XAPI.get_viewer(auth))
                if not identity or identity["x_id"] != account["x_id"]:
                    raise ValueError("身份读取未返回当前绑定账号，不能确认会话保活成功")
                trace.details["identity_verified"] = True
                message = "身份读取完成；未启用浏览来源，仅进行会话保活"
            elif operation in ("home", "search"):
                cursor = state.get("feed_cursor")
                if operation == "home":
                    raw = XAPI.get_home_timeline(auth, cursor=cursor, count=20)
                    page_limit = task.get("home_pages_per_cycle", 2)
                else:
                    raw = XAPI.search_work(auth, keyword, cursor=cursor, product="Latest", count=20)
                    page_limit = task["pages_per_cycle"]
                data = timeline(raw)
                count = len(data["posts"])
                next_cursor = data["cursor"]
                stop_reason = ("page_limit" if page >= page_limit else "no_cursor"
                               if not next_cursor else "repeated_cursor" if next_cursor == cursor else None)
                trace.details.update(cursor_out=cursor_summary(next_cursor), stop_reason=stop_reason,
                                     item_ids=[p["work_id"] for p in data["posts"][:20]])
                state.update(feed_page=page, feed_cursor=next_cursor, feed_done=bool(stop_reason))
                if task["read_comments"] and data["posts"]:
                    state.update(phase="comments", tweet_id=_rng.choice(data["posts"])["work_id"],
                                 comment_page=0, comment_cursor=None)
                else:
                    state = advance_source(state)
                message = f"{source_label}第 {page} 页：读取 {count} 条贴文"
            elif operation == "comments":
                cursor = state.get("comment_cursor")
                data = timeline(XAPI.get_work_comments(auth, state["tweet_id"], cursor=cursor))
                count = len(data["posts"])
                next_cursor = data["cursor"]
                stop_reason = ("page_limit" if page >= task["comment_pages"] else "no_cursor"
                               if not next_cursor else "repeated_cursor" if next_cursor == cursor else None)
                trace.details.update(cursor_out=cursor_summary(next_cursor), stop_reason=stop_reason,
                                     item_ids=[p["work_id"] for p in data["posts"][:20]])
                if not stop_reason:
                    state.update(comment_page=page, comment_cursor=next_cursor)
                else:
                    state = advance_source(state)
                message = f"{source_label}关联评论第 {page} 页：读取 {count} 条内容"
            else:
                raise ValueError("未知的养护读取步骤")
            if state:
                delay = _rng.uniform(
                    task["delay_min_seconds"], task["delay_max_seconds"]
                )
                delay_reason = "next_page"
            else:
                delay = task["interval_minutes"] * 60 * _rng.uniform(
                    0.8, 1.2
                )
                delay_reason = "cycle_interval"
                message += "；本轮结束"
            next_run = time.time() + delay
            trace.details["delay_range_seconds"] = [task["delay_min_seconds"], task["delay_max_seconds"]] if state else [task["interval_minutes"] * 48, task["interval_minutes"] * 72]
            if any(r.get("result", {}).get("errors") for r in trace.details["requests"]):
                status = "warning"
                message += "；X 返回部分错误，详见请求日志"
        except Exception as exc:
            trace.failure(exc)
            status = "error"
            message = exc.detail if isinstance(exc, HTTPException) else safe_error(exc)
            delay = max(900, task["interval_minutes"] * 60)
            codes = [e.get("code") for r in trace.details["requests"] for e in r.get("result", {}).get("errors", []) if isinstance(e, dict)]
            if isinstance(exc, GraphQLError):
                codes.append(exc.code)
            if any(c in (32, 89) for c in codes) or any(r.get("status") == 401 for r in trace.details["requests"]):
                with self.store.connect() as db:
                    db.execute(
                        "UPDATE accounts SET status='expired' WHERE id=?",
                        (account["id"],),
                    )
                    db.execute(
                        "UPDATE account_maintenance SET enabled=0 WHERE account_id=?",
                        (account["id"],),
                    )
                    db.execute(
                        "UPDATE rules SET enabled=0 WHERE account_id=?",
                        (account["id"],),
                    )
                state = {}
                delay_reason = "account_expired"
            if any(c in (88, 226, 344) for c in codes) or any(r.get("status") == 429 for r in trace.details["requests"]):
                delay = 6 * 3600
                delay_reason = "rate_limit"
            next_run = time.time() + delay
        finally:
            trace.details.update(delay_seconds=round(delay, 3), delay_reason=delay_reason,
                                 next_run=next_run, next_operation=state.get("phase", "new_cycle"),
                                 cycle_complete=not bool(state))
            with self.store.connect() as db:
                db.execute(
                    "UPDATE account_maintenance SET running=0,state=?,next_run=?,last_run=?,last_result=?,read_count=read_count+? WHERE account_id=?",
                    (
                        encode(state),
                        next_run,
                        time.time(),
                        message,
                        count,
                        account["id"],
                    ),
                )
                trace.finish(db, status, message, count)
                # Bound per-account logs to 30 days; no post bodies are retained.
                db.execute(
                    "DELETE FROM maintenance_logs WHERE account_id=? AND created<?",
                    (account["id"], time.time() - 30 * 86400),
                )
