"""Bound request bodies before multipart parsing, including chunked uploads."""

import tempfile
from starlette.responses import JSONResponse


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        limit = (
            55 * 1024 * 1024 if scope["path"].endswith("/media") else 2 * 1024 * 1024
        )
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as body:
            total = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                total += len(chunk)
                if total > limit:
                    return await JSONResponse({"detail": "请求体超过大小限制"}, 413)(
                        scope, receive, send
                    )
                body.write(chunk)
                if not message.get("more_body", False):
                    break
            body.seek(0)
            remaining = total
            delivered = False

            async def replay():
                nonlocal remaining, delivered
                if delivered:
                    return await receive()
                if remaining:
                    chunk = body.read(1024 * 1024)
                    remaining -= len(chunk)
                    delivered = not remaining
                    return {
                        "type": "http.request",
                        "body": chunk,
                        "more_body": bool(remaining),
                    }
                delivered = True
                return {"type": "http.request", "body": b"", "more_body": False}

            await self.app(scope, replay, send)
