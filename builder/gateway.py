"""requests-compatible internal Go TLS gateway transport (fail closed)."""

import base64
import hashlib
import os
import time
from pathlib import Path
from urllib.parse import urljoin, parse_qs
import requests
from requests.cookies import RequestsCookieJar
from requests.structures import CaseInsensitiveDict
from email.message import Message
from http.cookies import SimpleCookie
from http import HTTPStatus
from types import SimpleNamespace
from requests.cookies import extract_cookies_to_jar


class GatewayError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def enabled():
    return bool(os.getenv("X_GATEWAY_URL"))


def token():
    value = os.getenv("X_GATEWAY_TOKEN", "")
    if not value:
        value = (
            Path(os.getenv("X_GATEWAY_TOKEN_FILE", "data/gateway.token"))
            .read_text()
            .strip()
        )
    if not value:
        raise RuntimeError("Go gateway authentication is not configured")
    return value


class CookieJar(RequestsCookieJar):
    @property
    def jar(self):
        return self


class Session:
    def __init__(self):
        self.cookies = CookieJar()
        self._http = requests.Session()
        self._http.trust_env = False

    def request(self, method, url, **kwargs):
        # curl_cffi Session supplied these browser headers implicitly; the RPC
        # session must preserve that contract for guest activation and login.
        from builder.client import _apply_fetch_headers

        _apply_fetch_headers(url, kwargs)
        proxy = (kwargs.get("proxies") or {}).get("https") or (
            kwargs.get("proxies") or {}
        ).get("http")
        if not proxy:
            raise ValueError(
                "X account proxy is required before login or any X request"
            )
        headers = {
            k: v for k, v in (kwargs.get("headers") or {}).items() if v is not None
        }
        # Gateway handles gzip decoding; no unsupported encodings escape to callers.
        headers["accept-encoding"] = "gzip"
        jar = CookieJar()
        jar.update(self.cookies)
        jar.update(kwargs.get("cookies") or {})
        req = requests.Request(
            method,
            url,
            headers=headers,
            params=kwargs.get("params"),
            data=kwargs.get("data"),
            json=kwargs.get("json"),
            files=kwargs.get("files"),
            cookies=jar,
        ).prepare()
        body = req.body or b""
        if isinstance(body, str):
            body = body.encode()
        # Account-bound pool key. Login steps use the same proxy; explicit caller key
        # avoids different accounts sharing a pool even when the proxy is shared.
        pool_key = (kwargs.get("proxies") or {}).get("_account") or hashlib.sha256(
            proxy.encode()
        ).hexdigest()
        payload = {
            "method": method,
            "url": req.url,
            "headers": dict(req.headers),
            "body": base64.b64encode(body).decode(),
            "proxy": proxy,
            "account": pool_key,
        }
        seconds = kwargs.get("timeout", 30)
        seconds = float(seconds) if isinstance(seconds, (int, float)) else 30
        deadline = (kwargs.get("proxies") or {}).get("_deadline")
        if deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GatewayError(
                    "login_timeout",
                    "登录验证超时，请检查代理出口后重试，或导入已登录的 Cookie",
                )
            seconds = min(seconds, remaining)
        progress = (kwargs.get("proxies") or {}).get("_on_request")
        if progress:
            progress(method, req.url)
        started = time.monotonic()
        try:
            transport = self._http.post(
                os.environ["X_GATEWAY_URL"].rstrip("/") + "/v1/request",
                json=payload,
                headers={"Authorization": "Bearer " + token()},
                timeout=(5, min(120, max(1, seconds)) + 5),
            )
        except requests.Timeout:
            raise GatewayError(
                "proxy_timeout",
                "通过代理连接 X 超时；请检查代理协议（HTTP / SOCKS5）、认证信息及出口线路",
            ) from None
        except requests.RequestException:
            raise GatewayError(
                "gateway_unavailable", "无法连接出网网关，请检查网关服务是否正常运行"
            ) from None
        if transport.status_code != 200:
            messages = {
                401: ("gateway_auth", "出网网关认证失败，请检查共享密钥配置"),
                400: (
                    "proxy_configuration",
                    "代理或出网参数无效，请检查代理地址和协议",
                ),
                502: (
                    "proxy_connection",
                    "代理无法完成与 X 的连接；请确认 HTTP / SOCKS5 协议、代理认证及出口可用性",
                ),
                503: ("gateway_busy", "出网网关繁忙，请稍后重试"),
                504: ("proxy_timeout", "通过代理连接 X 超时，请检查代理协议和出口线路"),
            }
            code, message = messages.get(
                transport.status_code,
                ("gateway_error", "出网网关请求失败，请检查服务状态"),
            )
            raise GatewayError(code, message)
        data = transport.json()
        resp = requests.Response()
        resp.status_code = data["status"]
        try:
            resp.reason = HTTPStatus(resp.status_code).phrase
        except ValueError:
            resp.reason = "Upstream response"
        resp.url = req.url
        resp._content = base64.b64decode(data["body"])
        resp.encoding = "utf-8"
        resp.headers = CaseInsensitiveDict(
            {k: ", ".join(v) for k, v in data["headers"].items()}
        )
        resp.cookies = CookieJar()
        from urllib.parse import urlsplit

        host = urlsplit(req.url).hostname
        cookie_headers = Message()
        for name, values in data["headers"].items():
            for value in values:
                cookie_headers.add_header(name, value)
        cookie_response = SimpleNamespace(
            _original_response=SimpleNamespace(msg=cookie_headers)
        )
        extract_cookies_to_jar(resp.cookies, req, cookie_response)
        extract_cookies_to_jar(self.cookies, req, cookie_response)
        resp.request = req
        sent_cookies = SimpleCookie()
        try:
            sent_cookies.load(req.headers.get("Cookie", ""))
        except Exception:
            pass
        ct0 = sent_cookies.get("ct0")
        csrf = req.headers.get("x-csrf-token")
        cookie_events = []
        for name, values in data["headers"].items():
            if name.lower() == "set-cookie":
                for line in values:
                    parsed = SimpleCookie()
                    try:
                        parsed.load(line)
                    except Exception:
                        continue
                    cookie_events.extend(
                        {"name": k, "cleared": not bool(v.value)}
                        for k, v in parsed.items()
                    )
        resp.gateway_diagnostics = {
            "csrf_matches_cookie": csrf == ct0.value
            if csrf is not None and ct0
            else None,
            "cookie_names": list(sent_cookies),
            "set_cookie": cookie_events,
            "cookie_sync": "account"
            if (kwargs.get("proxies") or {}).get("_on_cookies")
            else "not applied",
        }
        callback = (kwargs.get("proxies") or {}).get("_on_cookies")
        cookie_error = None
        resp.gateway_diagnostics["cookie_sync_result"] = {
            "status": "no_set_cookie" if callback else "not_applied"
        }
        if callback:
            cookie_lines = [
                line
                for name, values in data["headers"].items()
                if name.lower() == "set-cookie"
                for line in values
            ]
            if cookie_lines:
                try:
                    resp.gateway_diagnostics["cookie_sync_result"] = callback(req.url, cookie_lines) or {"status": "unreported"}
                except Exception as exc:
                    cookie_error = exc
                    resp.gateway_diagnostics["cookie_sync_result"] = {"status": "failed", "error_type": type(exc).__name__}
        observer = (kwargs.get("proxies") or {}).get("_on_response")
        if observer:
            source = kwargs.get("json") or kwargs.get("data") or {}
            fields = (
                list(source)
                if isinstance(source, dict)
                else list(parse_qs(source))
                if isinstance(source, str)
                else []
            )
            try:
                observer(method, req.url, resp, time.monotonic() - started, fields)
            except Exception:
                import logging

                logging.getLogger("console").warning(
                    "Could not save a redacted request diagnostic"
                )
        if cookie_error:
            raise cookie_error
        # X login uses redirects for navigation; only safe GET redirects are followed,
        # each hop is validated again by the gateway. Never replay a write.
        if method == "GET" and resp.is_redirect and kwargs.get("allow_redirects", True):
            hops = kwargs.pop("_hops", 0)
            if hops >= 5:
                raise RuntimeError("Too many X redirects")
            target = urljoin(req.url, resp.headers["location"])
            if urlsplit(target).hostname != host:
                kwargs["headers"] = {
                    k: v
                    for k, v in headers.items()
                    if k.lower() not in ("authorization", "cookie", "x-csrf-token")
                }
                kwargs.pop("cookies", None)
            kwargs.pop("params", None)
            return self.request("GET", target, _hops=hops + 1, **kwargs)
        return resp

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def request(method, url, **kwargs):
    with Session() as session:
        return session.request(method, url, **kwargs)
