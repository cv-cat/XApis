# -*- coding: utf-8 -*-
"""XAuth：**所有动态鉴权状态的唯一持有者**。

对齐 ../Spider_XHS 的 Auth 设计——API 方法只从 auth 取值，
不在方法体里出现 cookie / token / 签名素材，
彻底干掉旧代码里 `(authorization, x_csrf_token, cookies_str)` 三件套满天飞的写法。

状态分为用户输入、本地纯算和服务端下发三类：

- **用户输入**：cookie 串（或用户名密码，走 login_api）。
- **本地纯算**：ct0（缺失时自己生成）、XCTID 生成器。
- **服务端下发**：guest_token、登录后的 auth_token / ct0。
"""

import time

from utils.fingerprint import get_profile
from utils.transaction import ClientTransaction
from utils.x_util import cookies_to_str, generate_ct0, trans_cookies

# X web 公开的固定 bearer，**不是用户身份**，所有 web 接口都带这一个值。
# 取自线上 main.*.js，随前端发版极少变动。
PUBLIC_BEARER = ('Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs'
                 '%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA')

GUEST_ACTIVATE_URL = 'https://api.x.com/1.1/guest/activate.json'
# guest_token 服务端有效期远大于此，这里只是防止长跑进程用到陈旧值
_GUEST_TTL = 3 * 3600


class XAuth:
    def __init__(self, bearer: str = PUBLIC_BEARER, proxies: dict = None):
        self.bearer = bearer
        self.proxies = proxies
        self.cookie = {}
        self.cookie_str = ''
        self._guest_token = ''
        self._guest_ts = 0.0
        self._transaction = None

    # ---- 装配 ----------------------------------------------------------- #

    def prepare_auth(self, cookies_str: str = ''):
        """用一串浏览器 cookie 初始化会话。

        ct0 既是 Cookie 也要原样进 `x-csrf-token` 头，两处必须一致。
        未登录态服务端接受任意自洽的 ct0，缺失就本地生成；
        但**已登录会话的 ct0 是服务端签发的，不能自己造**——
        造一个随机值会让所有写接口和鉴权读接口静默失败在 CSRF 校验上，
        所以这里直接报错，让调用方把 cookie 复制全。
        """
        self.cookie = trans_cookies(cookies_str)
        if not self.cookie.get('ct0'):
            if self.cookie.get('auth_token'):
                raise ValueError(
                    'cookie 里有 auth_token 但缺 ct0。已登录会话的 ct0 由服务端签发，'
                    '不能本地生成，请把浏览器 cookie 完整复制过来')
            self.cookie['ct0'] = generate_ct0()
        # lang cookie 决定 x-twitter-client-language 头，两处必须一致
        self.cookie.setdefault('lang', get_profile()['client_language'])
        self.cookie_str = cookies_to_str(self.cookie)
        return self

    # ---- 只读属性 ------------------------------------------------------- #

    @property
    def ct0(self) -> str:
        return self.cookie.get('ct0', '')

    @property
    def auth_token(self) -> str:
        return self.cookie.get('auth_token', '')

    @property
    def is_logged_in(self) -> bool:
        return bool(self.auth_token)

    @property
    def user_id(self) -> str:
        """twid cookie 形如 `u%3D1718802931036622848`。"""
        twid = self.cookie.get('twid', '')
        return twid.replace('u%3D', '').replace('u=', '').strip('"')

    # ---- 服务端下发状态 -------------------------------------------------- #

    @property
    def guest_token(self) -> str:
        """惰性换取 guest_token；已登录会话不需要它。"""
        now = time.time()
        if self._guest_token and now - self._guest_ts < _GUEST_TTL:
            return self._guest_token
        self.refresh_guest_token()
        return self._guest_token

    @guest_token.setter
    def guest_token(self, value: str):
        if value:
            self._guest_token = value
            self._guest_ts = time.time()

    def refresh_guest_token(self) -> str:
        from builder import client
        from builder.header import HeaderBuilder, HeaderType

        headers = HeaderBuilder.build(HeaderType.FORM).with_bearer(self).get()
        resp = client.post(GUEST_ACTIVATE_URL, headers=headers,
                           proxies=self.proxies, timeout=30)
        resp.raise_for_status()
        self.guest_token = resp.json()['guest_token']
        self.cookie['gt'] = self._guest_token
        self.cookie_str = cookies_to_str(self.cookie)
        return self._guest_token

    # ---- 签名 ----------------------------------------------------------- #

    @property
    def transaction(self) -> ClientTransaction:
        """XCTID 生成器。素材（key / 动画帧 / 下标）在一次会话内稳定，只装配一次。"""
        if self._transaction is None:
            try:
                self._transaction = ClientTransaction.from_network(
                    # Public signing-material requests are anonymous. Login HTML
                    # clears ct0; that deletion must not alter the account session.
                    proxies={k: v for k, v in (self.proxies or {}).items()
                             if k != '_on_cookies'} or None)
            except Exception:
                # The token algorithm is local; only its public animation
                # materials are fetched.  If that unrelated shell fetch is
                # reset, use the explicitly captured local profile instead of
                # preventing the real jetfuel request from being attempted.
                self._transaction = ClientTransaction.from_cached()
        return self._transaction

    def client_transaction_id(self, method: str, path: str) -> str:
        return self.transaction.generate(method.upper(), path)

    def refresh_transaction(self):
        """前端发版后素材会失效，调用这个强制重建。"""
        self._transaction = None
        return self.transaction

    # ---- 会话更新 -------------------------------------------------------- #

    def update_cookies(self, new_cookies):
        """把响应里的 Set-Cookie 合并回会话（登录流每一步都会下发新值）。"""
        if hasattr(new_cookies, 'get_dict'):
            new_cookies = new_cookies.get_dict()
        for key, value in dict(new_cookies).items():
            if value:
                self.cookie[key] = value
        self.cookie_str = cookies_to_str(self.cookie)
        return self
