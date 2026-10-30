"""Account-scoped login diagnostics. Request secrets are never recorded."""

import json
import re
import time
import traceback
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote
from urllib.parse import quote, quote_plus
from html import escape
from http.cookies import SimpleCookie
from console.store import uid, encode

SENSITIVE = re.compile(
    r"password|passwd|passcode|(?:^|_)pin(?:$|_)|private.?key|cookie|authorization|secret|token|csrf|email|phone|date_of_birth",
    re.I,
)


def sanitize(value, secrets=()):
    if isinstance(value, dict):
        return {
            str(k): ("[redacted]" if SENSITIVE.search(str(k)) else sanitize(v, secrets))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitize(v, secrets) for v in value[:150]]
    if not isinstance(value, str):
        return value
    text = value
    variants = set()
    for s in secrets:
        if isinstance(s, str) and s:
            variants.update(
                (
                    s,
                    quote(s, safe=""),
                    quote_plus(s),
                    json.dumps(s)[1:-1],
                    escape(s, quote=True),
                )
            )
    for secret in sorted(variants, key=len, reverse=True):
        text = text.replace(secret, "[redacted]")
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[email]", text)
    text = re.sub(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        "[token]",
        text,
        flags=re.I,
    )
    text = re.sub(r"[A-Za-z0-9_+/%=.-]{40,}", "[opaque value]", text)
    text = re.sub(r"\b\d{4,8}\b", "[code]", text)
    return "".join(c for c in text if c in "\n\t" or ord(c) >= 32)[:6000]


class LoginTrace:
    def __init__(self, store, account, secrets=()):
        self.store = store
        self.account = account
        self.attempt = uid()
        self.started = time.time()
        self.secrets = list(secrets)
        self.store.run(
            "DELETE FROM request_logs WHERE account_id=? AND created<?",
            (account, time.time() - 30 * 86400),
        )
        self.status("starting", "正在通过账号代理建立 X 登录会话")

    def status(self, stage, message):
        self.store.run(
            "INSERT INTO account_logins VALUES(?,?,?,?,?) ON DUPLICATE KEY UPDATE stage=VALUES(stage),message=VALUES(message),started=VALUES(started),updated=VALUES(updated)",
            (self.account, stage, message[:500], self.started, time.time()),
        )

    def request(self, method, url):
        path = urlsplit(url).path
        if "Viewer" in path:
            stage, message = "verifying", "正在验证 X 登录身份"
        elif "/actions/" in path:
            stage, message = "credentials", "正在提交账号验证，请等待 X 返回结果"
        elif path in ("", "/"):
            stage, message = "connecting", "正在通过绑定的代理连接 X"
        else:
            stage, message = "preparing", "正在准备 X 登录材料与会话"
        self.status(stage, message)

    def response(self, method, url, response, elapsed, fields):
        from x_apis.login_api import XJetfuelLoginApi

        for cookie in response.cookies:
            self.secrets.append(cookie.value)
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            try:
                body = sanitize(response.json(), self.secrets)
            except ValueError:
                body = "无法解析 JSON 响应"
        elif "html" in content_type:
            title = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.I | re.S)
            body = {
                "html_title": sanitize(title.group(1) if title else "", self.secrets),
                "bytes": len(response.content),
            }
        else:
            strings = XJetfuelLoginApi._decode(response.content)
            body = sanitize(strings if strings else response.text[:4000], self.secrets)
        headers = {
            k: v
            for k, v in response.headers.items()
            if k.lower()
            in (
                "content-type",
                "retry-after",
                "x-rate-limit-limit",
                "x-rate-limit-remaining",
                "x-rate-limit-reset",
            )
        }
        headers["set-cookie-names"] = [cookie.name for cookie in response.cookies]
        parsed = urlsplit(url)
        self.store.run(
            "INSERT INTO request_logs(account_id,attempt_id,method,path,status,duration_ms,request_fields,response_headers,response_excerpt,error_type,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                self.account,
                self.attempt,
                method,
                parsed.hostname + parsed.path,
                response.status_code,
                int(elapsed * 1000),
                encode(fields),
                encode(headers),
                encode(
                    {
                        "response": body,
                        "request_checks": getattr(response, "gateway_diagnostics", {}),
                    }
                )[:6000],
                "",
                time.time(),
            ),
        )

    def failure(self, exc, message):
        frames = [
            f"{Path(f.filename).name}:{f.lineno}:{f.name}"
            for f in traceback.extract_tb(exc.__traceback__)[-6:]
        ]
        detail = {
            "exception": type(exc).__name__,
            "frames": frames,
            "message": sanitize(str(exc), self.secrets),
        }
        self.store.run(
            "INSERT INTO request_logs(account_id,attempt_id,method,path,status,duration_ms,request_fields,response_headers,response_excerpt,error_type,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                self.account,
                self.attempt,
                "LOCAL",
                "login",
                None,
                int((time.time() - self.started) * 1000),
                "[]",
                "{}",
                encode(detail)[:6000],
                type(exc).__name__,
                time.time(),
            ),
        )
        self.status("failed", message)
