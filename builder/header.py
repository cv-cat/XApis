# -*- coding: utf-8 -*-
"""请求头建造器：X 专属签名头集中在这一处生成，并**按浏览器顺序输出**。

浏览器自动补的头（user-agent / sec-ch-ua* / accept / accept-language /
sec-fetch-* / priority / accept-encoding）不在这里写——它们由传输层
`builder/client.py` 的 Chrome impersonate 注入，版本与 TLS 自洽。
这里只写 X 前端 fetch 里**显式设置**的那几个头，且 `get()` 会把它们
排成与浏览器实抓一致的顺序。

用法对齐 ../DouYin_Spider/builder/header.py 的链式风格::

    headers = (HeaderBuilder.build(HeaderType.POST)
               .with_bearer(auth).with_csrf(auth).with_auth_type(auth)
               .with_client_language(auth).with_xctid(auth, 'POST', api)
               .set_referer(url).get())
"""

from enum import Enum

from utils.fingerprint import get_profile

# X 前端设置头的顺序**因请求族而异**（2026-08-16 Chrome DevTools 实抓）。
# 三族各不相同，不能混用：
#
#   GraphQL   : content-type 在**最前**
#   REST GET  : **完全没有** content-type（GET 没 body，前端不设）
#   REST POST : content-type 在 active-user 之后、xctid 之前（第 6 位）
#
# 早期版本用同一个顺序发所有请求，REST 族因此既错位又多带 content-type。
_GRAPHQL_ORDER = [
    'content-type', 'authorization', 'x-twitter-auth-type', 'x-csrf-token',
    'x-twitter-client-language', 'x-twitter-active-user', 'x-client-transaction-id',
    'x-guest-token', 'x-att', 'origin', 'referer',
]
# REST GET（/i/api/1.1/hashflags.json、/i/api/fleets/v1/fleetline 实抓）：无 content-type。
_REST_GET_ORDER = [
    'x-twitter-polling', 'authorization', 'x-twitter-auth-type', 'x-csrf-token',
    'x-twitter-client-language', 'x-twitter-active-user', 'x-client-transaction-id',
    'x-guest-token', 'x-att', 'origin', 'referer',
]
# REST POST form（/i/api/1.1/graphql/viewer_context.json、/1.1/flow/viewer.json、
# friendships/*.json 实抓）：content-type 夹在 active-user 与 xctid 之间。
_REST_FORM_ORDER = [
    'authorization', 'x-twitter-auth-type', 'x-csrf-token',
    'x-twitter-client-language', 'x-twitter-active-user', 'content-type',
    'x-client-transaction-id', 'x-guest-token', 'x-att', 'origin', 'referer',
]
# 媒体上传：upload.x.com 的 fetch 头顺序自成一族（2026-08-16 实抓 INIT/APPEND/FINALIZE
# 三条请求，顺序完全一致）：authorization 在最前，referer 夹在 auth-type 与 csrf 之间，
# 且**不带** x-client-transaction-id / x-twitter-client-language / x-twitter-active-user。
# APPEND 的 content-type（multipart/form-data; boundary=...）由传输层按 body 自动生成。
_UPLOAD_ORDER = [
    'authorization', 'x-twitter-auth-type', 'referer', 'x-csrf-token',
    'content-type', 'origin',
]
# 文档导航（登录落地页）：交给 impersonate 即可，这里保留少量显式头。
_DOC_ORDER = [
    'upgrade-insecure-requests', 'sec-fetch-dest', 'sec-fetch-mode',
    'sec-fetch-site', 'sec-fetch-user', 'origin', 'referer',
]


class HeaderType(Enum):
    GET = 'GET'        # GraphQL query via GET（有 content-type，排第一）
    POST = 'POST'      # GraphQL mutation / query via POST JSON body
    REST_GET = 'REST_GET'  # REST GET（/1.1/* /fleets/* 等，无 content-type）
    FORM = 'FORM'      # REST POST form-encoded（friendships / flow 等）
    UPLOAD = 'UPLOAD'  # upload.x.com 多段上传
    DOC = 'DOC'        # 文档导航（登录落地页）


