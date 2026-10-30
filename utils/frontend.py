# -*- coding: utf-8 -*-
"""读取 X 线上前端（app shell HTML + webpack 分片）的唯一入口。

X 目前同时在跑两套前端：

- `abs.twimg.com/x-web/x-web/*`  —— 2026 新栈（rolldown + TanStack Router + Relay），
  只负责**未登录营销落地页**（`https://x.com/` 裸访问）。
- `abs.twimg.com/responsive-web/client-web/*` —— 老 webpack 栈，**仍然是真正的 app shell**，
  `/i/flow/login`、时间线、发推等全部业务都在这套里。

本项目只关心后者：XCTID 生成器（`ondemand.s`）和 GraphQL 操作注册表（`queryId` + `features`）
都住在这里，而且 app shell HTML 里内联了完整的 webpack chunk 清单，
所以**纯 HTTP 就能枚举到全部分片**，不需要开浏览器。
"""

import re
import os

import requests

from utils.fingerprint import get_profile

SHELL_URL = 'https://x.com/i/flow/login'
ASSET_BASE = 'https://abs.twimg.com/responsive-web/client-web/'

_META_RE = re.compile(
    r'<meta[^>]+name=["\']twitter-site-verification["\'][^>]+content=["\']([^"\']+)["\']')
_ANIM_RE = re.compile(r'id=["\']loading-x-anim-(\d)["\'][^>]*>(.*?)</svg>', re.S)
_PATH_D_RE = re.compile(r'<path[^>]*\bd=["\']([^"\']+)["\']')
# Webpack emits numeric object keys in either decimal form (``59924``) or
# JavaScript's exponent form (for example ``9e3`` for 9000).  The latter is
# valid JavaScript but was not matched by the original decimal-only parser.
_CHUNK_ENTRY_RE = re.compile(r'([0-9]+(?:e[0-9]+)?):"([^"]*)"')
_ENTRY_SCRIPT_RE = re.compile(
    r'https://abs\.twimg\.com/responsive-web/client-web/([\w.~\-/]+\.js)')
_NAME_MAP_ANCHOR = re.compile(r'\d{1,6}:"ondemand\.s"')
# Hashes used to be seven hexadecimal characters; current client-web builds
# use 16 (and may change length again).  Anchor on a pair of hexadecimal
# values instead of a fixed width, while allowing exponent-form chunk IDs.
_HASH_MAP_ANCHOR = re.compile(
    r'\{[0-9]+(?:e[0-9]+)?:"[0-9a-f]{8,64}",'
    r'[0-9]+(?:e[0-9]+)?:"[0-9a-f]{8,64}"')


def shell_headers() -> dict:
    profile = get_profile()
    return {
        'user-agent': profile['ua'],
        'accept': ('text/html,application/xhtml+xml,application/xml;q=0.9,'
                   'image/avif,image/webp,*/*;q=0.8'),
        'accept-language': profile['accept_language'],
        'sec-ch-ua': profile['sec_ch_ua'],
        'sec-ch-ua-mobile': profile['sec_ch_ua_mobile'],
        'sec-ch-ua-platform': profile['sec_ch_ua_platform'],
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'none',
        'upgrade-insecure-requests': '1',
    }


def fetch_shell_html(session: requests.Session = None, proxies: dict = None) -> str:
    """拉取 app shell HTML（含 XCTID 素材 + webpack chunk 清单）。

    X currently A/B routes ``/i/flow/login`` between the legacy client-web
    shell and the newer jetfuel shell. Only the former contains the XCTID
    materials; retry a few times when the latter is selected instead of
    treating an otherwise healthy 200 response as permanent drift.
    """
    from builder import client
    get = (session or client).get
    last_url = SHELL_URL
    # ``/i/flow/login`` is currently A/B-routed between the legacy
    # client-web shell (which contains the XCTID materials) and the newer
    # x-web shell (which does not).  Five tries still occasionally lose to
    # the rollout; use a bounded larger retry budget so a transient A/B draw
    # does not abort an otherwise valid pure-login request.
    max_attempts = max(1, min(12, int(os.getenv('X_SHELL_ATTEMPTS', '12'))))
    for _ in range(max_attempts):
        resp = get(SHELL_URL, headers=shell_headers(), proxies=proxies, timeout=30)
        resp.raise_for_status()
        html = resp.text
        last_url = getattr(resp, 'url', SHELL_URL)
        if 'responsive-web/client-web' in html:
            return html
    raise RuntimeError(
        f'连续 {max_attempts} 次 app shell 都返回非 client-web 页面，'
        f'最后响应为 {last_url}；前端结构可能已变')


