# -*- coding: utf-8 -*-
"""X 登录。

**主路径：`XJetfuelLoginApi`（web jetfuel 流，端点在 `jf.x.com`）——浏览器登录流已实测跑通。
Castle 的完整纯算组装已单独落在 `utils.castle_token.generate_pure`，显式提供同一浏览器
状态下完整的 `Rl` 向量（旧版 632 槽、当前 x-web 版 749 槽）时，登录类可用 Python 直接调用 Chromium-zlib profile；默认
仍使用 Node runner（仅作兼容回退）。鉴权只需 web 公开 bearer +
`x-guest-token`，不需要 XCTID / x-csrf-token / OAuth2Session。

**保留：`XLoginApi`（mobile onboarding 状态机）**——历史死路，撞硬件设备证明
（App Attest / Play Integrity），仅供对照与未来复用，说明见下。

---

⚠️ 以下针对 **mobile 路径** 的现状说明（该路径走不通，被服务端设备证明 attestation 挡住）：

X 目前对「用户名+密码」登录做了两道设备证明墙，两条客户端路径各撞一道：

| 路径 | bearer / 端点 | 卡在哪 |
|---|---|---|
| **web**（老 onboarding） | web bearer + `x.com/i/api/1.1/onboarding/task.json` | 提交用户名即 399「Could not log you in now」 |
| **mobile**（Android/iOS） | 移动 bearer + `api.x.com/1.1/onboarding/task.json` | **能过用户名+密码输入**，密码校验时 399「LoginError.AttestationDenied」 |

**mobile 路径走得最远**——无需 ui_metrics、无需 jetfuel，一路推进到密码校验，
只在最后撞上 `AttestationDenied`（硬件级、离机不可伪造）。web jetfuel 流则不撞它，
只需软件令牌 castle_token，故为现行主路径。

推荐纯算用法：`XJetfuelLoginApi.login_by_password_pure(用户名, 密码, profile)`；
`login_by_password(..., pure_rl_values=profile, pure_required=True)` 等价。
不带 profile 的 `login_by_password` 仅保留给明确的旧兼容调用；或用
`XAuth.prepare_auth(cookie串)` 注入浏览器会话。
"""

import gzip
import re
import urllib.parse

import requests

from builder import client
from builder.auth import GUEST_ACTIVATE_URL, PUBLIC_BEARER, XAuth
from utils import castle_token
from utils.fingerprint import get_profile
from utils.transaction import ClientTransaction
from utils.x_util import (cookies_to_str, generate_client_uuid, generate_ct0,
                          trans_cookies)

# 老 onboarding 端点（web 与 mobile 复用同一状态机，差别在 bearer / header / body 形态）
API_BASE = 'https://api.x.com'
TASK_URL = f'{API_BASE}/1.1/onboarding/task.json'
GUEST_URL = f'{API_BASE}/1.1/guest/activate.json'

# 公开的移动端 bearer（X Android/iOS 客户端硬编码值）。mobile 路径必须用它——
# 用 web bearer 会走进被关停的 SSO 分支。
ANDROID_BEARER = ('Bearer AAAAAAAAAAAAAAAAAAAAAFXzAwAAAAAAMHCxpeSDG1gLNLghVe8d74hl6k4'
                  '%3DRUMF4xAQLsbeBhTSRrCiQpJtxoGWeyHrDb5te2jpGskWDFW82F')
ANDROID_UA = ('TwitterAndroid/10.10.0-release.0 (310100000-r-0) SM-G991B/12 '
              '(samsung;SM-G991B;samsung;o1s;0;;1;2013)')

# 需要用户额外输入的 subtask —— 遇到就把控制权交回调用方
CHALLENGE_SUBTASKS = {
    'LoginAcid': '需要邮箱/手机验证码',
    'LoginTwoFactorAuthChallenge': '需要两步验证动态码',
    'ArkoseLogin': '触发 Arkose 人机验证',
    'DenyLoginSubtask': '服务端拒绝本次登录',
    'LoginEnterAlternateIdentifierSubtask': '需要补充手机号/邮箱确认身份',
}


class LoginChallenge(Exception):
    """登录被风控挑战打断。`subtask_id` / `flow_token` 供调用方续跑。"""

    def __init__(self, subtask_id, message, flow_token, payload=None):
        super().__init__(f'{subtask_id}: {message}')
        self.subtask_id = subtask_id
        self.flow_token = flow_token
        self.payload = payload


class LoginFailed(Exception):
    pass


class LoginRateLimited(LoginFailed):
    """服务端明确要求退避；不是 Castle/token 字段校验失败。"""


class LoginAttestationBlocked(LoginFailed):
    """撞上 App Attest / Play Integrity 设备证明墙（LoginError.AttestationDenied）。

    这是硬件级信任根，离机不可伪造，纯算无解。用浏览器 cookie 注入会话代替。
    """