class Header:
    def __init__(self, order=None):
        self.headers = {}
        self._order = order or _GRAPHQL_ORDER

    def set_header(self, key, value):
        self.headers[key] = value
        return self

    def remove_header(self, key):
        self.headers.pop(key, None)
        return self

    def set_referer(self, url):
        return self.set_header('referer', url)

    def set_origin(self, url='https://x.com'):
        return self.set_header('origin', url)

    def with_bearer(self, auth):
        return self.set_header('authorization', auth.bearer)

    def with_csrf(self, auth):
        """ct0 必须与 Cookie 里的同名值完全一致，否则服务端判 CSRF 失败。"""
        return self.set_header('x-csrf-token', auth.ct0)

    def with_guest(self, auth):
        return self.set_header('x-guest-token', auth.guest_token)

    def with_xctid(self, auth, method: str, path: str):
        """`x-client-transaction-id`：每个请求一次性，按 (method, path) 现算。

        path 必须是**不含 query 的 pathname**——前端就是这么算的，带上 query 会校验不过。
        """
        value = auth.client_transaction_id(method, path)
        # Signing-material initialization may perform reads. Take csrf from the
        # same final auth state that will supply the outgoing Cookie header.
        if 'x-csrf-token' in self.headers:
            self.headers['x-csrf-token'] = auth.ct0
        return self.set_header('x-client-transaction-id', value)

    def with_att(self, auth):
        """登录流专用：服务端第一步下发 `att` Cookie，后续每步原样回传成 `x-att` 头。"""
        att = auth.cookie.get('att')
        if att:
            self.set_header('x-att', att)
        return self

    def with_client_language(self, auth):
        """`x-twitter-client-language` 与会话 cookie 的 `lang` 一致。"""
        lang = (auth.cookie.get('lang') or '').lower()
        if lang:
            self.set_header('x-twitter-client-language', lang)
        return self

    def with_auth_type(self, auth):
        """已登录会话才带 `x-twitter-auth-type`；未登录带上反而会被拒。"""
        if auth.is_logged_in:
            self.set_header('x-twitter-auth-type', 'OAuth2Session')
        return self

    def get(self):
        """按浏览器顺序输出。未登记的键按字母序追加在后面。"""
        rank = {k: i for i, k in enumerate(self._order)}
        end = len(self._order)
        keys = sorted(self.headers, key=lambda k: (rank.get(k, end), k))
        return {k: self.headers[k] for k in keys}

    def __call__(self):
        return self.get()


class HeaderBuilder:
    profile = get_profile()
    ua = profile['ua']
    sec_ch_ua = profile['sec_ch_ua']
    sec_ch_ua_platform = profile['sec_ch_ua_platform']

    @staticmethod
    def build(header_type: HeaderType) -> Header:
        """按请求类型给出基础头（只含 X 专属头；浏览器通用头由传输层 impersonate 注入）。

        字段与顺序逐项对齐浏览器实抓：
        - GraphQL（GET/POST）：content-type 排第一，其后是签名头；
        - REST_GET：**不带 content-type**（GET 无 body，前端就不设）；
        - FORM：REST POST 表单，content-type 在 active-user 之后、xctid 之前；
        - UPLOAD：只有 authorization / x-twitter-auth-type / x-csrf-token；
        - DOC：登录落地页导航头。
        """
        if header_type == HeaderType.DOC:
            header = Header(order=_DOC_ORDER)
            header.headers.update({
                'upgrade-insecure-requests': '1',
                'sec-fetch-dest': 'document',
                'sec-fetch-mode': 'navigate',
                'sec-fetch-site': 'none',
                'sec-fetch-user': '?1',
            })
            return header

        if header_type == HeaderType.UPLOAD:
            # 上传走 upload.x.com（跨子域），multipart boundary 由传输层生成，不写 content-type。
            header = Header(order=_UPLOAD_ORDER)
            header.set_origin('https://x.com')
            return header

        if header_type == HeaderType.REST_GET:
            # 实抓：REST GET 只有签名头，没有 content-type。
            header = Header(order=_REST_GET_ORDER)
            header.set_header('x-twitter-active-user', 'yes')
            return header

        if header_type == HeaderType.FORM:
            header = Header(order=_REST_FORM_ORDER)
            header.set_header('x-twitter-active-user', 'yes')
            header.set_header('content-type',
                              'application/x-www-form-urlencoded; charset=UTF-8')
            return header

        # GraphQL：GET 与 POST 同一套顺序，content-type 恒为 application/json。
        header = Header(order=_GRAPHQL_ORDER)
        header.set_header('x-twitter-active-user', 'yes')
        header.set_header('content-type', 'application/json')
        return header
