# -*- coding: utf-8 -*-
"""HTTP 传输层：curl_cffi + Chrome 指纹模拟。

统一走这里，让**所有读写接口**与浏览器在传输层保持一致：
- TLS 指纹（JA3/JA4）、HTTP/2 SETTINGS、伪首部顺序 = 真 Chrome；
- 浏览器自动补的头（user-agent / sec-ch-ua* / accept / accept-encoding /
  accept-language / sec-fetch-* / priority）由 impersonate 注入，版本自洽，
  不与我们写的 UA 打架；
- 我们只在 `builder/header.py` 里显式写 X 专属头（authorization / x-csrf-token /
  x-twitter-* / x-client-transaction-id / content-type），按浏览器顺序传入，
  curl_cffi 会原样保序拼在模板头之后。

接口与 requests 基本一致（get/post，返回对象有 .status_code / .json() /
.text / .content / .headers / .cookies / .raise_for_status()），
API 模块把 `import requests` 换成 `from builder import client` 即可。
"""

from urllib.parse import urlparse
import os

from curl_cffi import requests as _cffi

from utils.fingerprint import get_profile

# curl_cffi 0.16.2 当前最高可用的 Chrome profile 是 chrome150。应用层 UA/UA-CH
# 由下面的 fingerprint profile 显式覆盖为本次真实 Chrome 153；因此请求头与页面
# 画像一致，TLS/HTTP2 仍由 curl_cffi 的 chrome150 模板提供。
IMPERSONATE = 'chrome150'

# 真实浏览器 fetch/XHR 不发的导航专属头（curl_cffi 的 impersonate 模板会塞进来）。
# Client Hints 不能放在这里：本次 Chrome 153 的真实 X 请求明确带有 sec-ch-ua*，
# 并且它们必须与 user-agent 同版本。只删除导航请求专属的三个头。
_NAV_ONLY_HEADERS = ('upgrade-insecure-requests', 'sec-fetch-user')


def _sec_fetch_site(url: str) -> str:
    """按目标 host 相对 x.com 的关系给 Sec-Fetch-Site（与浏览器一致）。"""
    host = (urlparse(url).hostname or '').lower()
    if host in ('x.com', 'www.x.com'):
        return 'same-origin'
    if host.endswith('.x.com') or host == 'twitter.com' or host.endswith('.twitter.com'):
        return 'same-site'
    return 'cross-site'


def _apply_fetch_headers(url: str, kwargs: dict):
    """把请求头对齐成真实浏览器的 **fetch/XHR** 形态（而非 curl_cffi 默认的导航形态）：
    删掉导航专属头，补上 fetch 版 Sec-Fetch-*。调用方已显式设的值不覆盖。"""
    headers = dict(kwargs.get('headers') or {})
    profile = get_profile()
    # curl_cffi 的 chrome150 transport 会默认注入 Chrome 150 的画像。显式覆盖
    # 应用层字段，使 Python 与当前真实 Chrome 153 的 fetch 请求使用同一 UA/CH；
    # 调用方若有专用画像（例如 Android）仍可显式传入并优先保留。
    headers.setdefault('user-agent', profile['ua'])
    headers.setdefault('sec-ch-ua', profile['sec_ch_ua'])
    headers.setdefault('sec-ch-ua-mobile', profile['sec_ch_ua_mobile'])
    headers.setdefault('sec-ch-ua-platform', profile['sec_ch_ua_platform'])
    headers.setdefault('accept', '*/*')
    headers.setdefault('accept-language', profile['accept_language'])
    # Chrome fetch/XHR 的优先级不是 curl_cffi 导航模板的 u=0, i。
    headers.setdefault('priority', 'u=1, i')
    for key in _NAV_ONLY_HEADERS:
        headers.setdefault(key, None)  # None => curl_cffi 删除该头
    headers.setdefault('sec-fetch-site', _sec_fetch_site(url))
    headers.setdefault('sec-fetch-mode', 'cors')
    headers.setdefault('sec-fetch-dest', 'empty')
    kwargs['headers'] = headers


def get(url, **kwargs):
    _require_proxy(kwargs)
    kwargs.setdefault('impersonate', IMPERSONATE)
    _apply_fetch_headers(url, kwargs)
    from builder import gateway
    if gateway.enabled():
        return gateway.request('GET', url, **kwargs)
    if kwargs.get('proxies'):
        kwargs['proxies'] = {k:v for k,v in kwargs['proxies'].items() if not k.startswith('_')}
    return _cffi.get(url, **kwargs)


def post(url, **kwargs):
    _require_proxy(kwargs)
    kwargs.setdefault('impersonate', IMPERSONATE)
    _apply_fetch_headers(url, kwargs)
    from builder import gateway
    if gateway.enabled():
        return gateway.request('POST', url, **kwargs)
    if kwargs.get('proxies'):
        kwargs['proxies'] = {k:v for k,v in kwargs['proxies'].items() if not k.startswith('_')}
    return _cffi.post(url, **kwargs)


def session(impersonate=None):
    """需要跨请求保持 cookie（如登录流）时用。

    ``impersonate`` 可按调用链覆盖默认浏览器版本。默认仍保持全局
    ``IMPERSONATE``，登录等对版本敏感的链路可单独跟随 DevTools 实抓。
    """
    from builder import gateway
    if gateway.enabled():
        return gateway.Session()
    return _cffi.Session(impersonate=impersonate or IMPERSONATE)


def _require_proxy(kwargs):
    if os.getenv('X_REQUIRE_PROXY') == '1' and not (kwargs.get('proxies') or {}).get('https'):
        raise ValueError('必须绑定代理后才能请求 X')
