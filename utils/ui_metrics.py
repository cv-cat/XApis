# -*- coding: utf-8 -*-
"""ui_metrics：登录流 `LoginJsInstrumentationSubtask` 的 JS 指纹挑战。

服务端下发一段每次随机重命名的混淆 JS（`/i/js_inst?c_name=ui_metrics`），
要求回传它的执行结果。**服务端是延后校验的**——提交 JS 挑战那一步永远返回
success，真正的判定发生在下一步（提交用户名），不合格就报
399「Could not log you in now」。

脚本的计算部分只用到算术与 `Date`，唯一的宿主依赖是把结果写进
`document.getElementsByName('ui_metrics')`，所以给一组最小 DOM 桩、用 Node 跑一次即可，
**不需要浏览器**（桩在 static/ui_metrics.js）。

与 ../Spider_XHS 一样，把「必须由 JS 引擎执行」的那一小段隔离在 Node 侧，
Python 侧只负责取素材和拼请求。
"""

import os
import subprocess
import tempfile

import requests

from utils.fingerprint import get_profile

JS_INST_URL = 'https://x.com/i/js_inst?c_name=ui_metrics'
RUNNER = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'static', 'ui_metrics.js'))
NODE = os.environ.get('NODE_BIN', 'node')


def fetch_challenge(session: requests.Session = None, proxies: dict = None,
                    url: str = None) -> str:
    from builder import client
    get = (session or client).get
    resp = get(url or JS_INST_URL,
               headers={'user-agent': get_profile()['ua'],
                        'accept': '*/*',
                        'referer': 'https://x.com/'},
               proxies=proxies, timeout=30)
    resp.raise_for_status()
    return resp.text


def solve(script: str) -> str:
    """跑挑战脚本，返回要回传的 ui_metrics 字符串（JSON 文本）。"""
    path = None
    try:
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False,
                                         encoding='utf-8') as fp:
            fp.write(script)
            path = fp.name
        result = subprocess.run([NODE, RUNNER, path], capture_output=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(
                f'ui_metrics 求解失败（exit={result.returncode}）：'
                f'{result.stderr.decode("utf-8", "replace")[:400]}')
        return result.stdout.decode('utf-8', 'replace').strip()
    except FileNotFoundError as exc:
        raise RuntimeError(
            f'找不到 node 可执行文件（{NODE}），登录流的 ui_metrics 需要它；'
            f'可用环境变量 NODE_BIN 指定路径') from exc
    finally:
        if path and os.path.exists(path):
            os.unlink(path)


def build(session: requests.Session = None, proxies: dict = None,
          url: str = None) -> str:
    """取素材 + 求解，一步到位。"""
    return solve(fetch_challenge(session, proxies, url))
