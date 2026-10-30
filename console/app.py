"""XApis Web API. One scheduler per MySQL database owns durable task state."""

import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import os
import re
from pathlib import Path
import secrets
from console.store import IntegrityError
import tempfile
import time
from urllib.parse import urlsplit
from fastapi import (
    FastAPI,
    Depends,
    Request,
    Response,
    HTTPException,
    UploadFile,
    File,
    Form,
    Query,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from console.store import Store, uid, encode
from console.security import require, password_hash, password_check, token_hash
from console import models as M
from console import xbridge as X
from console.content import Content
from console.jobs import Queue
from console.network import target
from console.middleware import BodyLimit
from console import policy
from console import chat as chat_adapter
from x_apis.x_dm_api import XChatAPI
from console.cookies import hook as cookie_hook
from console.diagnostics import LoginTrace, sanitize
from utils.x_util import tweet_weight, parse_tweet_id
from x_apis.x_api import XAPI
from x_apis.x_article_api import XArticleAPI
from x_apis.x_media_api import XMediaAPI, MIME_BY_EXT
from x_apis.login_api import XJetfuelLoginApi, LoginChallenge, LoginFailed
from builder.auth import XAuth

STATIC = Path(__file__).parent / "static"
COOKIE = "xapis_session"


def create_app(data_dir=None, start_worker=True):
    store = Store(data_dir)
    queue = Queue(store)
    chat_service = chat_adapter.ChatService(store)
    dummy_password = password_hash(secrets.token_urlsafe(32))
    os.environ.setdefault("X_REQUIRE_PROXY", "1")
    os.environ.setdefault("X_GATEWAY_URL", "http://127.0.0.1:8090")
    os.environ.setdefault("X_SHELL_ATTEMPTS", "2")

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            store.acquire_worker()
            store.run("UPDATE accounts SET status='pending' WHERE status='logging_in'")
            queue.start()
        yield
        if start_worker:
            await asyncio.to_thread(queue.close)
            store.release_worker()

    app = FastAPI(
        title="XApis Console",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(BodyLimit)
    app.state.store = store
    app.state.queue = queue

    @app.middleware("http")
    async def security_headers(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            expected = os.getenv("CONSOLE_PUBLIC_URL", "").rstrip("/") or str(
                request.base_url
            ).rstrip("/")
            if request.headers.get("x-requested-with") != "XApis" or (
                origin and origin != expected
            ):
                return JSONResponse(
                    {"detail": "请求来源验证失败，请从控制台页面操作"}, 403
                )
        size = request.headers.get("content-length")
        if size and (not size.isdigit() or int(size) > 55 * 1024 * 1024):
            return JSONResponse({"detail": "请求过大（最大 50 MB 媒体）"}, 413)
        try:
            response = await call_next(request)
        except Exception as exc:
            # Do not let upstream exceptions containing URLs/cookies reach server logs.
            response = JSONResponse({"detail": X.safe_error(exc)}, 502)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; style-src 'self'; img-src 'self' https://*.twimg.com data: blob:; media-src https://*.twimg.com blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            }
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # FastAPI's default errors echo input, potentially including passwords.
        errors = [
            {"field": ".".join(map(str, e["loc"][1:])), "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse({"detail": "请检查输入字段", "fields": errors}, 422)

    @app.exception_handler(Exception)
    async def upstream_error(request, exc):
        return JSONResponse({"detail": X.safe_error(exc)}, 502)

    def current(request: Request):
        session = store.one(
            "SELECT s.*,u.username,u.role,u.disabled FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
            (token_hash(request.cookies.get(COOKIE, "")),),
        )
        require(
            session and session["expires"] > time.time() and not session["disabled"],
            "请先登录",
            401,
        )
        if request.method not in ("GET", "HEAD"):
            require(
                hmac.compare_digest(
                    request.headers.get("x-csrf-token", ""), session["csrf"]
                ),
                "会话验证失败，请刷新页面",
                403,
            )
        return session

    def admin(user=Depends(current)):
        require(user["role"] == "admin", "需要管理员权限", 403)
        return user

    def owned(table, item, user):
        assert table in (
            "accounts",
            "sources",
            "entries",
            "rules",
            "jobs",
            "keyword_groups",
        )
        row = store.one(
            f"SELECT * FROM {table} WHERE id=? AND owner=?", (item, user["user_id"])
        )
        require(row, "记录不存在", 404)
        return row

    def session_response(response, user_id):
        raw = secrets.token_urlsafe(48)
        csrf = secrets.token_urlsafe(32)
        now = time.time()
        store.run("DELETE FROM sessions WHERE expires<?", (now,))
        store.run(
            "INSERT INTO sessions VALUES(?,?,?,?)",
            (token_hash(raw), user_id, csrf, now + 7 * 86400),
        )
        response.set_cookie(
            COOKIE,
            raw,
            max_age=7 * 86400,
            httponly=True,
            samesite="strict",
            secure=os.getenv("CONSOLE_COOKIE_SECURE", "0") == "1",
            path="/",
        )
        row = store.one("SELECT id,username,role FROM users WHERE id=?", (user_id,))
        return {"user": row, "csrf": csrf}

    def throttle(request, key, limit=10):
        require(
            store.throttle(
                key + ":" + (request.client.host if request.client else "unknown"),
                limit,
            ),
            "操作过于频繁，请在 15 分钟后重试",
            429,
        )

    @app.get("/healthz")
    def health():
        store.one("SELECT 1")
        require(
            not start_worker or (queue.thread and queue.thread.is_alive()),
            "调度器未运行",
            503,
        )
        return {"status": "ok", "database": "mysql"}

    @app.get("/api/auth/status")
    def auth_status():
        return {"initialized": bool(store.one("SELECT id FROM users LIMIT 1"))}

    @app.post("/api/auth/setup")
    def setup(body: M.Setup, request: Request, response: Response):
        throttle(request, "setup")
        require(
            hmac.compare_digest(body.token, store.setup_token), "初始化令牌不正确", 403
        )
        password = password_hash(body.password)
        user_id = uid()
        with store.connect(immediate=True) as db:
            require(
                not db.execute("SELECT id FROM users LIMIT 1").fetchone(),
                "控制台已初始化，请登录",
                409,
            )
            db.execute(
                "INSERT INTO users(id,username,password,role,created) VALUES(?,?,?,?,?)",
                (user_id, body.username, password, "admin", time.time()),
            )
        store.audit(user_id, "auth.setup", "首位管理员创建完成")
        return session_response(response, user_id)

    @app.post("/api/auth/login")
    def login(body: M.LoginCredentials, request: Request, response: Response):
        throttle(request, "login", 20)
        require(
            store.throttle("username:" + body.username.lower(), 20),
            "登录尝试过多，请稍后重试",
            429,
        )
        user = store.one("SELECT * FROM users WHERE username=?", (body.username,))
        # Equal-cost check for nonexistent users.
        encoded = user["password"] if user else dummy_password
        valid = password_check(body.password, encoded)
        require(user and valid and not user["disabled"], "账号或密码不正确", 401)
        store.audit(user["id"], "auth.login")
        return session_response(response, user["id"])

    @app.get("/api/auth/me")
    def me(user=Depends(current)):
        return {
            "user": {
                "id": user["user_id"],
                "username": user["username"],
                "role": user["role"],
            },
            "csrf": user["csrf"],
        }

    @app.post("/api/auth/logout")
    def logout(response: Response, user=Depends(current)):
        store.run("DELETE FROM sessions WHERE token=?", (user["token"],))
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.post("/api/auth/password")
    def password(body: M.Password, response: Response, user=Depends(current)):
        row = store.one("SELECT password FROM users WHERE id=?", (user["user_id"],))
        require(password_check(body.current, row["password"]), "当前密码不正确", 403)
        with store.connect() as db:
            db.execute(
                "UPDATE users SET password=? WHERE id=?",
                (password_hash(body.new), user["user_id"]),
            )
            db.execute("DELETE FROM sessions WHERE user_id=?", (user["user_id"],))
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/users")
    def users(user=Depends(admin)):
        return store.all(
            "SELECT id,username,role,disabled,created FROM users ORDER BY created"
        )

    @app.post("/api/users")
    def add_user(body: M.UserCreate, user=Depends(admin)):
        try:
            store.run(
                "INSERT INTO users(id,username,password,role,created) VALUES(?,?,?,?,?)",
                (
                    uid(),
                    body.username,
                    password_hash(body.password),
                    body.role,
                    time.time(),
                ),
            )
        except IntegrityError:
            raise HTTPException(409, "用户名已存在") from None
        store.audit(user["user_id"], "user.create", body.username)
        return {"ok": True}

    @app.patch("/api/users/{user_id}")
    def update_user(user_id: str, body: M.UserUpdate, user=Depends(admin)):
        with store.connect(immediate=True) as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            require(row, "用户不存在", 404)
            if (
                row["role"] == "admin"
                and not row["disabled"]
                and (body.disabled or body.role != "admin")
            ):
                count = db.execute(
                    "SELECT COUNT(*) FROM users WHERE role='admin' AND disabled=0"
                ).fetchone()[0]
                require(count > 1, "不能停用或降级最后一位管理员", 409)
            db.execute(
                "UPDATE users SET role=?,disabled=? WHERE id=?",
                (body.role, body.disabled, user_id),
            )
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        store.audit(user["user_id"], "user.update", row["username"])
        return {"ok": True}

    def account_public(row):
        secret = store.decrypt(row["secret"])
        return {
            **{k: v for k, v in row.items() if k not in ("secret", "owner")},
            "proxy": X.proxy_label(secret["proxy"]),
            "policy": policy.status(store, row),
        }

    @app.get("/api/accounts")
    def accounts(user=Depends(current)):
        return [
            account_public(r)
            for r in store.all(
                "SELECT * FROM accounts WHERE owner=? ORDER BY created",
                (user["user_id"],),
            )
        ]

    @app.post("/api/accounts")
    def add_account(body: M.AccountCreate, user=Depends(current)):
        proxy = X.proxy_url(body.proxy)
        account_id = uid()
        store.run(
            "INSERT INTO accounts(id,owner,x_id,handle,name,secret,status,created,warmup_days) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                account_id,
                user["user_id"],
                "pending-" + account_id,
                "",
                body.name,
                store.encrypt({"proxy": proxy}),
                "pending",
                time.time(),
                body.warmup_days,
            ),
        )
        return account_public(owned("accounts", account_id, user))

    @app.put("/api/accounts/{account_id}/proxy")
    def set_proxy(account_id: str, body: M.Proxy, user=Depends(current)):
        row = owned("accounts", account_id, user)
        proxy = X.proxy_url(body.proxy)
        require(row["status"] != "logging_in", "账号正在登录，请稍后重试", 409)
        require(
            not store.one(
                "SELECT id FROM jobs WHERE account_id=? AND state='sending'",
                (account_id,),
            ),
            "账号正在发布，请稍后重试",
            409,
        )
        with store.connect(immediate=True) as db:
            latest = db.execute("SELECT secret FROM accounts WHERE id=? FOR UPDATE", (account_id,)).fetchone()
            prior_secret = store.decrypt(latest["secret"])
            replacement = {"proxy": proxy}
            if prior_secret.get("chat_pin"):
                replacement["chat_pin"] = prior_secret["chat_pin"]
            db.execute(
                "UPDATE accounts SET secret=?,status='pending',session_version=session_version+1 WHERE id=?",
                (store.encrypt(replacement), account_id),
            )
            db.execute("UPDATE rules SET enabled=0 WHERE account_id=?", (account_id,))
            db.execute(
                "UPDATE jobs SET state='draft' WHERE account_id=? AND state='queued'",
                (account_id,),
            )
        return {
            "ok": True,
            "message": "代理已更新，请重新登录；自动化已暂停，待发布内容已转为草稿",
        }

    @app.post("/api/accounts/{account_id}/login")
    def login_account(
        account_id: str, body: M.LoginAccount, request: Request, user=Depends(current)
    ):
        throttle(request, "xlogin:" + user["user_id"], 8)
        row = owned("accounts", account_id, user)
        secret = store.decrypt(row["secret"])
        proxy = X.proxy_url(secret.get("proxy", ""))
        require(
            not store.one(
                "SELECT id FROM jobs WHERE account_id=? AND state='sending'",
                (account_id,),
            ),
            "请等待当前发布完成",
            409,
        )
        require(
            store.run(
                "UPDATE accounts SET status='logging_in',session_version=session_version+1 WHERE id=? AND status!='logging_in'",
                (account_id,),
            ),
            "账号正在登录",
            409,
        )
        proxies = {"http": proxy, "https": proxy, "_account": account_id}
        from urllib.parse import unquote

        proxy_parts = urlsplit(proxy)
        trace = LoginTrace(
            store,
            account_id,
            [
                body.username,
                body.password,
                body.cookies,
                proxy,
                unquote(proxy_parts.username or ""),
                unquote(proxy_parts.password or ""),
            ],
        )
        proxies["_on_request"] = trace.request
        proxies["_on_response"] = trace.response
        proxies["_deadline"] = time.monotonic() + 180
        auth_holder = [None]
        proxies["_on_cookies"] = cookie_hook(
            store, account_id, row["session_version"] + 1, lambda: auth_holder[0]
        )
        try:
            if body.cookies.strip():
                auth = XAuth(proxies=proxies).prepare_auth(body.cookies)
                auth_holder[0] = auth
                require(auth.is_logged_in, "Cookie 需要包含 auth_token 和 ct0")
            else:
                require(
                    body.username.strip() and body.password, "请输入 X 用户名和密码"
                )
                api = XJetfuelLoginApi(proxies=proxies, pure_rl_values=body.profile)
                auth_holder[0] = api.auth
                auth = api.login(body.username.strip(), body.password)
                auth_holder[0] = auth
            p = X.profile(XAPI.get_viewer(auth))
            require(
                p and p["x_id"] and p["handle"] and auth.is_logged_in,
                "X 未返回有效用户身份，请检查会话",
                502,
            )
            require(
                row["x_id"].startswith("pending-") or row["x_id"] == p["x_id"],
                "登录身份与此账号原绑定的 X 用户不同，请新增账号，避免已有任务发往错误账号",
                409,
            )
            if not auth.user_id:
                auth.update_cookies({"twid": "u%3D" + p["x_id"]})
            # Retain cookie metadata accumulated during all login responses.
            secret = store.decrypt(
                store.one("SELECT secret FROM accounts WHERE id=?", (account_id,))[
                    "secret"
                ]
            )
            secret["cookies"] = auth.cookie_str
            with store.connect(immediate=True) as db:
                account_policy = policy.bind_policy(db, row, p["x_id"])
                db.execute(
                    "UPDATE accounts SET x_id=?,handle=?,name=?,avatar=?,secret=?,status='connected',policy_id=?,cookie_updated=? WHERE id=?",
                    (
                        p["x_id"],
                        p["handle"],
                        p["name"],
                        p["avatar"],
                        store.encrypt(secret),
                        account_policy["id"],
                        time.time(),
                        account_id,
                    ),
                )
                db.execute(
                    "INSERT IGNORE INTO account_maintenance(account_id,next_run) VALUES(?,?)",
                    (account_id, time.time() + 30),
                )
            store.audit(user["user_id"], "account.connected", p["handle"])
            trace.status("connected", "X 身份已验证，账号已连接")
        except Exception as exc:
            store.run("UPDATE accounts SET status='pending' WHERE id=?", (account_id,))
            if isinstance(exc, IntegrityError):
                code, message = 409, "此 X 账号已经添加"
            elif isinstance(exc, LoginChallenge):
                code, message = (
                    409,
                    "X 要求验证码、2FA 或设备验证，请在浏览器完成后导入 Cookie",
                )
            elif isinstance(exc, LoginFailed):
                code, message = (
                    409,
                    "X 登录失败：" + sanitize(str(exc), trace.secrets)[:350],
                )
            elif isinstance(exc, HTTPException):
                code, message = exc.status_code, exc.detail
            else:
                code, message = 502, X.safe_error(exc)
            trace.failure(exc, message)
            raise HTTPException(code, message) from None
        return account_public(owned("accounts", account_id, user))

    @app.get("/api/accounts/{account_id}/login-status")
    def login_status(account_id: str, user=Depends(current)):
        owned("accounts", account_id, user)
        return store.one(
            "SELECT stage,message,started,updated FROM account_logins WHERE account_id=?",
            (account_id,),
        ) or {"stage": "idle", "message": "尚未开始登录"}

    @app.get("/api/accounts/{account_id}/request-logs")
    def request_logs(account_id: str, user=Depends(current)):
        owned("accounts", account_id, user)
        rows = store.all(
            "SELECT attempt_id,method,path,status,duration_ms,request_fields,response_headers,response_excerpt,error_type,created FROM request_logs WHERE account_id=? ORDER BY id DESC LIMIT 100",
            (account_id,),
        )
        for row in rows:
            row["request_fields"] = json.loads(row["request_fields"])
            row["response_headers"] = json.loads(row["response_headers"])
        return rows

    @app.post("/api/accounts/{account_id}/proxy-test")
    def proxy_test(account_id: str, user=Depends(current)):
        account = owned("accounts", account_id, user)
        secret = store.decrypt(account["secret"])
        from builder import gateway

        started = time.monotonic()
        response = gateway.request(
            "GET",
            "https://x.com/",
            proxies={
                "http": secret["proxy"],
                "https": secret["proxy"],
                "_account": account_id,
            },
            timeout=20,
        )
        return {
            "status": response.status_code,
            "seconds": round(time.monotonic() - started, 2),
            "message": f"代理通路已建立，X 返回 HTTP {response.status_code}",
        }

    @app.delete("/api/accounts/{account_id}")
    def delete_account(account_id: str, user=Depends(current)):
        row = owned("accounts", account_id, user)
        require(
            row["status"] != "logging_in"
            and not store.one(
                "SELECT id FROM jobs WHERE account_id=? AND state='sending'",
                (account_id,),
            ),
            "账号正忙，请稍后重试",
            409,
        )
        store.run("DELETE FROM accounts WHERE id=?", (account_id,))
        return {"ok": True}

    @app.get("/api/accounts/{account_id}/timeline")
    def get_timeline(
        account_id: str,
        kind: str = "home",
        q: str = "",
        cursor: str | None = None,
        product: str = "Latest",
        user=Depends(current),
    ):
        row = owned("accounts", account_id, user)
        auth = X.auth_for(store, row)
        require(kind in ("home", "mine", "search", "detail", "user"), "未知时间线")
        require(len(q) <= 500 and (not cursor or len(cursor) <= 4000), "查询过长")
        require(
            product in ("Top", "Latest", "People", "Media", "Lists"), "未知搜索类型"
        )
        if kind == "mine":
            raw = XAPI.get_user_post_note(auth, row["x_id"], cursor=cursor)
        elif kind == "search":
            require(q, "请输入搜索关键词")
            raw = XAPI.search_work(auth, q, cursor=cursor, product=product)
        elif kind == "detail":
            require(q, "请输入贴文 ID")
            raw = XAPI.get_work_info(auth, q, cursor=cursor)
        elif kind == "user":
            p = X.profile(XAPI.get_user_info(auth, q))
            require(p, "用户不存在", 404)
            return {
                **X.timeline(XAPI.get_user_post_note(auth, p["x_id"], cursor=cursor)),
                "profile": p,
            }
        else:
            raw = XAPI.get_home_timeline(auth, cursor=cursor)
        return X.timeline(raw)

    @app.get("/api/accounts/{account_id}/posts/{post_id}")
    def post_detail(account_id: str, post_id: str, cursor: str | None = None, user=Depends(current)):
        row = owned("accounts", account_id, user)
        require(post_id.isascii() and post_id.isdigit() and len(post_id) <= 30, "贴文 ID 无效")
        require(not cursor or len(cursor) <= 4000, "翻页游标过长")
        auth = X.auth_for(store, row)
        return X.discussion(XAPI.get_work_info(auth, post_id, cursor=cursor), post_id)

    @app.get("/api/accounts/{account_id}/chat/inbox")
    def chat_inbox(account_id: str, cursor: str | None = None, user=Depends(current)):
        account = owned("accounts", account_id, user)
        require(not cursor or len(cursor) <= 5000, "收件箱翻页游标过长")
        auth = X.auth_for(store, account)
        raw = XChatAPI.get_inbox_page(auth, chat_adapter.parse_cursor(cursor)) if cursor else XChatAPI.get_initial_chat_page(auth)
        if not cursor:
            chat_service.remember_metadata(account, raw)
        return chat_adapter.inbox(raw, account["x_id"])

    @app.get("/api/accounts/{account_id}/chat/status")
    def chat_status(account_id: str, user=Depends(current)):
        account = owned("accounts", account_id, user)
        return {"has_saved_pin": bool(store.decrypt(account["secret"]).get("chat_pin")),
                "send_supported": True, "can_write": policy.status(store, account)["can_write"]}

    @app.get("/api/accounts/{account_id}/chat/recipient")
    def chat_recipient(account_id: str, handle: str, user=Depends(current)):
        account = owned("accounts", account_id, user)
        handle = handle.lstrip("@").strip()
        require(re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle), "请输入有效的 X 用户名")
        person = X.profile(XAPI.get_user_info(X.auth_for(store, account), handle))
        require(person, "未找到该聊天用户", 404)
        ids = sorted({account["x_id"], person["x_id"]}, key=int)
        cid = ":".join(ids if len(ids) == 2 else ids * 2)
        return {"id": cid, "title": person["name"] or person["handle"],
                "participant_ids": ids, "participants": [person], "events": []}

    @app.get("/api/accounts/{account_id}/chat/public-keys")
    def chat_public_keys(account_id: str, ids: str, user=Depends(current)):
        account = owned("accounts", account_id, user)
        user_ids = list(dict.fromkeys(ids.split(",")))
        require(0 < len(user_ids) <= 100 and all(v.isascii() and v.isdigit() and len(v) <= 30 for v in user_ids), "聊天成员 ID 无效")
        return chat_adapter.public_keys(XChatAPI.get_public_keys(X.auth_for(store, account), user_ids, include_juicebox_tokens=False))

    @app.put("/api/accounts/{account_id}/chat/password")
    def save_chat_password(account_id: str, body: M.ChatPassword, user=Depends(current)):
        account = owned("accounts", account_id, user)
        chat_service.save_pin(account, body.pin)
        store.audit(user["user_id"], "chat.password.saved", account_id)
        return {"has_saved_pin": True}

    @app.delete("/api/accounts/{account_id}/chat/password")
    def clear_chat_password(account_id: str, user=Depends(current)):
        chat_service.save_pin(owned("accounts", account_id, user), None)
        store.audit(user["user_id"], "chat.password.removed", account_id)
        return {"has_saved_pin": False}

    @app.get("/api/accounts/{account_id}/chat/conversations/{conversation_id}")
    def chat_conversation(account_id: str, conversation_id: str, before: str | None = None,
                          key_before: str | None = None, user=Depends(current)):
        account = owned("accounts", account_id, user)
        require(re.fullmatch(r"[a-zA-Z0-9:-]{1,200}", conversation_id), "会话 ID 无效")
        for value in (before, key_before):
            require(value is None or (value.isascii() and value.isdigit() and len(value) <= 20), "会话翻页游标无效")
        payload = XChatAPI.get_conversation_page(X.auth_for(store, account), conversation_id,
                    min_local_sequence_id=before or 9223372036854775807,
                    min_conversation_key_version=key_before or 9223372036854775807)
        return {"id": conversation_id, **chat_service.display_page(account, conversation_id, payload)}

    @app.post("/api/accounts/{account_id}/chat/send")
    def chat_send(account_id: str, body: M.ChatSend, user=Depends(current)):
        account = owned("accounts", account_id, user)
        policy.ensure_write(store, account)
        auth = X.auth_for(store, account)
        event = chat_service.dispatch(account, body.message_id, "send", body.model_dump(),
                                      lambda: XChatAPI.send_message(auth, **body.model_dump()))
        return {"accepted": True, "message_id": body.message_id, "events": [event]}

    @app.post("/api/accounts/{account_id}/chat/conversation-keys")
    def chat_setup_keys(account_id: str, body: M.ChatKeySetup, user=Depends(current)):
        account = owned("accounts", account_id, user)
        policy.ensure_write(store, account)
        members = set(body.conversation_id.split(":"))
        require(account["x_id"] in members and members == {p.user_id for p in body.conversation_participant_keys}, "会话成员与密钥接收者不一致")
        auth = X.auth_for(store, account)
        current_page = chat_adapter.conversation_page(XChatAPI.get_conversation_page(auth, body.conversation_id))
        require(not current_page["events"] and not current_page["has_more"], "已有会话需要先读取并恢复原密钥，不能覆盖会话密钥", 409)
        result = chat_service.dispatch(account, body.action_signatures[0].message_id, "keys", body.model_dump(),
                                       lambda: XChatAPI.add_conversation_keys(auth, **body.model_dump()))
        return {"confirmed": True, "sequence_id": result["conversation_key_change_sequence_id"]}

    @app.post("/api/accounts/{account_id}/chat/unlock-context")
    def chat_unlock_context(account_id: str, request: Request, user=Depends(current)):
        account = owned("accounts", account_id, user)
        throttle(request, "chat-unlock:" + account_id, 6)
        return chat_service.context(account)

    @app.post("/api/accounts/{account_id}/chat/relay")
    def chat_relay(account_id: str, body: M.ChatRelay, user=Depends(current)):
        return chat_service.relay(owned("accounts", account_id, user), body)

    @app.delete("/api/accounts/{account_id}/chat/unlock-context/{context_id}")
    def chat_lock(account_id: str, context_id: str, user=Depends(current)):
        chat_service.discard(owned("accounts", account_id, user), context_id)
        return {"ok": True}

    @app.post("/api/accounts/{account_id}/action")
    def action(account_id: str, body: M.Action, user=Depends(current)):
        row = owned("accounts", account_id, user)
        policy.ensure_write(store, row)
        auth = X.auth_for(store, row)
        if body.action in ("follow", "unfollow"):
            require(body.target.isdigit(), "关注操作需要用户数字 ID")
        else:
            require(parse_tweet_id(body.target).isdigit(), "请输入有效贴文 ID / 链接")
        result = X.ACTIONS[body.action](auth, body.target)
        store.audit(user["user_id"], "x." + body.action, body.target)
        return {"ok": True}

    @app.post("/api/accounts/{account_id}/article-action")
    def article_action(account_id: str, body: M.ArticleAction, user=Depends(current)):
        account = owned("accounts", account_id, user)
        policy.ensure_write(store, account)
        auth = X.auth_for(store, account)
        if body.action == "delete":
            result = XArticleAPI.delete(auth, body.article_id)
        else:
            request_id = "article:" + body.request_id
            policy.reserve(store, account, request_id, 1)
            try:
                result = XArticleAPI.publish(auth, body.article_id, body.caption)
                policy.finish(store, request_id, 1)
            except Exception as exc:
                from x_apis.errors import GraphQLError

                policy.finish(store, request_id, 0, not isinstance(exc, GraphQLError))
                raise
        store.audit(user["user_id"], "article." + body.action, body.article_id)
        return X.public_raw(result)

    @app.get("/api/capabilities")
    def capabilities(user=Depends(current)):
        return {
            "reads": [
                {"id": k, "label": v[2], "params": v[1]} for k, v in X.READS.items()
            ],
            "dm_send": True,
            "gateway": "go-tls-client" if os.getenv("X_GATEWAY_URL") else "curl_cffi",
            "proxy_required": True,
        }

    @app.post("/api/accounts/{account_id}/explore")
    def explore(account_id: str, body: M.Explorer, user=Depends(current)):
        require(body.operation in X.READS, "未支持的操作")
        fn, fields, _ = X.READS[body.operation]
        require(set(body.params) <= set(fields), "参数不支持")
        for key, value in body.params.items():
            if key == "user_ids":
                require(
                    isinstance(value, list)
                    and 0 < len(value) <= 50
                    and all(isinstance(v, str) and v.isdigit() for v in value),
                    "用户 ID 需为字符串数组",
                )
            else:
                require(
                    isinstance(value, str) and len(value) <= 4000, "参数必须为字符串"
                )
        if "lifecycle" in body.params:
            require(
                body.params["lifecycle"] in ("Draft", "Published"),
                "状态必须为 Draft 或 Published",
            )
        params = {k: v for k, v in body.params.items() if v != ""}
        import inspect

        try:
            inspect.signature(fn).bind(None, **params)
        except TypeError:
            raise HTTPException(400, "缺少必填参数") from None
        result = fn(X.auth_for(store, owned("accounts", account_id, user)), **params)
        return X.public_raw(result)

    @app.post("/api/accounts/{account_id}/media")
    def upload_media(
        account_id: str,
        file: UploadFile = File(...),
        purpose: str = Form("post"),
        allow_download: bool = Form(True),
        user=Depends(current),
    ):
        row = owned("accounts", account_id, user)
        policy.ensure_write(store, row)
        auth = X.auth_for(store, row)
        suffix = Path(file.filename or "").suffix.lower()
        require(suffix in MIME_BY_EXT, "支持 JPG、PNG、GIF、WebP、MP4、MOV")
        require(purpose in ("post", "article"), "媒体用途无效")
        if purpose == "article":
            require(
                suffix in (".jpg", ".jpeg", ".png", ".webp"),
                "文章插图与封面需使用 JPG、PNG 或 WebP",
            )
        with tempfile.NamedTemporaryFile(suffix=suffix) as f:
            total = 0
            while chunk := file.file.read(1024 * 1024):
                total += len(chunk)
                require(total <= 50 * 1024 * 1024, "文件不得超过 50 MB", 413)
                f.write(chunk)
            require(total > 0, "文件为空")
            f.flush()
            x_id = XMediaAPI.upload(
                auth,
                f.name,
                with_metadata=purpose != "article",
                allow_download=allow_download,
            )
        media_id = uid()
        store.run(
            "INSERT INTO media VALUES(?,?,?,?,?,?,?)",
            (
                media_id,
                user["user_id"],
                account_id,
                x_id,
                Path(file.filename).name,
                MIME_BY_EXT[suffix],
                time.time(),
            ),
        )
        return {
            "id": media_id,
            "name": Path(file.filename).name,
            "mime": MIME_BY_EXT[suffix],
        }

    @app.get("/api/ai")
    def ai_config(user=Depends(current)):
        row = store.one("SELECT * FROM ai_settings WHERE owner=?", (user["user_id"],))
        if not row:
            return {
                "base_url": "https://api.openai.com/v1",
                "model": "",
                "instruction": "",
                "configured": False,
                "token_parameter": "auto",
            }
        return {k: v for k, v in row.items() if k not in ("owner", "secret")} | {
            "configured": True,
            "has_key": bool(store.decrypt(row["secret"]).get("api_key")),
            "token_parameter": store.decrypt(row["secret"]).get(
                "token_parameter", "auto"
            ),
        }

    @app.put("/api/ai")
    def save_ai(body: M.AIConfig, user=Depends(current)):
        target(body.base_url, allow_private=True)
        require(not urlsplit(body.base_url).query, "AI 基础地址不能包含查询参数")
        existing = store.one(
            "SELECT secret FROM ai_settings WHERE owner=?", (user["user_id"],)
        )
        values = store.decrypt(existing["secret"]) if existing else {}
        if body.api_key or not existing:
            values["api_key"] = body.api_key
        values["token_parameter"] = body.token_parameter
        secret = store.encrypt(values)
        store.run(
            "INSERT INTO ai_settings VALUES(?,?,?,?,?) ON DUPLICATE KEY UPDATE base_url=VALUES(base_url),model=VALUES(model),secret=VALUES(secret),instruction=VALUES(instruction)",
            (
                user["user_id"],
                body.base_url.rstrip("/"),
                body.model,
                secret,
                body.instruction,
            ),
        )
        return {"ok": True}

    @app.post("/api/ai/generate")
    def generate(body: M.Generate, request: Request, user=Depends(current)):
        throttle(request, "ai:" + user["user_id"], 30)
        entries = []
        for eid in body.entry_ids:
            e = store.one(
                "SELECT e.* FROM entries e JOIN sources s ON s.id=e.source_id WHERE e.id=? AND s.owner=?",
                (eid, user["user_id"]),
            )
            require(e, "热点不存在", 404)
            entries.append(e)
        return Content(store).generate(
            user["user_id"], body.prompt, entries, body.style, body.long
        )

    @app.get("/api/sources")
    def sources(user=Depends(current)):
        return store.all(
            "SELECT * FROM sources WHERE owner=? ORDER BY created DESC",
            (user["user_id"],),
        )

    @app.post("/api/sources")
    def add_source(body: M.Source, user=Depends(current)):
        target(body.url)
        sid = uid()
        store.run(
            "INSERT INTO sources(id,owner,name,url,kind,enabled,created) VALUES(?,?,?,?,?,?,?)",
            (
                sid,
                user["user_id"],
                body.name,
                body.url,
                body.kind,
                body.enabled,
                time.time(),
            ),
        )
        return {"id": sid}

    @app.delete("/api/sources/{source_id}")
    def delete_source(source_id: str, user=Depends(current)):
        owned("sources", source_id, user)
        for rule in store.all("SELECT * FROM rules WHERE owner=?", (user["user_id"],)):
            require(
                source_id not in json.loads(rule["source_ids"]),
                "请先移除引用此来源的自动化任务",
                409,
            )
        store.run("DELETE FROM sources WHERE id=?", (source_id,))
        return {"ok": True}

    @app.post("/api/sources/{source_id}/refresh")
    def refresh_source(source_id: str, request: Request, user=Depends(current)):
        throttle(request, "source:" + user["user_id"], 30)
        source = owned("sources", source_id, user)
        try:
            count = Content(store).collect(source)
        except Exception as exc:
            error = exc.detail if isinstance(exc, HTTPException) else X.safe_error(exc)
            store.run("UPDATE sources SET error=? WHERE id=?", (error, source_id))
            raise HTTPException(502, error) from None
        return {"count": count}

    @app.get("/api/entries")
    def entries(user=Depends(current)):
        return store.all(
            "SELECT e.*,s.name source_name FROM entries e JOIN sources s ON s.id=e.source_id WHERE s.owner=? ORDER BY COALESCE(e.published,e.fetched) DESC LIMIT 100",
            (user["user_id"],),
        )

    def validate_job(body, user):
        account = owned("accounts", body.account_id, user)
        if body.state == "queued":
            require(account["status"] == "connected", "请先完成账号登录", 409)
            policy.ensure_write(store, account, body.scheduled or time.time())
        p = body.payload
        texts = p.texts if p.kind == "thread" else [p.text]
        require(
            texts and all(t.strip() and len(t) <= 25000 for t in texts),
            "正文不能为空或过长",
        )
        if p.kind != "article" and not p.long:
            require(
                all(tweet_weight(t) <= 280 for t in texts),
                "普通贴文超过 280 权重，请缩短或启用 Premium 长贴文",
            )
        if p.kind == "article":
            require(p.title.strip(), "请填写文章标题")
        if p.reply_to:
            require(parse_tweet_id(p.reply_to).isdigit(), "回复贴文 ID 无效")
        if p.article_id:
            require(p.article_id.isdigit(), "文章 ID 无效")
        if p.quote_url:
            u = urlsplit(p.quote_url)
            require(
                u.scheme == "https"
                and u.hostname in ("x.com", "twitter.com")
                and parse_tweet_id(p.quote_url).isdigit(),
                "请输入 X 贴文引用链接",
            )
        scheduled = body.scheduled or time.time()
        require(
            time.time() - 300 <= scheduled <= time.time() + 366 * 86400,
            "发布时间必须在未来一年内",
        )
        media = []
        for mid in p.media:
            m = store.one(
                "SELECT * FROM media WHERE id=? AND owner=? AND account_id=?",
                (mid, user["user_id"], body.account_id),
            )
            require(m, "媒体不存在或不属于该账号")
            media.append(m)
            if body.state == "queued":
                require(
                    scheduled < m["created"] + 23 * 3600,
                    "X 媒体约 24 小时后过期，请在发布前重新上传",
                )
        if len(media) > 1:
            require(
                all(
                    m["mime"] in ("image/jpeg", "image/png", "image/webp")
                    for m in media
                ),
                "视频或 GIF 不能与其他媒体混合",
            )
        return scheduled

    @app.get("/api/jobs")
    def jobs(user=Depends(current)):
        rows = store.all(
            "SELECT j.*,a.handle,a.name account_name FROM jobs j JOIN accounts a ON a.id=j.account_id WHERE j.owner=? ORDER BY j.created DESC LIMIT 200",
            (user["user_id"],),
        )
        for r in rows:
            r["payload"] = json.loads(r["payload"])
            r["result"] = json.loads(r["result"])
        return rows

    @app.post("/api/jobs")
    def create_job(body: M.Job, user=Depends(current)):
        scheduled = validate_job(body, user)
        now = time.time()
        job_id = uid()
        with store.connect(immediate=True) as db:
            existing = db.execute(
                "SELECT id FROM jobs WHERE owner=? AND request_id=?",
                (user["user_id"], body.request_id),
            ).fetchone()
            if existing:
                return {"id": existing["id"], "duplicate": True}
            db.execute(
                "INSERT INTO jobs(id,owner,account_id,request_id,payload,state,scheduled,created,updated) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    user["user_id"],
                    body.account_id,
                    body.request_id,
                    encode(body.payload.model_dump()),
                    body.state,
                    scheduled,
                    now,
                    now,
                ),
            )
        store.audit(user["user_id"], "job." + body.state, job_id)
        return {"id": job_id}

    @app.put("/api/jobs/{job_id}")
    def edit_job(job_id: str, body: M.Job, user=Depends(current)):
        owned("jobs", job_id, user)
        scheduled = validate_job(body, user)
        changed = store.run(
            "UPDATE jobs SET payload=?,account_id=?,state=?,scheduled=?,updated=? WHERE id=? AND state='draft'",
            (
                encode(body.payload.model_dump()),
                body.account_id,
                body.state,
                scheduled,
                time.time(),
                job_id,
            ),
        )
        require(changed, "仅草稿可以编辑，请先取消排期", 409)
        return {"id": job_id}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, user=Depends(current)):
        owned("jobs", job_id, user)
        require(
            store.run(
                "UPDATE jobs SET state='draft',updated=? WHERE id=? AND state='queued'",
                (time.time(), job_id),
            ),
            "任务已开始或不在队列，无法取消",
            409,
        )
        return {"ok": True}

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str, user=Depends(current)):
        owned("jobs", job_id, user)
        require(
            store.run("DELETE FROM jobs WHERE id=? AND state='draft'", (job_id,)),
            "只能删除草稿",
            409,
        )
        return {"ok": True}

    @app.get("/api/rules")
    def rules(user=Depends(current)):
        rows = store.all(
            "SELECT * FROM rules WHERE owner=? ORDER BY created DESC",
            (user["user_id"],),
        )
        for row in rows:
            row["source_ids"] = json.loads(row["source_ids"])
        return rows

    def validate_rule(body, user):
        a = owned("accounts", body.account_id, user)
        if body.enabled:
            require(a["status"] == "connected", "请先完成账号登录", 409)
        require(
            store.one(
                "SELECT owner FROM ai_settings WHERE owner=?", (user["user_id"],)
            ),
            "请先连接 AI",
            409,
        )
        for sid in body.source_ids:
            owned("sources", sid, user)

    @app.post("/api/rules")
    def add_rule(body: M.Rule, user=Depends(current)):
        validate_rule(body, user)
        rid = uid()
        now = time.time()
        store.run(
            "INSERT INTO rules(id,owner,account_id,name,source_ids,prompt,mode,interval_minutes,daily_limit,enabled,next_run,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rid,
                user["user_id"],
                body.account_id,
                body.name,
                encode(body.source_ids),
                body.prompt,
                body.mode,
                body.interval_minutes,
                body.daily_limit,
                body.enabled,
                now + body.interval_minutes * 60,
                now,
            ),
        )
        return {"id": rid}

    @app.put("/api/rules/{rule_id}")
    def update_rule(rule_id: str, body: M.Rule, user=Depends(current)):
        row = owned("rules", rule_id, user)
        validate_rule(body, user)
        require(not row["running"], "任务正在执行，请完成后编辑", 409)
        store.run(
            "UPDATE rules SET account_id=?,name=?,source_ids=?,prompt=?,mode=?,interval_minutes=?,daily_limit=?,enabled=?,next_run=? WHERE id=?",
            (
                body.account_id,
                body.name,
                encode(body.source_ids),
                body.prompt,
                body.mode,
                body.interval_minutes,
                body.daily_limit,
                body.enabled,
                time.time() + body.interval_minutes * 60,
                rule_id,
            ),
        )
        return {"ok": True}

    @app.post("/api/rules/{rule_id}/run")
    def run_rule(rule_id: str, user=Depends(current)):
        row = owned("rules", rule_id, user)
        require(row["enabled"], "请先启用任务", 409)
        require(not row["running"], "任务正在执行", 409)
        store.run("UPDATE rules SET next_run=? WHERE id=?", (time.time(), rule_id))
        return {"ok": True}

    @app.post("/api/rules/{rule_id}/pause")
    def pause_rule(rule_id: str, user=Depends(current)):
        owned("rules", rule_id, user)
        with store.connect() as db:
            db.execute("UPDATE rules SET enabled=0 WHERE id=?", (rule_id,))
            db.execute(
                "UPDATE jobs SET state='draft' WHERE rule_id=? AND state='queued'",
                (rule_id,),
            )
        return {"ok": True}

    @app.delete("/api/rules/{rule_id}")
    def delete_rule(rule_id: str, user=Depends(current)):
        row = owned("rules", rule_id, user)
        require(not row["running"], "请等待任务运行完成", 409)
        with store.connect() as db:
            db.execute(
                "UPDATE jobs SET state='draft' WHERE rule_id=? AND state='queued'",
                (rule_id,),
            )
            db.execute("DELETE FROM rules WHERE id=?", (rule_id,))
        return {"ok": True}

    @app.get("/api/keyword-groups")
    def keyword_groups(user=Depends(current)):
        rows = store.all(
            "SELECT * FROM keyword_groups WHERE owner=? ORDER BY created",
            (user["user_id"],),
        )
        for row in rows:
            row["keywords"] = json.loads(row["keywords"])
        return rows

    def validate_keywords(body):
        keywords = list(dict.fromkeys(k.strip() for k in body.keywords if k.strip()))
        require(
            keywords and all(len(k) <= 200 for k in keywords),
            "每组至少一个关键词，每个不超过 200 字符",
        )
        return keywords

    @app.post("/api/keyword-groups")
    def add_keyword_group(body: M.KeywordGroup, user=Depends(current)):
        keywords = validate_keywords(body)
        gid = uid()
        store.run(
            "INSERT INTO keyword_groups VALUES(?,?,?,?,?)",
            (gid, user["user_id"], body.name, encode(keywords), time.time()),
        )
        return {"id": gid}

    @app.put("/api/keyword-groups/{group_id}")
    def update_keyword_group(
        group_id: str, body: M.KeywordGroup, user=Depends(current)
    ):
        owned("keyword_groups", group_id, user)
        keywords = validate_keywords(body)
        store.run(
            "UPDATE keyword_groups SET name=?,keywords=? WHERE id=?",
            (body.name, encode(keywords), group_id),
        )
        return {"ok": True}

    @app.delete("/api/keyword-groups/{group_id}")
    def delete_keyword_group(group_id: str, user=Depends(current)):
        owned("keyword_groups", group_id, user)
        tasks = store.all(
            "SELECT m.group_ids FROM account_maintenance m JOIN accounts a ON a.id=m.account_id WHERE a.owner=?",
            (user["user_id"],),
        )
        require(
            all(group_id not in json.loads(t["group_ids"]) for t in tasks),
            "请先解除账号对此关键词分组的绑定",
            409,
        )
        store.run("DELETE FROM keyword_groups WHERE id=?", (group_id,))
        return {"ok": True}

    @app.get("/api/maintenance")
    def maintenance_list(user=Depends(current)):
        rows = store.all(
            "SELECT m.*,a.name,a.handle,a.status,a.cookie_updated FROM account_maintenance m JOIN accounts a ON a.id=m.account_id WHERE a.owner=? ORDER BY a.created",
            (user["user_id"],),
        )
        for row in rows:
            row["group_ids"] = json.loads(row["group_ids"])
            row["state"] = json.loads(row["state"])
            row["policy"] = policy.status(
                store, owned("accounts", row["account_id"], user)
            )
        return rows

    @app.put("/api/accounts/{account_id}/maintenance")
    def configure_maintenance(
        account_id: str, body: M.Maintenance, user=Depends(current)
    ):
        account = owned("accounts", account_id, user)
        require(
            body.delay_max_seconds >= body.delay_min_seconds,
            "随机延迟最大值不能小于最小值",
        )
        for gid in body.group_ids:
            owned("keyword_groups", gid, user)
        with store.connect(immediate=True) as db:
            previous = db.execute(
                "SELECT running FROM account_maintenance WHERE account_id=?",
                (account_id,),
            ).fetchone()
            require(
                not previous or not previous["running"],
                "正在读取当前页，请完成后再修改配置",
                409,
            )
            db.execute(
                "INSERT INTO account_maintenance(account_id,group_ids,enabled,interval_minutes,pages_per_cycle,delay_min_seconds,delay_max_seconds,read_comments,comment_pages,next_run,read_home,home_pages_per_cycle) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE group_ids=VALUES(group_ids),enabled=VALUES(enabled),interval_minutes=VALUES(interval_minutes),pages_per_cycle=VALUES(pages_per_cycle),delay_min_seconds=VALUES(delay_min_seconds),delay_max_seconds=VALUES(delay_max_seconds),read_comments=VALUES(read_comments),comment_pages=VALUES(comment_pages),next_run=VALUES(next_run),read_home=VALUES(read_home),home_pages_per_cycle=VALUES(home_pages_per_cycle),state=JSON_OBJECT()",
                (
                    account_id,
                    encode(body.group_ids),
                    body.enabled,
                    body.interval_minutes,
                    body.pages_per_cycle,
                    body.delay_min_seconds,
                    body.delay_max_seconds,
                    body.read_comments,
                    body.comment_pages,
                    time.time() + body.delay_min_seconds,
                    body.read_home,
                    body.home_pages_per_cycle,
                ),
            )
        store.audit(user["user_id"], "maintenance.configure", account_id)
        return {"ok": True}

    @app.post("/api/accounts/{account_id}/maintenance/run")
    def run_maintenance(account_id: str, user=Depends(current)):
        account = owned("accounts", account_id, user)
        require(account["status"] == "connected", "请先登录账号", 409)
        with store.connect(immediate=True) as db:
            row = db.execute(
                "SELECT * FROM account_maintenance WHERE account_id=?", (account_id,)
            ).fetchone()
            require(row and row["enabled"], "请先配置并启用账号养护", 409)
            require(not row["running"], "正在读取当前页", 409)
            require(
                not row["last_run"]
                or time.time() >= row["last_run"] + row["delay_min_seconds"],
                "正在等待最低读取间隔，不能连续触发",
                409,
            )
            require(
                not json.loads(row["state"]) or row["next_run"] <= time.time(),
                "正在等待随机翻页间隔，不能跳过",
                409,
            )
            db.execute(
                "UPDATE account_maintenance SET next_run=? WHERE account_id=?",
                (time.time(), account_id),
            )
        return {"ok": True}

    @app.post("/api/accounts/{account_id}/maintenance/pause")
    def pause_maintenance(account_id: str, user=Depends(current)):
        owned("accounts", account_id, user)
        store.run(
            "UPDATE account_maintenance SET enabled=0 WHERE account_id=?", (account_id,)
        )
        return {"ok": True}

    @app.get("/api/accounts/{account_id}/maintenance/logs")
    def maintenance_logs(account_id: str, user=Depends(current)):
        owned("accounts", account_id, user)
        rows = store.all(
            "SELECT id,keyword,operation,page,item_count,status,message,created,details FROM maintenance_logs WHERE account_id=? ORDER BY id DESC LIMIT 100",
            (account_id,),
        )
        for row in rows:
            row["details"] = json.loads(row["details"])
        return rows

    @app.get("/api/audit")
    def audit(user=Depends(current)):
        return store.all(
            "SELECT action,detail,created FROM audit WHERE owner=? ORDER BY id DESC LIMIT 100",
            (user["user_id"],),
        )

    @app.get("/api/stats")
    def stats(user=Depends(current)):
        return {
            "accounts": store.one(
                "SELECT COUNT(*) n FROM accounts WHERE owner=?", (user["user_id"],)
            )["n"],
            "jobs": {
                r["state"]: r["n"]
                for r in store.all(
                    "SELECT state,COUNT(*) n FROM jobs WHERE owner=? GROUP BY state",
                    (user["user_id"],),
                )
            },
            "rules": store.one(
                "SELECT COUNT(*) n FROM rules WHERE owner=? AND enabled=1",
                (user["user_id"],),
            )["n"],
        }

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app
