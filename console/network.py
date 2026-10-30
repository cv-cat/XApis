"""Bounded HTTP with DNS pinning, no redirects or implicit proxy credentials."""

import ipaddress
import json
import os
import socket
from urllib.parse import urlsplit
import urllib3


class RemoteError(ValueError):
    pass


def target(url, allow_private=False):
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("https", "http")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or any(c in url for c in ("\r", "\n", "\\"))
    ):
        raise RemoteError("请输入不含账号密码的完整 HTTP(S) 地址")
    host = parsed.hostname.encode("idna").decode("ascii")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    allowed = {
        s.strip().lower()
        for s in os.getenv("CONSOLE_PRIVATE_AI_HOSTS", "").split(",")
        if s.strip()
    }
    private_ok = allow_private and host.lower() in allowed
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        }
    except OSError:
        raise RemoteError("无法解析服务器地址") from None
    if not addresses or (
        not private_ok and any(not ipaddress.ip_address(a).is_global for a in addresses)
    ):
        raise RemoteError("禁止访问内网地址；本地 AI 服务需在部署配置中显式放行主机名")
    return parsed, host, port, sorted(addresses)[0]


def fetch(url, *, payload=None, api_key=None, allow_private=False, limit=2_000_000):
    parsed, host, port, address = target(url, allow_private)
    headers = {
        "Host": parsed.netloc,
        "User-Agent": "XApis-Console/1.0",
        "Accept": "application/json,application/rss+xml,application/atom+xml,text/html,*/*",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = None
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    kwargs = dict(
        host=address,
        port=port,
        timeout=urllib3.Timeout(connect=10, read=60),
        retries=False,
    )
    pool = (
        urllib3.HTTPSConnectionPool(
            **kwargs,
            server_hostname=host,
            assert_hostname=host,
            cert_reqs="CERT_REQUIRED",
        )
        if parsed.scheme == "https"
        else urllib3.HTTPConnectionPool(**kwargs)
    )
    response = None
    try:
        response = pool.urlopen(
            "POST" if body is not None else "GET",
            (parsed.path or "/") + ("?" + parsed.query if parsed.query else ""),
            body=body,
            headers=headers,
            redirect=False,
            preload_content=False,
        )
        if 300 <= response.status < 400:
            raise RemoteError("地址发生重定向，请填写最终地址（不会转发 API 密钥）")
        if response.status >= 400:
            raise RemoteError(
                f"远端服务返回 HTTP {response.status}，请检查地址、授权或限额"
            )
        chunks, size = [], 0
        for chunk in response.stream(65536, decode_content=True):
            size += len(chunk)
            if size > limit:
                raise RemoteError("远端响应过大，已停止读取")
            chunks.append(chunk)
        return b"".join(chunks), response.headers.get("Content-Type", "")
    except urllib3.exceptions.HTTPError:
        raise RemoteError("远端连接失败或超时，请检查网络和服务状态") from None
    finally:
        if response:
            response.close()
        pool.close()
