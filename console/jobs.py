"""Persistent single-runner queue. Never blindly retry a possibly published write."""

import json
import threading
import time
from fastapi import HTTPException
from console.store import uid, encode
from console.xbridge import auth_for, safe_error
from console.security import require
from console.content import Content
from console import policy
from console.maintenance import MaintenanceRunner
from utils.x_util import tweet_weight
from utils.article_util import markdown_to_content_state
from x_apis.x_write_api import XWriteAPI
from x_apis.x_article_api import XArticleAPI


class Queue:
    def __init__(self, store):
        self.store = store
        self.stop = threading.Event()
        self.thread = None
        self.maintenance = MaintenanceRunner(store)

    def start(self):
        self.recover()
        self.thread = threading.Thread(
            target=self.loop, name="xapis-scheduler", daemon=True
        )
        self.thread.start()

    def recover(self):
        # A process may have died after X accepted a request. Keep it for manual reconciliation.
        self.store.run(
            "UPDATE jobs SET state='uncertain',error='服务曾在发送期间中断，请先在 X 核对；不会自动重发',updated=? WHERE state='sending'",
            (time.time(),),
        )
        self.store.run(
            "UPDATE rules SET running=0,last_result='上次运行被中断，下个周期继续；已保留来源去重记录' WHERE running=1"
        )
        self.store.run("UPDATE account_maintenance SET running=0 WHERE running=1")
        self.store.run(
            "UPDATE maintenance_logs SET status='interrupted',message='服务曾在读取期间中断，保留已收到的结果，等待冷却后继续',details=JSON_SET(details,'$.interrupted',true) WHERE status='running'"
        )
        self.store.run(
            "UPDATE publication_ledger SET state='uncertain' WHERE state='reserved'"
        )

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=10)

    def loop(self):
        while not self.stop.is_set():
            try:
                self.store.check_worker()
            except Exception:
                try:
                    self.store.release_worker()
                    self.store.acquire_worker()
                    self.recover()
                except Exception:
                    self.stop.wait(10)
                    continue
            try:
                self.tick()
            except Exception:
                # No raw upstream exceptions or credentials in logs.
                import logging

                logging.getLogger("console").error(
                    "Scheduler iteration failed; persisted state retained"
                )
            self.stop.wait(3)

    def tick(self):
        job = None
        now = time.time()
        with self.store.connect(immediate=True) as db:
            row = db.execute(
                "SELECT j.* FROM jobs j JOIN users u ON u.id=j.owner JOIN accounts a ON a.id=j.account_id WHERE j.state='queued' AND j.scheduled<=? AND u.disabled=0 AND a.status='connected' ORDER BY j.scheduled LIMIT 1",
                (now,),
            ).fetchone()
            if row:
                job = dict(row)
                db.execute(
                    "UPDATE jobs SET state='sending',updated=? WHERE id=?",
                    (now, job["id"]),
                )
        if job:
            self.publish(job)
        rule = None
        with self.store.connect(immediate=True) as db:
            row = db.execute(
                "SELECT r.* FROM rules r JOIN users u ON u.id=r.owner WHERE r.enabled=1 AND r.running=0 AND r.next_run<=? AND u.disabled=0 ORDER BY r.next_run LIMIT 1",
                (time.time(),),
            ).fetchone()
            if row:
                rule = dict(row)
                db.execute(
                    "UPDATE rules SET running=1,next_run=? WHERE id=?",
                    (time.time() + rule["interval_minutes"] * 60, rule["id"]),
                )
        if rule:
            self.automate(rule)
        self.maintenance.tick()

    def publish(self, job):
        result = {"tweet_ids": []}
        state = "failed"
        error = None
        write_started = False
        reserved = False
        post_inflight = False
        confirmed = 0
        retry_at = None
        try:
            account = self.store.one(
                "SELECT * FROM accounts WHERE id=? AND owner=?",
                (job["account_id"], job["owner"]),
            )
            require(account, "账号已移除", 409)
            auth = auth_for(self.store, account)
            policy.ensure_write(self.store, account)
            p = json.loads(job["payload"])
            texts = p.get("texts") or [p["text"]]
            media = []
            for media_id in p.get("media", []):
                row = self.store.one(
                    "SELECT * FROM media WHERE id=? AND owner=? AND account_id=?",
                    (media_id, job["owner"], account["id"]),
                )
                require(
                    row and row["created"] > time.time() - 23 * 3600,
                    "媒体已过期，请重新上传",
                )
                media.append(row["x_id"])
            units = (
                (1 if p.get("publish_article") else 0)
                if p["kind"] == "article"
                else len(texts)
            )
            if units:
                policy.reserve(self.store, account, job["id"], units)
                reserved = True
            if p["kind"] == "article":
                # Web clients may reference only uploads belonging to this account.
                def image_upload(path):
                    key = path.removeprefix("media:")
                    row = self.store.one(
                        "SELECT * FROM media WHERE id=? AND owner=? AND account_id=?",
                        (key, job["owner"], account["id"]),
                    )
                    require(
                        row and row["created"] > time.time() - 23 * 3600,
                        "文章插图只能使用未过期的 media:上传ID",
                    )
                    return row["x_id"]

                content = markdown_to_content_state(
                    p["text"], upload_image=image_upload
                )
                write_started = True
                article = p.get("article_id") or XArticleAPI.extract_article_id(
                    XArticleAPI.create_draft(auth)
                )
                result["article_id"] = article
                self.store.run(
                    "UPDATE jobs SET result=? WHERE id=?", (encode(result), job["id"])
                )
                XArticleAPI.update_title(auth, article, p["title"])
                XArticleAPI.update_content(auth, article, content)
                if media:
                    XArticleAPI.update_cover(auth, article, media[0])
                if p.get("publish_article"):
                    post_inflight = True
                    raw = XArticleAPI.publish(
                        auth,
                        article,
                        p.get("caption", ""),
                        reply_mode=p.get("reply_mode") or None,
                    )
                    result["tweet_ids"] = [XArticleAPI.extract_tweet_id(raw)]
                    confirmed = 1
                    post_inflight = False
                    policy.confirm(self.store, job["id"], confirmed)
                result["edit_url"] = f"https://x.com/compose/articles/edit/{article}"
            else:
                parent = p.get("reply_to") or None
                for i, text in enumerate(texts):
                    if i and self.stop.wait(2):
                        raise RuntimeError("Stopping")
                    create = (
                        XWriteAPI.create_note_tweet
                        if p.get("long")
                        else XWriteAPI.create_tweet
                    )
                    write_started = True
                    post_inflight = True
                    raw = create(
                        auth,
                        text,
                        media_ids=media if i == 0 else [],
                        reply_to=parent,
                        quote_url=p.get("quote_url") or None if i == 0 else None,
                    )
                    parent = XWriteAPI.extract_tweet_id(raw)
                    result["tweet_ids"].append(parent)
                    confirmed += 1
                    post_inflight = False
                    policy.confirm(self.store, job["id"], confirmed)
                    self.store.run(
                        "UPDATE jobs SET result=?,updated=? WHERE id=?",
                        (encode(result), time.time(), job["id"]),
                    )
            state = "sent"
        except policy.PolicyWait as exc:
            state = "queued"
            retry_at = exc.retry_at
            error = exc.detail
        except Exception as exc:
            from x_apis.errors import GraphQLError

            # Explicit rejection is final; transport errors after a write are ambiguous.
            state = (
                "uncertain"
                if write_started and not isinstance(exc, (GraphQLError, HTTPException))
                else "failed"
            )
            error = exc.detail if isinstance(exc, HTTPException) else safe_error(exc)
            if isinstance(exc, GraphQLError) and exc.code in (32, 89):
                with self.store.connect() as db:
                    db.execute(
                        "UPDATE accounts SET status='expired' WHERE id=?",
                        (job["account_id"],),
                    )
                    db.execute(
                        "UPDATE rules SET enabled=0 WHERE account_id=?",
                        (job["account_id"],),
                    )
                    db.execute(
                        "UPDATE jobs SET state='draft' WHERE account_id=? AND state='queued'",
                        (job["account_id"],),
                    )
        if reserved:
            policy.finish(
                self.store, job["id"], confirmed, post_inflight and state == "uncertain"
            )
        if retry_at:
            self.store.run(
                "UPDATE jobs SET scheduled=? WHERE id=?", (retry_at, job["id"])
            )
        self.store.run(
            "UPDATE jobs SET state=?,result=?,error=?,updated=? WHERE id=?",
            (state, encode(result), error, time.time(), job["id"]),
        )
        self.store.audit(job["owner"], "publish." + state, job["id"])

    def automate(self, rule):
        outcome = "没有新内容"
        try:
            # Cap all generated items over a rolling 24-hour window, including drafts.
            count = self.store.one(
                "SELECT COUNT(*) n FROM jobs WHERE rule_id=? AND created>?",
                (rule["id"], time.time() - 86400),
            )["n"]
            if count >= rule["daily_limit"]:
                outcome = "已达到最近 24 小时生成上限"
                return
            service = Content(self.store)
            candidates = []
            for sid in json.loads(rule["source_ids"]):
                source = self.store.one(
                    "SELECT * FROM sources WHERE id=? AND owner=? AND enabled=1",
                    (sid, rule["owner"]),
                )
                if not source:
                    continue
                service.collect(source)
                candidates.extend(
                    self.store.all(
                        "SELECT e.* FROM entries e WHERE source_id=? AND NOT EXISTS "
                        "(SELECT 1 FROM rule_entries r WHERE r.entry_id=e.id AND r.rule_id=?) "
                        "ORDER BY COALESCE(published,fetched) DESC LIMIT 5",
                        (sid, rule["id"]),
                    )
                )
            candidates = sorted(
                candidates, key=lambda e: e["published"] or e["fetched"], reverse=True
            )[:3]
            if not candidates:
                return
            generated = service.generate(rule["owner"], rule["prompt"], candidates)
            # Validation failure does not consume sources; the next cycle can regenerate.
            require(
                generated["weight"] <= 280,
                "AI 输出超过普通贴文限制，本次未发布；请调整提示词",
            )
            payload = {
                "kind": "post",
                "text": generated["text"],
                "texts": [],
                "media": [],
                "long": False,
                "sources": generated["sources"],
            }
            now = time.time()
            job_id = uid()
            account = self.store.one(
                "SELECT * FROM accounts WHERE id=?", (rule["account_id"],)
            )
            account_policy = policy.status(self.store, account)
            can_publish = (
                account_policy["can_write"] and account_policy["remaining"] != 0
            )
            with self.store.connect(immediate=True) as db:
                # Cancellation/edits during generation must prevent publication.
                current = db.execute(
                    "SELECT * FROM rules WHERE id=?", (rule["id"],)
                ).fetchone()
                if not current or not current["enabled"]:
                    outcome = "任务已暂停"
                    return
                for e in candidates:
                    db.execute(
                        "INSERT INTO rule_entries VALUES(?,?)", (rule["id"], e["id"])
                    )
                db.execute(
                    "INSERT INTO jobs(id,owner,account_id,request_id,payload,state,scheduled,rule_id,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        job_id,
                        rule["owner"],
                        rule["account_id"],
                        job_id,
                        encode(payload),
                        "queued"
                        if current["mode"] == "publish" and can_publish
                        else "draft",
                        now,
                        rule["id"],
                        now,
                        now,
                    ),
                )
            outcome = (
                "已加入发布队列"
                if current["mode"] == "publish" and can_publish
                else "已生成待审核草稿"
            )
            if current["mode"] == "publish" and not can_publish:
                outcome += "（账号养护期或今日发布额度已用完）"
        except Exception as exc:
            outcome = exc.detail if isinstance(exc, HTTPException) else safe_error(exc)
        finally:
            self.store.run(
                "UPDATE rules SET running=0,last_run=?,last_result=? WHERE id=?",
                (time.time(), outcome, rule["id"]),
            )
            self.store.audit(
                rule["owner"], "automation.run", rule["name"] + ": " + outcome
            )