# jetfuel 挑战 action 名的人类可读描述（子串匹配；仅用于提示，不参与控制流判定）
_JF_CHALLENGE_MARKERS = {
    'two_factor': '需要两步验证动态码',
    'verification': '需要邮箱/手机验证码',
    'acid': '需要邮箱/手机验证码',
    'arkose': '触发 Arkose 人机验证',
    'deny': '服务端拒绝本次登录',
    'alternate': '需要补充手机号/邮箱确认身份',
}


class XJetfuelLoginApi:
    """web jetfuel 登录流（`jf.x.com`）：浏览器实抓流程已跑通；纯算 native 压缩已接入。

    要点（DevTools 实抓 + 纯算复现）：

        - 端点在独立子域 `jf.x.com`，路径 `/onboarding/web/actions/{begin_login,login_enter_password}`。
        - 鉴权使用 web 公开 bearer + `x-guest-token` + 每步新算的 XCTID；不带 x-csrf-token /
          OAuth2Session。
        - 每一步一枚**新鲜** `$castle_token`（默认 Node runner；完整 `Rl` 向量或按 action 提供
      raw profile 时可显式走 Python 纯算 native profile）。
    - `login_enter_password` 成功后 `Set-Cookie` 下发 `auth_token` + `twid`；
      jetfuel 不下发 ct0，前端本就是自造（双提交），这里缺失即 `generate_ct0()`。
    """

    # 2026-09-23 Chrome Preserve log 实抓：jetfuel 端点在独立子域 jf.x.com。
    # referer/origin 仍来自 https://x.com/，因此 sec-fetch-site 为 same-site；
    # 每一步都带 x-client-transaction-id。
    JF_HOST = 'https://jf.x.com'
    JF_BASE = f'{JF_HOST}/onboarding/web'
    # 2026-10-24 HAR: the landing route is /onboarding/web with mode=login.
    LANDING_URL = f'{JF_BASE}?redirect_after_login=%2Fhome&mode=login'
    PASSKEY_URL = f'{JF_BASE}/remotes/passkey_one_fa'
    LOGIN_PAGE_URL = 'https://x.com/i/jf/onboarding/web?redirect_after_login=%2Fhome&mode=login'
    ACTION_BASE = f'{JF_BASE}/actions/'
    BEGIN_URL = f'{ACTION_BASE}begin_login'
    ENTER_PWD_URL = f'{ACTION_BASE}login_enter_password'
    # XCTID 按 pathname 现算，这里给出 action 的 path 前缀
    ACTION_PATH = '/onboarding/web/actions/'
    # 浏览器实抓的 referer（不是 jf.x.com 页面地址）
    PAGE_URL = 'https://x.com/'
    # curl_cffi 当前最高可用的 Chrome transport profile 为 150；应用层 UA/UA-CH
    # 在 _headers() 中显式覆盖为当前真实 Chrome 153，避免登录流出现两套画像。
    LOGIN_ACCEPT_LANGUAGE = 'zh-cn'
    LOGIN_CLIENT_LANGUAGE = 'zh-cn'
    LOGIN_IMPERSONATE = 'chrome150'

    _UUID_RE = re.compile(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
    # jetfuel 是服务端驱动流：响应体内联「下一步 action 路径」，用它续跑（不硬编码挑战名）
    # 路径现在是 /i/jfapi/onboarding/web/actions/<name>（同源）
    _ACTION_RE = re.compile(
        rb'(?:https?://jf\.x\.com/)?(?:i/jfapi/)?'
        rb'onboarding/web/actions/([a-z_]+)')
    # 导航/备选 action，不是主推进步骤
    _ALT_ACTIONS = {'begin_login', 'begin_password_recovery'}

    def __init__(self, proxies: dict = None, browser_cookies: dict = None,
                 castle_snapshot: dict = None, pure_rl_values=None,
                 pure_required: bool = False):
        self.proxies = proxies
        self.castle_snapshot = castle_snapshot
        # Explicit pure-computation opt-in.  The value may be a complete
        # Complete 632-slot legacy or 749-slot current Rl profile/list/mapping,
        # or a zero-argument callable returning one
        # for each action.  A callable is the intended way to refresh the
        # capture timestamp and other per-token signals between steps.
        if pure_required and pure_rl_values is None:
            raise ValueError(
                'pure_required=True 需要完整 Rl/raw profile；拒绝回退 Node runner')
        self._validate_pure_profile_shape(pure_rl_values)
        self.pure_rl_values = pure_rl_values
        self.session = client.session(impersonate=self.LOGIN_IMPERSONATE)
        self.auth = XAuth(proxies=proxies)
        # A strict Castle profile already proves this is an offline/pure
        # computation path.  XCTID's public animation materials are likewise
        # deterministic; seed the verified local capture immediately so login
        # does not first perform an unrelated shell download that can be reset
        # by the network edge.
        if pure_rl_values is not None:
            try:
                self.auth._transaction = ClientTransaction.from_cached()
            except (OSError, TypeError, ValueError):
                # Keep the normal network construction as a fallback when a
                # caller deliberately supplies a different XCTID profile.
                pass
        self.guest_token = ''
        # A browser capture may contain one raw serialized signal blob per
        # action.  Castle changes a small subset of the 749 slots between
        # createRequestToken() calls, so keeping an action-indexed sequence
        # prevents a stale first capture from being silently reused for every
        # step.  A single profile remains fully supported.
        self._pure_sequence_index = 0
        self._pure_action_indices = {}
        # A serialized profile contains Castle-side signal values, while the
        # transport still needs the page's visible client id.  When callers
        # pass a profile directly, carry localStorage.__cuid into the same
        # cookie jar (the CLI handles cookie-string captures separately).
        profile_storage = {}
        if isinstance(pure_rl_values, dict):
            storage = (pure_rl_values.get('localStorage')
                       or pure_rl_values.get('local_storage'))
            if isinstance(storage, dict):
                profile_storage = storage
        cookie_seed = dict(browser_cookies or {})
        if browser_cookies is None and isinstance(pure_rl_values, dict):
            captured = (pure_rl_values.get('browser_cookies')
                        or pure_rl_values.get('cookie'))
            if isinstance(captured, str):
                captured = trans_cookies(captured)
            if isinstance(captured, dict):
                cookie_seed.update({
                    str(key): str(value) for key, value in captured.items()
                    if str(key) not in {'auth_token', 'twid', 'ct0'} and value
                })
        if profile_storage.get('__cuid') and not cookie_seed.get('__cuid'):
            cookie_seed['__cuid'] = str(profile_storage['__cuid'])
        # 登录页可以从一个已登录的 X 标签打开“添加已有账号”。保留该标签的
        # .x.com cookie 形状（包括 auth_token/twid/ct0），让 Castle 的
        # document.cookie 与浏览器同源上下文一致；不传则仍从干净会话开始。
        for name, value in cookie_seed.items():
            if value:
                self.session.cookies.set(name, value, domain='.x.com', path='/')

    # ---- 传输 ----------------------------------------------------------- #

    def _headers(self, form: bool = False, xctid_path: str = None,
                 method: str = 'POST', referer: str = None) -> dict:
        """jetfuel **跨子域** fetch 请求头，字段与顺序逐项对齐浏览器实抓（2026-09-23）。

        实抓顺序（landing / begin_login / login_enter_password 一致）::

            x-jf-client-theme → authorization → referer → accept-language →
            timezone → x-twitter-client-language → x-twitter-active-user →
            x-client-transaction-id →
            x-guest-token → x-jf-v → content-type

        当前 jf.x.com 跨子域请求的要点：

        - `sec-fetch-site` 是 **same-site**；
        - **每一步（含 landing 的 GET）都要带** `x-client-transaction-id`；
        - `x-twitter-client-language` 与浏览器页面语言一致（本次实抓为 `zh-cn`）；
        - `referer` 是 `https://x.com/`。

        curl_cffi(impersonate) 仍会补 user-agent / accept-encoding / priority。
        """
        profile = get_profile()
        headers = {
            'x-jf-client-theme': 'light',
            'authorization': PUBLIC_BEARER,
            'referer': referer or self.PAGE_URL,
            'accept-language': self.LOGIN_ACCEPT_LANGUAGE,
            'timezone': profile['timezone'],
            'x-twitter-client-language': self.LOGIN_CLIENT_LANGUAGE,
            'x-twitter-active-user': 'yes',
            # curl_cffi 的 transport 仍用 chrome150，但真实登录页是 Chrome 153；
            # 这些字段必须显式跟随页面画像，不能交给 impersonate 默认值。
            'user-agent': profile['ua'],
            'sec-ch-ua': profile['sec_ch_ua'],
            'sec-ch-ua-mobile': profile['sec_ch_ua_mobile'],
            'sec-ch-ua-platform': profile['sec_ch_ua_platform'],
            'priority': 'u=1, i',
        }
        if xctid_path:
            headers['x-client-transaction-id'] = \
                self.auth.client_transaction_id(method, xctid_path)
        headers['x-guest-token'] = self.guest_token
        headers['x-jf-v'] = 'JP-5'
        if form:
            headers['content-type'] = 'application/x-www-form-urlencoded'
        headers.update({
            'origin': 'https://x.com',
            'accept': '*/*',
            'sec-fetch-site': 'same-site',
            'sec-fetch-mode': 'cors',
            'sec-fetch-dest': 'empty',
            # 真实 fetch 不带这些导航专属头（curl_cffi 模板会塞，置 None 删掉）。
            'upgrade-insecure-requests': None,
            'sec-fetch-user': None,
        })
        return headers

    @staticmethod
    def _navigation_headers() -> dict:
        """Document-navigation headers for the initial x.com landing GET.

        The session transport still uses curl_cffi's chrome150 TLS template, so
        the application-level Chrome 153 UA/Client Hints must be explicit here
        as well.  The action endpoints use :meth:`_headers` (fetch mode) instead.
        """
        profile = get_profile()
        return {
            'user-agent': profile['ua'],
            'sec-ch-ua': profile['sec_ch_ua'],
            'sec-ch-ua-mobile': profile['sec_ch_ua_mobile'],
            'sec-ch-ua-platform': profile['sec_ch_ua_platform'],
            'accept': ('text/html,application/xhtml+xml,application/xml;q=0.9,'
                       'image/avif,image/webp,image/apng,*/*;q=0.8'),
            'accept-language': profile['accept_language'],
            'priority': 'u=0, i',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'none',
            'upgrade-insecure-requests': '1',
        }

    @staticmethod
    def _decode(raw: bytes) -> list:
        """jetfuel 响应：「长度字节 + 内容」TLV 串。curl_cffi 一般已 gunzip，兜底再解一次。"""
        body = raw
        if raw[:2] == b'\x1f\x8b':
            try:
                body = gzip.decompress(raw)
            except Exception:
                body = raw
        out, i, n = [], 0, len(body)
        while i < n:
            ln = body[i]
            if 1 <= ln <= 255 and i + 1 + ln <= n:
                chunk = body[i + 1:i + 1 + ln]
                # 现行 jetfuel 错误文案可能是 UTF-8 中文；旧实现只接收
                # ASCII，导致“我们已临时限制你的登录”被丢掉，进而把真实
                # 限流误报成 Castle/字段错误。保留可打印 ASCII，同时接受
                # 没有控制字符的有效 UTF-8 文本。
                try:
                    text = chunk.decode('utf-8')
                except UnicodeDecodeError:
                    text = None
                if text and len(text) >= 1 and not any(
                        (ord(ch) < 32 and ch not in '\\t\\r\\n') for ch in text):
                    if len(text) >= 3 or any(ord(ch) > 127 for ch in text):
                        out.append(text)
                        i += 1 + ln
                        continue
            i += 1
        return out

    def _cookies(self) -> dict:
        return {c.name: c.value for c in self.session.cookies.jar}

    def _classify_failure(self, strings: list, status: int, text: str = '',
                          headers=None):
        """把非成功响应翻译成限流 / 挑战 / 失败，抛对应异常。"""
        blob = ' '.join(strings).lower()
        # jetfuel 的错误正文是 TLV，限流文案在中文页面不会出现 ``limit``；
        # 同时保留英文/状态码判断，避免把 200 + errors 误报成 Castle 参数错。
        full_blob = f'{blob} {text or ""}'.lower()
        rate_markers = (
            'imit', 'rate limit', 'temporarily limited',
            '临时限制', '暂时限制', '暂时被限制', '登录限制',
            '稍后重试', '稍后再试',
        )
        if status == 429 or any(marker in full_blob for marker in rate_markers):
            headers = headers or {}
            retry_after = headers.get('retry-after')
            reset_at = headers.get('x-rate-limit-reset')
            hint = ''
            if retry_after or reset_at:
                hint = f'，retry-after={retry_after or "?"}'
                if reset_at:
                    hint += f'，x-rate-limit-reset={reset_at}'
            raise LoginRateLimited(
                f'登录限流（status={status}）{hint}，退避后重试：{strings[:8]}')
        for marker, desc in _JF_CHALLENGE_MARKERS.items():
            if marker in blob:
                raise LoginChallenge(marker, desc, flow_token=None, payload=strings)
        raise LoginFailed(f'status={status}: {strings[:12] or text[:200]}')

    # ---- 解码 / 续跑基元 ------------------------------------------------- #

    @staticmethod
    def _decompress(raw: bytes) -> bytes:
        if raw[:2] == b'\x1f\x8b':
            try:
                return gzip.decompress(raw)
            except Exception:
                return raw
        return raw

    @classmethod
    def _next_actions(cls, body: bytes) -> list:
        """从（解压后的）响应体按出现顺序抽出服务端给的 action 名（去重）。
        jetfuel 自描述下一步，续跑不靠硬编码挑战名。"""
        seen, out = set(), []
        for match in cls._ACTION_RE.findall(body):
            name = match.decode()
            if name not in seen:
                seen.add(name)
                out.append(name)
        return out

    def _extract_session_token(self, strings: list):
        for i, s in enumerate(strings):
            if s == 'session_token' and i + 1 < len(strings) \
                    and self._UUID_RE.fullmatch(strings[i + 1]):
                return strings[i + 1]
        for s in strings:
            if self._UUID_RE.fullmatch(s):
                return s
        return None

    def _post_action(self, action: str, fields: dict) -> dict:
        """向 x.com/i/jfapi/onboarding/web/actions/<action> 提交 fields
        （自动附新鲜 castle_token）。返回 {status, strings, actions, session_token, resp}。

        XCTID 按该 action 的**真实 pathname** 现算——同源之后每步都要带这个头。
        """
        # 纯算仍复用同一 requests 会话的可见页面状态：Castle 的采集器会读取
        # document.cookie / localStorage.__cuid。不能把它留空，否则长度偶尔接近，
        # 但设备画像与浏览器请求并不相同。
        cookies = self._cookies()
        cookie_str = '; '.join(f'{k}={v}' for k, v in cookies.items() if v)
        local_storage = {}
        if cookies.get('__cuid'):
            local_storage['__cuid'] = cookies['__cuid']
        if self.pure_rl_values is not None:
            rl_values = self._pure_profile_for_action(action)
            token = castle_token.generate_pure(rl_values)
        else:
            token = castle_token.generate(cookie=cookie_str,
                                          local_storage=local_storage,
                                          snapshot=self.castle_snapshot)
        body = self._encode_form(fields, token)
        headers = self._headers(form=True, xctid_path=self.ACTION_PATH + action)
        resp = self.session.post(self.ACTION_BASE + action, headers=headers,
                                 data=body, proxies=self.proxies, timeout=30)
        strings = self._decode(resp.content)
        return {
            'status': resp.status_code,
            'strings': strings,
            'actions': self._next_actions(self._decompress(resp.content)),
            'session_token': self._extract_session_token(strings),
            'resp': resp,
        }

    @staticmethod
    def _encode_form(fields: dict, token: str) -> str:
        """Encode a jetfuel form in browser insertion order.

        ``URLSearchParams`` appends ``$castle_token`` after the action fields;
        passing an ordered pair list makes that contract explicit and keeps
        `$`/`+`/`/`/`=` percent-encoding identical to Python's
        application/x-www-form-urlencoded implementation.
        """
        pairs = list(fields.items())
        pairs.append(('$castle_token', token))
        return urllib.parse.urlencode(pairs)

    def _pure_profile_for_action(self, action: str):
        """Select the captured pure profile for one jetfuel action.

        ``pure_rl_values`` historically accepted one complete ``Rl`` vector
        or one serialized ``raw`` blob.  A current browser can vary a small
        set of signals on each Castle call, so captures may additionally use
        either of these JSON shapes::

            {"raw_by_action": {"begin_login": {...},
                               "login_enter_password": {...}}}
            {"raw_sequence": [{...}, {...}]}

        The camelCase spellings ``rawByAction``/``rawSequence`` are accepted
        for browser-exported JSON.  Each selected item is passed unchanged to
        ``generate_pure``; outer ``prefix`` metadata is inherited when the
        item omits it.  A callable still has highest priority and can return a
        fresh vector/blob/profile for every request.
        """
        source = self.pure_rl_values() if callable(self.pure_rl_values) \
            else self.pure_rl_values
        self._validate_pure_profile_shape(source)
        if not isinstance(source, dict):
            return source

        by_action = source.get('raw_by_action') or source.get('rawByAction')
        if isinstance(by_action, dict):
            selected = (by_action.get(action) or by_action.get('default')
                        or by_action.get('*'))
            if selected is not None:
                return self._inherit_profile_metadata(source, selected)

        sequence = source.get('raw_sequence') or source.get('rawSequence')
        if isinstance(sequence, (list, tuple)) and sequence:
            index = min(self._pure_sequence_index, len(sequence) - 1)
            self._pure_sequence_index += 1
            return self._inherit_profile_metadata(source, sequence[index])
        return source

    @staticmethod
    def _inherit_profile_metadata(container: dict, selected):
        if not isinstance(selected, dict):
            return selected
        inherited = {
            key: container[key] for key in (
                'prefix', 'compression', 'inner_variant',
                'timestamp_ms', 'timestamp')
            if key in container and key not in selected
        }
        if not inherited:
            return selected
        return {**inherited, **selected}

    @staticmethod
    def _validate_pure_profile_shape(profile) -> None:
        """Reject action profiles that cannot cover the password flow."""
        if not isinstance(profile, dict):
            return
        by_action = profile.get('raw_by_action') or profile.get('rawByAction')
        if isinstance(by_action, dict):
            has_default = any(key in by_action for key in ('default', '*'))
            missing = [name for name in ('begin_login', 'login_enter_password')
                       if name not in by_action]
            if missing and not has_default:
                raise ValueError(
                    'raw_by_action 缺少登录步骤: ' + ', '.join(missing))
        sequence = profile.get('raw_sequence') or profile.get('rawSequence')
        if isinstance(sequence, (list, tuple)) and len(sequence) < 2:
            raise ValueError('raw_sequence 至少需要 begin_login 和 login_enter_password 两枚 profile')

    def _primary_next(self, step: dict):
        """本步响应里的主 next action（排除导航/备选）；没有则 None。"""
        for name in step['actions']:
            if name not in self._ALT_ACTIONS:
                return name
        return None

    def _describe_challenge(self, action: str) -> str:
        low = action.lower()
        for marker, desc in _JF_CHALLENGE_MARKERS.items():
            if marker in low:
                return f'{action}：{desc}'
        return f'{action}：需要额外输入/验证，用 submit_action 续跑'

    # ---- 各步 ----------------------------------------------------------- #

    def _prime(self):
        """建立会话，按浏览器实抓的顺序走一遍预热请求（2026-08-16）：

            GET /                                   拿 Cloudflare / 访客 cookie
            GET https://jf.x.com/onboarding/web/landing
            GET https://jf.x.com/onboarding/web/remotes/passkey_one_fa?form_id=landing

        每个 GET 都带 XCTID（同源之后浏览器就是这么发的）。
        """
        self.session.get(self.LOGIN_PAGE_URL, headers=self._navigation_headers(),
                         proxies=self.proxies, timeout=30)
        # 浏览器带的客户端 cookie：dnt 偏好 + __cuid 前端设备 id（本地生成）
        self.session.cookies.set('dnt', '1', domain='.x.com')
        if not self._cookies().get('__cuid'):
            self.session.cookies.set('__cuid', generate_client_uuid(), domain='.x.com')
        self.guest_token = self._cookies().get('gt', '')
        if not self.guest_token:
            resp = self.session.post(GUEST_ACTIVATE_URL,
                                     headers={'authorization': PUBLIC_BEARER},
                                     proxies=self.proxies, timeout=30)
            self.guest_token = resp.json().get('guest_token', '')
            if self.guest_token:
                self.session.cookies.set('gt', self.guest_token, domain='.x.com')

        for url, path in (
            (self.LANDING_URL, '/onboarding/web'),
            (self.PASSKEY_URL, '/onboarding/web/remotes/passkey_one_fa'),
        ):
            self.session.get(url,
                             headers=self._headers(xctid_path=path, method='GET'),
                             proxies=self.proxies, timeout=30)

    def submit_action(self, action: str, fields: dict, session_token: str = None) -> dict:
        """通用续跑：任何 jetfuel 步骤都能这样推进（验证码 / 2FA 等挑战）。

        自动附新鲜 castle_token；给了 session_token 就带上。返回 `_post_action` 结果 dict
        （`status` / `strings` / `actions` / `session_token`）。供挑战续跑用。
        """
        payload = dict(fields)
        if session_token:
            payload.setdefault('session_token', session_token)
        return self._post_action(action, payload)

    def begin_login(self, username: str) -> str:
        """提交用户名，拿 session_token（下一步一般是 login_enter_password）。"""
        step = self._post_action('begin_login', {'username_or_email': username, 'password': ''})
        if step['status'] != 200 or not step['session_token']:
            self._classify_failure(step['strings'], step['status'], step['resp'].text,
                                   step['resp'].headers)
        return step['session_token']

    def enter_password(self, username: str, password: str, session_token: str) -> list:
        """提交密码，成功后会话 cookie（auth_token/twid）落到 session.cookies。"""
        step = self._post_action('login_enter_password', {
            'username': username, 'password': password, 'session_token': session_token})
        if step['status'] != 200:
            self._classify_failure(step['strings'], step['status'], step['resp'].text,
                                   step['resp'].headers)
        return step['strings']

    # ---- 编排 ----------------------------------------------------------- #

    def login(self, username: str, password: str, on_challenge=None,
              max_steps: int = 8) -> XAuth:
        """跑完整条流，成功后返回带会话 cookie 的 XAuth。

        流程**服务端驱动**：每步响应内联下一步 action。密码步自动走；遇到需要用户输入的挑战
        （验证码 / 2FA 等）时——给了 `on_challenge(action, strings) -> dict` 就回调取值并续跑，
        没给就抛 `LoginChallenge`（带 action 名 + session_token，调用方可用 `submit_action` 续跑）。
        """
        self._prime()
        step = self._post_action('begin_login', {'username_or_email': username, 'password': ''})
        if step['status'] != 200 or not step['session_token']:
            self._classify_failure(step['strings'], step['status'], step['resp'].text,
                                   step['resp'].headers)
        session_token = step['session_token']

        for _ in range(max_steps):
            if self._cookies().get('auth_token') or 'login_success' in step['strings']:
                break
            if 'errors' in step['strings']:  # 限流 / 密码错 / 风控——别重试，直接翻译抛出
                self._classify_failure(step['strings'], step['status'], step['resp'].text,
                                       step['resp'].headers)

            action = self._primary_next(step)
            if action == 'login_enter_password':
                step = self._post_action('login_enter_password', {
                    'username': username, 'password': password,
                    'session_token': session_token})
            elif action:  # 需要用户输入的挑战——响应自描述了 action
                if on_challenge is None:
                    raise LoginChallenge(action, self._describe_challenge(action),
                                         flow_token=session_token, payload=step['strings'])
                values = on_challenge(action, step['strings']) or {}
                step = self._post_action(action, {**values, 'session_token': session_token})
            else:
                self._classify_failure(step['strings'], step['status'] or 200,
                                       step['resp'].text, step['resp'].headers)

            if step['status'] != 200:
                self._classify_failure(step['strings'], step['status'], step['resp'].text,
                                       step['resp'].headers)
            session_token = step['session_token'] or session_token
        else:
            raise LoginFailed(f'{max_steps} 步内没登录成功：{step["strings"][:12]}')

        cookies = self._cookies()
        if not cookies.get('auth_token') and 'login_success' not in step['strings']:
            self._classify_failure(step['strings'], 200,
                                   step['resp'].text, step['resp'].headers)

        self.auth.cookie = {k: v for k, v in cookies.items() if v}
        if not self.auth.cookie.get('ct0'):
            # jetfuel 不下发 ct0，前端本就是自造随机值（CSRF 双提交），这里补一个
            self.auth.cookie['ct0'] = generate_ct0()
        self.auth.cookie.setdefault('lang', self.LOGIN_CLIENT_LANGUAGE)
        self.auth.cookie_str = cookies_to_str(self.auth.cookie)
        if not self.auth.auth_token:
            raise LoginFailed(f'走到 login_success 但没拿到 auth_token：{step["strings"]}')
        return self.auth

    @staticmethod
    def login_by_password(username: str, password: str, proxies: dict = None,
                          on_challenge=None, browser_cookies: dict = None,
                          castle_snapshot: dict = None, pure_rl_values=None,
                          pure_required: bool = False):
        """:return: (success, msg, auth)。`on_challenge(action, strings)->dict` 可选，
        用于自动续跑验证码 / 2FA 等挑战（不传则命中挑战抛 LoginChallenge 交回人工）。

        `pure_rl_values` 是显式的纯算开关：传入同一浏览器页面抓到的完整
        `Rl` profile（旧版 632 槽/当前 749 槽）、raw profile（可按 action 分配），或一个每次返回
        新向量的无参 callable，即不启动 Node runner；不传则保持默认浏览器兼容 runner 路径。纯算入口当前实现的是
        Python 纯算默认使用 bundled Chromium-zlib native profile；只有显式调用
        `generate_pure(..., compression='fallback')` 才使用 Castle fallback。"""
        api = XJetfuelLoginApi(proxies=proxies, browser_cookies=browser_cookies,
                               castle_snapshot=castle_snapshot,
                               pure_rl_values=pure_rl_values,
                               pure_required=pure_required)
        try:
            return True, '成功', api.login(username, password, on_challenge=on_challenge)
        except LoginChallenge as exc:
            return False, f'需要人工处理：{exc}', api.auth
        except Exception as exc:
            return False, f'{type(exc).__name__}: {exc}', api.auth

    @staticmethod
    def login_by_password_pure(username: str, password: str, pure_rl_values,
                               proxies: dict = None, on_challenge=None,
                               browser_cookies: dict = None):
        """Strict Python-native login; never falls back to the Node runner.

        This is the public convenience wrapper for callers that want the
        objective's pure-computation contract rather than the legacy
        compatibility behavior of :meth:`login_by_password`.
        """
        if pure_rl_values is None:
            raise ValueError('login_by_password_pure requires pure_rl_values')
        return XJetfuelLoginApi.login_by_password(
            username, password, proxies=proxies, on_challenge=on_challenge,
            browser_cookies=browser_cookies, pure_rl_values=pure_rl_values,
            pure_required=True)


class XLoginApi:
    """Android onboarding 状态机。一次登录一个实例。"""

    def __init__(self, proxies: dict = None):
        self.proxies = proxies
        self.session = requests.Session()
        self.auth = XAuth(proxies=proxies)
        self.guest_token = None
        self.att = None
        self.flow_token = None

    # ---- 传输 ----------------------------------------------------------- #

    def _headers(self) -> dict:
        """移动客户端头。不带 XCTID —— 移动端不算这个头。"""
        headers = {
            'authorization': ANDROID_BEARER,
            'content-type': 'application/json',
            'user-agent': ANDROID_UA,
            'accept-encoding': 'gzip',
            'x-twitter-client-language': 'en',
            'x-twitter-active-user': 'yes',
            'x-twitter-api-version': '5',
            'x-twitter-client': 'TwitterAndroid',
            'x-twitter-client-version': '10.10.0',
            'os-version': '12',
            'system-user-agent': ANDROID_UA,
        }
        if self.guest_token:
            headers['x-guest-token'] = self.guest_token
        # att 是服务端下发的一次性流令牌，后续每步要原样回传
        if self.att:
            headers['att'] = self.att
        return headers

    def _post(self, body: dict = None, params: dict = None) -> dict:
        resp = self.session.post(TASK_URL, headers=self._headers(), params=params,
                                 json=body, proxies=self.proxies, timeout=30)
        if resp.headers.get('att'):
            self.att = resp.headers['att']
        self.auth.update_cookies(resp.cookies)
        if resp.status_code >= 400:
            if 'AttestationDenied' in resp.text:
                raise LoginAttestationBlocked(
                    'LoginError.AttestationDenied：撞上 App Attest / Play Integrity '
                    '设备证明墙，硬件级不可离机伪造。请用浏览器 cookie 注入会话，'
                    '请改用浏览器 cookie 注入会话')
            raise LoginFailed(f'{resp.status_code}: {resp.text[:300]}')
        data = resp.json()
        if data.get('flow_token'):
            self.flow_token = data['flow_token']
        return data

    def _submit(self, subtask_id: str, payload: dict) -> dict:
        return self._post({
            'flow_token': self.flow_token,
            'subtask_inputs': [{'subtask_id': subtask_id, **payload}],
        })

    # ---- 状态机各步 ------------------------------------------------------ #

    def start(self) -> dict:
        resp = self.session.post(GUEST_URL, headers=self._headers(),
                                 proxies=self.proxies, timeout=30)
        resp.raise_for_status()
        self.guest_token = resp.json()['guest_token']
        return self._post(params={'flow_name': 'login'}, body={
            'flow_token': None,
            'input_flow_data': {'flow_context': {
                'debug_overrides': {},
                'start_location': {'location': 'splash_screen'}}}})

    def _enter_username(self, subtask_id: str, username: str) -> dict:
        # Android 用 enter_text（web SSO 用 settings_list，两者不通用）
        return self._submit(subtask_id, {
            'enter_text': {'text': username, 'link': 'next_link'}})

    def _enter_password(self, subtask_id: str, password: str) -> dict:
        return self._submit(subtask_id, {
            'enter_password': {'password': password, 'link': 'next_link'}})

    def _duplication_check(self, subtask_id: str) -> dict:
        return self._submit(subtask_id, {
            'check_logged_in_account': {'link': 'AccountDuplicationCheck_false'}})

    def _js_instrumentation(self, subtask_id: str) -> dict:
        # 移动流一般不下发这一步；万一下发，回空对象即可（移动端不校验内容）
        return self._submit(subtask_id, {
            'js_instrumentation': {'response': '{}', 'link': 'next_link'}})

    # ---- 编排 ------------------------------------------------------------ #

    def login(self, username: str, password: str, max_steps: int = 12) -> XAuth:
        """跑完整条状态机，成功后返回带会话 cookie 的 XAuth。"""
        data = self.start()

        for _ in range(max_steps):
            subtasks = data.get('subtasks') or []
            if not subtasks:
                raise LoginFailed(f'状态机没有下一步：{data}')
            subtask_id = subtasks[0]['subtask_id']

            if subtask_id == 'LoginSuccessSubtask':
                break
            if subtask_id in CHALLENGE_SUBTASKS:
                raise LoginChallenge(subtask_id, CHALLENGE_SUBTASKS[subtask_id],
                                     self.flow_token, data)

            if subtask_id in ('LoginEnterUserIdentifier', 'LoginEnterUserIdentifierSSO'):
                data = self._enter_username(subtask_id, username)
            elif subtask_id == 'LoginEnterPassword':
                data = self._enter_password(subtask_id, password)
            elif subtask_id == 'AccountDuplicationCheck':
                data = self._duplication_check(subtask_id)
            elif subtask_id == 'LoginJsInstrumentationSubtask':
                data = self._js_instrumentation(subtask_id)
            else:
                raise LoginChallenge(subtask_id, '未知 subtask，需要人工确认',
                                     self.flow_token, data)
        else:
            raise LoginFailed(f'状态机在 {max_steps} 步内没有走到登录成功')

        self._absorb_success(data)
        if not self.auth.auth_token:
            raise LoginFailed(f'走到 LoginSuccess 但没拿到 auth_token：{data}')
        self.auth.cookie_str = cookies_to_str(self.auth.cookie)
        if not self.auth.ct0:
            self.auth.cookie['ct0'] = generate_ct0()
        return self.auth

    def _absorb_success(self, data: dict):
        """LoginSuccessSubtask 里的 open_account 带 oauth token / 会话信息，
        合并进 auth（移动流的会话有时不走 Set-Cookie，而在 body 里给）。"""
        for subtask in data.get('subtasks', []):
            account = subtask.get('open_account')
            if not account:
                continue
            user = account.get('user') or {}
            if user.get('id_str'):
                self.auth.cookie['twid'] = f'u%3D{user["id_str"]}'

    # ---- 便捷入口 -------------------------------------------------------- #

    @staticmethod
    def login_by_password(username: str, password: str, proxies: dict = None):
        """:return: (success, msg, auth)"""
        api = XLoginApi(proxies=proxies)
        try:
            return True, '成功', api.login(username, password)
        except LoginChallenge as exc:
            return False, f'需要人工处理：{exc}', api.auth
        except Exception as exc:
            return False, f'{type(exc).__name__}: {exc}', api.auth
