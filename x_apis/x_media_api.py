# -*- coding: utf-8 -*-
"""XMediaAPI：媒体三段式上传（INIT → APPEND → FINALIZE →（视频）STATUS 轮询）。

发图文推的前置步骤：先把图片传成 media_id，再把 media_id 交给 CreateTweet。

**请求形态逐字段对齐浏览器实抓**，
有三处和「想当然的写法」不一样：

1. 命令参数（command / total_bytes / media_id / segment_index）走 **query string**，
   不是 form body；只有 APPEND 的分片数据在 multipart body 里。
2. `FINALIZE` 带 **original_md5**（整个文件的 md5 十六进制）。
3. 上传接口**不带** `x-client-transaction-id` —— XCTID 中间件的 host 白名单是
   `(jf|grok|api|mobile).(twitter|x).com`，`upload.x.com` 不在其中。
   多带一个头反而与真实客户端不一致。
"""

import hashlib
import os
import time

from builder import client
from builder.header import HeaderBuilder, HeaderType

UPLOAD_URL = 'https://upload.x.com/i/media/upload.json'
METADATA_URL = 'https://x.com/i/api/1.1/media/metadata/create.json'
# 单片 4MB，X 对每个 APPEND 分片有大小上限
CHUNK_SIZE = 4 * 1024 * 1024

MIME_BY_EXT = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
    '.gif': 'image/gif', '.webp': 'image/webp',
    '.mp4': 'video/mp4', '.mov': 'video/quicktime',
}

CATEGORY_BY_MIME = {
    'image/gif': 'tweet_gif',
    'video/mp4': 'tweet_video',
    'video/quicktime': 'tweet_video',
}


def guess_media_type(path: str) -> str:
    return MIME_BY_EXT.get(os.path.splitext(path)[1].lower(), 'image/jpeg')


def guess_media_category(media_type: str) -> str:
    return CATEGORY_BY_MIME.get(media_type, 'tweet_image')


def _upload_headers(auth):
    """浏览器上传时只带这三个头（外加浏览器自动补的通用头）。"""
    return (HeaderBuilder.build(HeaderType.UPLOAD)
            .with_bearer(auth)
            .with_csrf(auth)
            .with_auth_type(auth)
            .set_referer('https://x.com/')
            .get())


