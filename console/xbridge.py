"""Narrow adapters over the existing SDK; no user-controlled Python calls or paths."""

import json
import re
from urllib.parse import urlsplit
from builder.auth import XAuth
from utils.data_util import handle_work_info
from utils.x_util import extract_cursor
from x_apis.x_api import XAPI
from x_apis.x_write_api import XWriteAPI
from x_apis.x_article_api import XArticleAPI
from x_apis.x_dm_api import XChatAPI
from x_apis.errors import GraphQLError
from console.security import require


def proxy_url(value):
    p = urlsplit(value)
    require(
        p.scheme in ("http", "https", "socks5", "socks5h")
        and p.hostname
        and p.port
        and not p.query
        and not p.fragment
        and p.path in ("", "/"),
        "请绑定完整代理地址，例如 http://用户名:密码@代理主机:端口",
    )
    require(not any(c in value for c in ("\r", "\n")), "代理地址无效")
    return value


def proxy_label(value):
    p = urlsplit(value)
    return f"{p.scheme}://{p.hostname}:{p.port}"


def auth_for(store, account):
    secret = store.decrypt(account["secret"])
    proxy = proxy_url(secret.get("proxy", ""))
    require(account["status"] == "connected", "请先绑定代理并完成账号登录", 409)
    auth = XAuth(
        proxies={"http": proxy, "https": proxy, "_account": account["id"]}
    ).prepare_auth(secret.get("cookies", ""))
    if not auth.is_logged_in:
        with store.connect() as db:
            db.execute(
                "UPDATE accounts SET status='expired' WHERE id=?", (account["id"],)
            )
            db.execute(
                "UPDATE account_maintenance SET enabled=0 WHERE account_id=?",
                (account["id"],),
            )
            db.execute(
                "UPDATE rules SET enabled=0 WHERE account_id=?", (account["id"],)
            )
            db.execute(
                "UPDATE jobs SET state='draft' WHERE account_id=? AND state='queued'",
                (account["id"],),
            )
        require(False, "X 会话已过期，请重新登录账号", 409)
    if not auth.user_id:
        auth.update_cookies({"twid": "u%3D" + account["x_id"]})
    from console.cookies import hook

    auth.proxies["_on_cookies"] = hook(
        store, account["id"], account["session_version"], lambda: auth
    )
    return auth


def profile(raw):
    if isinstance(raw, dict):
        if raw.get("rest_id") and (
            raw.get("__typename") == "User"
            or raw.get("core", {}).get("screen_name")
            or raw.get("legacy", {}).get("screen_name")
        ):
            core, legacy = raw.get("core") or {}, raw.get("legacy") or {}
            return {
                "x_id": str(raw["rest_id"]),
                "handle": core.get("screen_name") or legacy.get("screen_name", ""),
                "name": core.get("name") or legacy.get("name", ""),
                "avatar": (raw.get("avatar") or {}).get("image_url")
                or legacy.get("profile_image_url_https", ""),
                "bio": legacy.get("description", ""),
                "followers": legacy.get("followers_count", 0),
                "following": legacy.get("friends_count", 0),
                "following_me": legacy.get("followed_by", False),
                "followed": legacy.get("following", False),
            }
        for value in raw.values():
            result = profile(value)
            if result:
                return result
    elif isinstance(raw, list):
        for value in raw:
            result = profile(value)
            if result:
                return result
    return None


def timeline(raw):
    posts, users, seen, seen_users = [], [], set(), set()

    def walk(node):
        if isinstance(node, dict):
            if node.get("promotedMetadata") or node.get("entryId", "").startswith(
                "promoted"
            ):
                return
            if node.get("__typename") == "User":
                p = profile(node)
                if p and p["x_id"] not in seen_users:
                    users.append(p)
                    seen_users.add(p["x_id"])
            if node.get("rest_id") and (
                node.get("legacy", {}).get("full_text") is not None
                or node.get("__typename") == "Tweet"
            ):
                p = handle_work_info(node)
                u = profile((node.get("core") or {}).get("user_results", {})) or {}
                p.update(
                    nickname=u.get("name", p["nickname"]),
                    screen_name=u.get("handle", p["screen_name"]),
                    avatar=u.get("avatar", ""),
                    liked=node.get("legacy", {}).get("favorited", False),
                    retweeted=node.get("legacy", {}).get("retweeted", False),
                    bookmarked=node.get("legacy", {}).get("bookmarked", False),
                    reply_to_id=node.get("legacy", {}).get("in_reply_to_status_id_str"),
                    conversation_id=node.get("legacy", {}).get("conversation_id_str"),
                )
                if p["work_id"] not in seen:
                    posts.append(p)
                    seen.add(p["work_id"])
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(raw)
    return {"posts": posts, "users": users, "cursor": extract_cursor(raw)}