def parse_site_verification(html: str) -> str:
    """XCTID 的 key 素材：base64 编码的 48 字节。"""
    match = _META_RE.search(html)
    if not match:
        raise RuntimeError('app shell 里没有 twitter-site-verification meta')
    return match.group(1)


def parse_animation_frames(html: str) -> list:
    """4 个 `loading-x-anim-*` 的第 2 条 `<path d>`，按 id 升序返回。"""
    frames = {}
    for index, svg_body in _ANIM_RE.findall(html):
        paths = _PATH_D_RE.findall(svg_body)
        if len(paths) >= 2:
            frames[int(index)] = paths[1]
    if len(frames) < 4:
        raise RuntimeError(f'只解析到 {len(frames)} 个动画帧，期望 4 个')
    return [frames[i] for i in sorted(frames)]


def _enclosing_object(text: str, pos: int) -> str:
    """取出包含 pos 的那一对花括号内容。chunk 表的值里不含花括号，直接配对即可。"""
    start = text.rindex('{', 0, pos)
    depth, index = 0, start
    while index < len(text):
        if text[index] == '{':
            depth += 1
        elif text[index] == '}':
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
        index += 1
    raise RuntimeError('花括号不配对，无法定位 chunk 表')


def _normalize_chunk_id(raw: str) -> str:
    """Normalize a JavaScript numeric object key to its decimal spelling.

    In minified webpack runtime objects, ``9e3`` is the numeric literal 9000,
    so property lookup against a decimal name-table key must use ``"9000"``.
    Keep ordinary decimal IDs untouched and avoid floating-point conversion.
    """
    if 'e' not in raw:
        return raw
    coefficient, exponent = raw.split('e', 1)
    return str(int(coefficient) * (10 ** int(exponent)))


def parse_chunk_manifest(html: str) -> dict:
    """还原 webpack 的 `__webpack_require__.u`：chunk 名 → 完整 URL。

    内联 runtime 里有两张按 chunkId 排的表：`{id: "chunk名"}` 与 `{id: "7位hash"}`。
    最终文件名是 `<名>.<hash>a.js` —— 尾部那个 `a` 是前端模板里拼死的，
    所以表里存的 hash 比文件名少一位。没登记名字的 chunk 用数字 id 兜底。

    必须锚定到这两张表本体再取值：HTML 里还有 `__INITIAL_STATE__` 等大量
    `数字:"字符串"` 结构，全局扫描会把无关键值对混进来，导致拼出 404 的 URL。
    """
    name_anchor = _NAME_MAP_ANCHOR.search(html)
    if not name_anchor:
        raise RuntimeError('app shell 里找不到 webpack chunk 名字表')
    names = {
        _normalize_chunk_id(key): value
        for key, value in _CHUNK_ENTRY_RE.findall(
            _enclosing_object(html, name_anchor.start()))
    }

    hash_anchor = _HASH_MAP_ANCHOR.search(html, name_anchor.end())
    if not hash_anchor:
        raise RuntimeError('app shell 里找不到 webpack chunk hash 表')
    hashes = {
        _normalize_chunk_id(key): value
        for key, value in _CHUNK_ENTRY_RE.findall(
            _enclosing_object(html, hash_anchor.start() + 1))
    }

    return {names.get(cid, cid): f'{ASSET_BASE}{names.get(cid, cid)}.{digest}a.js'
            for cid, digest in hashes.items()}


def parse_entry_scripts(html: str) -> dict:
    """HTML 里直接 `<script src>` 引用的入口包（main / vendor / prelude …）。

    这些不走 `__webpack_require__.u`，**不在 chunk 清单里**，但恰恰是 GraphQL 操作
    注册表的主要落点（`main.*.js` 一个人就装了一百多个操作）。
    """
    entries = {}
    for filename in _ENTRY_SCRIPT_RE.findall(html):
        name = re.sub(r'\.\w{8}\.js$', '', filename)
        entries[name] = ASSET_BASE + filename
    return entries


def parse_all_assets(html: str) -> dict:
    """入口包 + 全部 chunk，合成一张「本次发版的全部 JS」清单。"""
    assets = parse_chunk_manifest(html)
    assets.update(parse_entry_scripts(html))
    return assets


def fetch_chunk(url: str, session: requests.Session = None, proxies: dict = None) -> str:
    from builder import client
    get = (session or client).get
    resp = get(url, headers={'user-agent': get_profile()['ua'],
                             'accept': '*/*',
                             'referer': 'https://x.com/'},
               proxies=proxies, timeout=60)
    resp.raise_for_status()
    return resp.text