class XMediaAPI:

    @staticmethod
    def init(auth, total_bytes: int, media_type: str,
             media_category: str = None, **kwargs) -> str:
        """申请一个 media_id。参数走 query string。"""
        params = {
            'command': 'INIT',
            'total_bytes': str(total_bytes),
            'media_type': media_type,
            'media_category': media_category or guess_media_category(media_type),
        }
        resp = client.post(UPLOAD_URL, headers=_upload_headers(auth),
                           cookies=auth.cookie, params=params,
                           proxies=auth.proxies, timeout=60)
        resp.raise_for_status()
        return resp.json()['media_id_string']

    @staticmethod
    def append(auth, media_id: str, chunk: bytes, segment_index: int, **kwargs):
        """上传一个分片：命令走 query，分片数据走 multipart body。

        curl_cffi ≥ 0.7 移除了 `files=` 参数，改用 `CurlMime` 对象。
        """
        from builder import gateway
        if gateway.enabled():
            resp = client.post(
                UPLOAD_URL, headers=_upload_headers(auth), cookies=auth.cookie,
                params={'command': 'APPEND', 'media_id': media_id, 'segment_index': str(segment_index)},
                files={'media': ('blob', chunk, 'application/octet-stream')},
                proxies=auth.proxies, timeout=120)
            resp.raise_for_status()
            return resp
        from curl_cffi import CurlMime
        mime = CurlMime()
        mime.addpart(name='media', data=chunk,
                     content_type='application/octet-stream', filename='blob')
        resp = client.post(
            UPLOAD_URL, headers=_upload_headers(auth), cookies=auth.cookie,
            params={'command': 'APPEND', 'media_id': media_id,
                    'segment_index': str(segment_index)},
            multipart=mime,
            proxies=auth.proxies, timeout=120)
        resp.raise_for_status()
        return resp

    @staticmethod
    def finalize(auth, media_id: str, original_md5: str = None, **kwargs) -> dict:
        """收尾。浏览器会带整文件的 md5，服务端用它校验分片拼装结果。"""
        params = {'command': 'FINALIZE', 'media_id': media_id}
        if original_md5:
            params['original_md5'] = original_md5
        resp = client.post(UPLOAD_URL, headers=_upload_headers(auth),
                           cookies=auth.cookie, params=params,
                           proxies=auth.proxies, timeout=60)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def metadata_create(auth, media_id: str, allow_download: bool = True,
                        referer: str = 'https://x.com/home', **kwargs):
        """提交上传媒体的下载权限元数据。

        Chrome 在 FINALIZE 成功后、CreateTweet 之前固定发这一条 JSON 请求。
        图片和视频都走同一个 endpoint；响应为空，因此只校验 HTTP 状态并返回
        response 对象，不能调用 ``json()``。
        """
        path = '/i/api/1.1/media/metadata/create.json'
        headers = (HeaderBuilder.build(HeaderType.POST)
                   .with_bearer(auth)
                   .with_csrf(auth)
                   .with_auth_type(auth)
                   .with_client_language(auth)
                   .with_xctid(auth, 'POST', path)
                   .set_referer(referer)
                   .get())
        body = {
            'media_id': str(media_id),
            'allow_download_status': {
                'allow_download': 'true' if allow_download else 'false',
            },
        }
        resp = client.post(METADATA_URL, headers=headers, cookies=auth.cookie,
                           json=body, proxies=auth.proxies, timeout=60)
        resp.raise_for_status()
        return resp

    @staticmethod
    def status(auth, media_id: str, **kwargs) -> dict:
        resp = client.get(UPLOAD_URL, headers=_upload_headers(auth),
                          cookies=auth.cookie,
                          params={'command': 'STATUS', 'media_id': media_id},
                          proxies=auth.proxies, timeout=60)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def wait_processing(auth, media_id: str, finalize_result: dict,
                        timeout: int = 180) -> dict:
        """视频要等服务端转码完成才能发推；图片没有 processing_info，直接返回。"""
        info = (finalize_result or {}).get('processing_info')
        deadline = time.time() + timeout
        while info and info.get('state') in ('pending', 'in_progress'):
            if time.time() > deadline:
                raise TimeoutError(f'媒体 {media_id} 转码超时')
            time.sleep(max(info.get('check_after_secs', 1), 1))
            result = XMediaAPI.status(auth, media_id)
            info = result.get('processing_info')
            finalize_result = result
        if info and info.get('state') == 'failed':
            raise RuntimeError(f'媒体 {media_id} 转码失败：{info.get("error")}')
        return finalize_result

    @staticmethod
    def upload(auth, file_path: str, media_category: str = None, **kwargs) -> str:
        """完整上传一个本地文件，返回 media_id。"""
        with open(file_path, 'rb') as fp:
            payload = fp.read()
        media_type = guess_media_type(file_path)
        media_id = XMediaAPI.init(auth, len(payload), media_type, media_category)
        for index, offset in enumerate(range(0, len(payload), CHUNK_SIZE)):
            XMediaAPI.append(auth, media_id, payload[offset:offset + CHUNK_SIZE], index)
        result = XMediaAPI.finalize(auth, media_id,
                                    original_md5=hashlib.md5(payload).hexdigest())
        XMediaAPI.wait_processing(auth, media_id, result)
        # 文章编辑器（封面 / 正文插图）上传完 FINALIZE 就结束，
        # 不发 metadata/create（2026-09-27 实抓），用 with_metadata=False 对齐。
        if not kwargs.get('with_metadata', True):
            return media_id
        # 网页端无论图片还是视频，发帖前都会登记下载权限元数据。
        # 这一步漏掉时，媒体虽已 FINALIZE 成功，但 CreateTweet 的媒体状态
        # 与浏览器不同，某些账号会被服务端拒绝或降级。
        XMediaAPI.metadata_create(
            auth, media_id,
            allow_download=kwargs.get('allow_download', True),
            referer=kwargs.get('referer', 'https://x.com/home'))
        return media_id

    @staticmethod
    def upload_many(auth, file_paths, **kwargs) -> list:
        """批量上传。传单个路径字符串时按一个文件处理，
        避免误当成可迭代对象逐字符上传。"""
        if isinstance(file_paths, str):
            file_paths = [file_paths]
        return [XMediaAPI.upload(auth, path, **kwargs) for path in (file_paths or [])]