def discussion(raw, focal_id):
    """Separate the focal post, its ancestors and replies from TweetDetail."""
    page = timeline(raw)
    by_id = {p["work_id"]: p for p in page["posts"]}
    focal = by_id.get(focal_id)
    context, seen = [], {focal_id}
    parent = focal.get("reply_to_id") if focal else None
    while parent and parent in by_id and parent not in seen:
        seen.add(parent)
        context.insert(0, by_id[parent])
        parent = by_id[parent].get("reply_to_id")
    conversation = focal.get("conversation_id") if focal else None
    replies = [p for p in page["posts"] if p["work_id"] not in seen
               and p.get("reply_to_id")
               and (not conversation or not p.get("conversation_id") or p["conversation_id"] == conversation)]
    return {"post": focal, "context": context, "replies": replies, "cursor": page["cursor"]}


def public_raw(value):
    """X Chat responses sometimes include tokens; never return them to the browser."""
    if isinstance(value, dict):
        return {
            k: public_raw(v)
            for k, v in value.items()
            if not any(
                s in k.lower() for s in ("token", "cookie", "secret", "authorization", "passcode", "private_key", "chat_pin")
            )
        }
    if isinstance(value, list):
        return [public_raw(v) for v in value]
    return value


def safe_error(exc):
    from builder.gateway import GatewayError

    if isinstance(exc, GatewayError):
        return str(exc)
    import requests

    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        code = exc.response.status_code
        try:
            errors = exc.response.json().get("errors") or []
            if errors and errors[0].get("code") == 353:
                return "X 返回 HTTP 403 / 错误 353：CSRF Cookie 与请求头不一致，请查看登录日志"
        except (ValueError, AttributeError, TypeError):
            pass
        return {
            401: "X 会话验证失败，请重新登录",
            403: "X 拒绝访问，请检查账号验证状态或代理出口",
            429: "X 请求限流，请稍后再试",
        }.get(code, f"X 返回 HTTP {code}，请检查登录状态或接口版本")
    if isinstance(exc, GraphQLError):
        code = exc.code
        messages = {
            32: "X 登录会话已过期，请重新登录",
            89: "X 登录会话已过期，请重新登录",
            88: "X 请求限流，请稍后再试",
            226: "X 限制了此操作，请在 X 网页检查账号状态",
            344: "X 请求限流，请稍后再试",
            187: "X 检测到重复贴文",
            179: "没有权限访问此内容",
            385: "此操作需要 X Premium 权限",
        }
        return messages.get(
            code, f"X 拒绝了操作（错误码 {code or 'unknown'}），请检查账号权限与状态"
        )
    from console.network import RemoteError

    if isinstance(exc, RemoteError):
        return str(exc)
    return "上游服务请求失败或超时，请检查代理、登录状态和服务配置"


# Advanced explorer covers low-level reads that have no dedicated visual component.
READS = {
    "viewer": (XAPI.get_viewer, {}, "当前用户"),
    "tweet_result": (
        XAPI.get_work_result,
        {"work_id": "贴文 ID / 链接"},
        "贴文补充详情",
    ),
    "comments": (
        XAPI.get_work_comments,
        {"work_id": "贴文 ID / 链接", "cursor": "翻页游标（选填）"},
        "评论列表",
    ),
    "articles": (
        XArticleAPI.list_articles,
        {"lifecycle": "Draft 或 Published", "cursor": "翻页游标（选填）"},
        "文章列表",
    ),
    "chat_settings": (XChatAPI.get_dm_settings, {}, "私信设置"),
    "chat_bootstrap": (XChatAPI.bootstrap, {}, "私信初始化（令牌已隐藏）"),
    "chat_inbox": (XChatAPI.get_initial_chat_page, {}, "私信收件箱"),
    "chat_conversation": (
        XChatAPI.get_conversation_page,
        {"conversation_id": "会话 ID"},
        "私信会话",
    ),
    "chat_members": (
        XChatAPI.get_users_by_ids,
        {"user_ids": "用户 ID 数组"},
        "私信成员",
    ),
    "chat_public_keys": (
        XChatAPI.get_public_keys,
        {"user_ids": "用户 ID 数组"},
        "私信公钥（令牌已隐藏）",
    ),
}
ACTIONS = {
    name: getattr(XWriteAPI, method)
    for name, method in {
        "like": "favorite_tweet",
        "unlike": "unfavorite_tweet",
        "repost": "create_retweet",
        "unrepost": "delete_retweet",
        "bookmark": "create_bookmark",
        "unbookmark": "delete_bookmark",
        "delete": "delete_tweet",
        "follow": "follow_user",
        "unfollow": "unfollow_user",
    }.items()
}
