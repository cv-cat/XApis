"""X Chat read adapters and an account-bound relay for browser key recovery.

PINs use the store's encrypted secret field; recovered private keys stay in the
browser worker. Recovery credentials are short lived and account/session bound.
"""

import base64
import hashlib
import json
import secrets
import struct
import threading
import time
from urllib.parse import urlsplit

from builder import gateway
from console.security import require
from console.xbridge import auth_for, profile
from console import policy
from x_apis.errors import GraphQLError
from x_apis.x_dm_api import XChatAPI

REALM_HOSTS = frozenset(("realm-b.x.com", "realm-east1.x.com", "realm-west1.x.com"))
FEATURES_URL = "https://api.x.com/2/chat/features"


def walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def public_keys(payload):
    result = []
    for user in (payload.get("data") or {}).get("user_results_by_rest_ids", []):
        uid = str(user.get("rest_id") or "")
        keys = (user.get("result") or {}).get("get_public_keys") or {}
        for record in keys.get("public_keys_with_token_map") or []:
            metadata = record.get("public_key_with_metadata") or {}
            key = metadata.get("public_key") or {}
            if uid and key.get("public_key") and key.get("signing_public_key"):
                result.append(
                    {
                        "userId": uid,
                        "publicKeyVersion": str(metadata.get("version") or ""),
                        "publicKey": key["signing_public_key"],
                        "identityPublicKey": key["public_key"],
                        "identityPublicKeySignature": key.get(
                            "identity_public_key_signature", ""
                        ),
                    }
                )
    return result


def encoded_events(value):
    # Only event envelopes, never a ciphertext field or a signature by itself.
    events = []
    for node in walk(value):
        for key in (
            "missing_conversation_key_change_events",
            "latest_conversation_key_change_events",
            "encoded_message_events",
            "latest_message_events",
            "encoded_event",
            "encoded_message_event",
        ):
            values = node.get(key, [])
            if isinstance(values, str):
                values = [values]
            if isinstance(values, list):
                events.extend(
                    v for v in values if isinstance(v, str) and len(v) <= 2_000_000
                )
    return list(dict.fromkeys(events))[:500]


def event_header(encoded):
    """Read only leading string metadata from a Thrift binary MessageEvent.

    These IDs identify X's own settings-sync events. This does not decrypt or
    trust message content; signature verification remains in the browser SDK.
    """
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 2_000_000:
            return {}
        offset, result = 0, {}
        for _ in range(16):
            kind, field, size = struct.unpack_from(">bhi", raw, offset)
            if kind != 11 or size < 0 or size > 500 or offset + 7 + size > len(raw):
                break
            value = raw[offset + 7 : offset + 7 + size].decode("ascii")
            if field in (1, 2):
                result[field] = value
            offset += 7 + size
            if 1 in result and 2 in result:
                break
        return result
    except (ValueError, TypeError, struct.error, UnicodeError):
        return {}


def inbox(payload, viewer_id=None):
    data = payload.get("data") or {}
    page = data.get("get_initial_chat_page") or data.get("get_inbox_page")
    require(
        isinstance(page, dict) and isinstance(page.get("items"), list),
        "X Chat 返回了未识别的收件箱结构，不能当作空收件箱",
        502,
    )
    conversations, seen, hidden = [], set(), 0
    for item in page["items"]:
        if isinstance(item, dict) and item.get("is_deleted_by_viewer"):
            hidden += 1
            continue
        for node in walk(item):
            cid = node.get("conversation_id") or node.get("conversationId")
            if not isinstance(cid, str) or not cid or cid in seen or len(cid) > 200:
                continue
            seen.add(cid)
            people = [profile(r) for r in node.get("participants_results", [])]
            people = [p for p in people if p]
            members = list(dict.fromkeys(p["x_id"] for p in people))[:100]
            others = [p for p in people if p["x_id"] != viewer_id]
            title = (
                "群聊"
                if len(members) > 2
                else (others[0]["name"] or others[0]["handle"])
                if others
                else "给自己留言"
                if members == [viewer_id]
                else "私信会话"
            )
            title = (node.get("group_metadata") or {}).get("group_name") or title
            conversations.append(
                {
                    "id": cid,
                    "title": title,
                    "participant_ids": members,
                    "participants": people,
                    "events": encoded_events(item),
                    "has_more": bool(item.get("has_more")),
                }
            )
            break
    cursor = page.get("inboxCursor") or {}
    next_cursor = None
    if cursor.get("__typename") == "XChatGetInboxPageContinueCursor" and cursor.get(
        "cursor_id"
    ):
        next_cursor = base64.urlsafe_b64encode(
            json.dumps(
                {
                    k: v
                    for k, v in cursor.items()
                    if k
                    in ("cursor_id", "graph_snapshot_id", "graph_snapshot_restarted")
                }
            ).encode()
        ).decode()
    return {
        "conversations": conversations,
        "item_count": len(page["items"]),
        "message_requests": page.get("message_requests_count", 0),
        "complete": cursor.get("__typename") == "XChatGetInboxPageEndCursor",
        "unrecognized_items": max(0, len(page["items"]) - hidden - len(conversations)),
        "cursor": next_cursor,
        "synced_at": time.time(),
        "send_supported": True,
    }


def parse_cursor(value):
    try:
        cursor = json.loads(base64.urlsafe_b64decode(value))
        valid = (
            isinstance(cursor, dict)
            and set(cursor)
            <= {"cursor_id", "graph_snapshot_id", "graph_snapshot_restarted"}
            and all(
                isinstance(cursor.get(k), str) and 0 < len(cursor[k]) <= 1000
                for k in ("cursor_id", "graph_snapshot_id")
            )
            and isinstance(cursor.get("graph_snapshot_restarted", False), bool)
        )
    except (ValueError, TypeError):
        valid = False
    require(valid, "收件箱翻页游标无效", 400)
    return cursor


def conversation_page(payload):
    page = (payload.get("data") or {}).get("get_conversation_page")
    require(
        isinstance(page, dict) and isinstance(page.get("encoded_message_events"), list),
        "X Chat 返回了未识别的会话结构",
        502,
    )
    sequences = [event_header(e).get(1, "") for e in page["encoded_message_events"]]
    sequences = [v for v in sequences if v.isascii() and v.isdigit() and len(v) <= 20]
    return {
        "events": encoded_events(page),
        "page_events": list(dict.fromkeys(page["encoded_message_events"]))[:500],
        "before": min(sequences, key=int) if sequences else None,
        "has_more": bool(page.get("has_more")),
        "send_supported": True,
        "message_request_state": page.get("message_request_state"),
    }


class ChatService:
    def __init__(self, store):
        self.store = store
        self.contexts = {}
        self.metadata = {}
        self.lock = threading.Lock()

    def remember_metadata(self, account, payload):
        page = (payload.get("data") or {}).get("get_initial_chat_page") or {}
        events = [page.get("latest_user_metadata_message_event")]
        events += list((page.get("user_metadata_snapshot") or {}).values())
        ids = {event_header(e).get(2) for e in events if isinstance(e, str)} - {None}
        now = time.time()
        with self.lock:
            self.metadata = {
                k: v for k, v in self.metadata.items() if v["expires"] > now
            }
            old = self.metadata.get(account["id"], {})
            if old.get("version") == account["session_version"]:
                ids |= old.get("ids", set())
            self.metadata[account["id"]] = {
                "ids": set(list(ids)[-1000:]),
                "expires": now + 900,
                "version": account["session_version"],
            }

    def display_page(self, account, conversation_id, payload):
        result = conversation_page(payload)
        result["system_event_count"] = 0
        if conversation_id != account["x_id"] + ":" + account["x_id"]:
            return result
        with self.lock:
            cached = self.metadata.get(account["id"])
        if (
            not cached
            or cached["expires"] <= time.time()
            or cached["version"] != account["session_version"]
        ):
            self.remember_metadata(
                account, XChatAPI.get_initial_chat_page(auth_for(self.store, account))
            )
            with self.lock:
                cached = self.metadata.get(account["id"])
        ids = cached["ids"]
        filtered = [e for e in result["events"] if event_header(e).get(2) not in ids]
        result["system_event_count"] = len(result["events"]) - len(filtered)
        result["events"] = filtered
        result["page_events"] = [
            e for e in result["page_events"] if event_header(e).get(2) not in ids
        ]
        return result

    def dispatch(self, account, message_id, operation, payload, send):
        """Persist only a digest and outcome; an uncertain write is never retried."""
        policy.ensure_write(self.store, account)
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        now = time.time()
        with self.store.connect(immediate=True) as db:
            prior = db.execute(
                "SELECT * FROM chat_dispatches WHERE account_id=? AND message_id=?",
                (account["id"], message_id),
            ).fetchone()
            require(
                not prior, "这条聊天请求已提交，请先刷新会话核对结果，不能重复发送", 409
            )
            db.execute(
                "INSERT INTO chat_dispatches VALUES(?,?,?,?,?,?,?)",
                (account["id"], message_id, digest, operation, "sending", now, now),
            )
        try:
            result = send()
        except Exception as exc:
            state = "rejected" if isinstance(exc, GraphQLError) else "uncertain"
            self.store.run(
                "UPDATE chat_dispatches SET state=?,updated=? WHERE account_id=? AND message_id=?",
                (state, time.time(), account["id"], message_id),
            )
            self.store.audit(
                account["owner"], "chat." + operation + "." + state, account["id"]
            )
            raise
        self.store.run(
            "UPDATE chat_dispatches SET state='responded',updated=? WHERE account_id=? AND message_id=?",
            (time.time(), account["id"], message_id),
        )
        self.store.audit(
            account["owner"], "chat." + operation + ".responded", account["id"]
        )
        return result

    def save_pin(self, account, pin):
        with self.store.connect(immediate=True) as db:
            row = db.execute(
                "SELECT secret FROM accounts WHERE id=? FOR UPDATE", (account["id"],)
            ).fetchone()
            secret = self.store.decrypt(row["secret"])
            if pin is None:
                secret.pop("chat_pin", None)
            else:
                secret["chat_pin"] = pin
            db.execute(
                "UPDATE accounts SET secret=? WHERE id=?",
                (self.store.encrypt(secret), account["id"]),
            )
        with self.lock:
            self.contexts = {
                k: v
                for k, v in self.contexts.items()
                if v["account_id"] != account["id"]
            }

    def context(self, account):
        pin = self.store.decrypt(account["secret"]).get("chat_pin")
        require(pin, "请先保存已在 X Chat 设置的聊天密码", 409)
        auth = auth_for(self.store, account)
        auth.proxies["_deadline"] = time.monotonic() + 90
        payload = XChatAPI.get_public_keys(auth, [account["x_id"]])
        users = (payload.get("data") or {}).get("user_results_by_rest_ids", [])
        own = next((r for r in users if str(r.get("rest_id")) == account["x_id"]), {})
        records = ((own.get("result") or {}).get("get_public_keys") or {}).get(
            "public_keys_with_token_map"
        ) or []
        require(records, "X 未返回聊天密钥备份，请先在 X Chat 完成初始化", 409)
        # The server returns versions newest first. Never generate or replace keys.
        record = records[0]
        token_map = record.get("token_map") or {}
        try:
            config = json.loads(token_map.get("key_store_token_map_json", "{}"))
        except (ValueError, TypeError):
            require(False, "X 返回的密钥备份配置无法解析", 502)
        realms = config.get("realms") or []
        require(realms and len(realms) <= 5, "X 未返回可恢复的聊天密钥备份", 409)
        allowed_urls = set()
        for realm in realms:
            parsed = urlsplit(realm.get("address", ""))
            require(
                parsed.scheme == "https"
                and parsed.hostname in REALM_HOSTS
                and parsed.port in (None, 443)
                and not parsed.username
                and not parsed.password
                and not parsed.query
                and not parsed.fragment,
                "X 返回了暂不支持的密钥服务地址",
                502,
            )
            base = realm["address"].rstrip("/")
            allowed_urls.update((base, base + "/req"))
        tokens = {}
        for entry in token_map.get("token_map") or []:
            value = entry.get("value") or {}
            token = value.get("token") or value.get("auth_token")
            if isinstance(token, str) and token:
                tokens[str(entry["key"]).lower().replace("-", "")] = token
        require(
            len(tokens) >= config.get("recover_threshold", 2),
            "X 未返回完整的聊天密钥恢复授权",
            502,
        )
        realm_auth = {}
        for realm in realms:
            token = tokens.get(str(realm["id"]).lower().replace("-", ""))
            if token:
                base = realm["address"].rstrip("/")
                realm_auth.update({base: token, base + "/req": token})
        keys = public_keys(payload)
        version = str(
            (record.get("public_key_with_metadata") or {}).get("version") or ""
        )
        require(
            any(k["publicKeyVersion"] == version for k in keys),
            "X 未返回有效的聊天公钥版本",
            502,
        )
        now = time.time()
        context_id = secrets.token_urlsafe(24)
        with self.lock:
            self.contexts = {
                k: v for k, v in self.contexts.items() if v["expires"] > now
            }
            require(len(self.contexts) < 128, "聊天解锁会话过多，请稍后再试", 429)
            self.contexts[context_id] = {
                "account_id": account["id"],
                "version": account["session_version"],
                "urls": allowed_urls,
                "realm_auth": realm_auth,
                "expires": now + 300,
            }
        return {
            "context_id": context_id,
            "user_id": account["x_id"],
            "version": version,
            "pin": pin,
            "config": {
                "key_store_token_map_json": json.dumps(config),
                "max_guess_count": token_map.get("max_guess_count", 20),
            },
            "realm_tokens": tokens,
            "public_keys": keys,
        }

    def discard(self, account, context_id):
        with self.lock:
            ctx = self.contexts.get(context_id)
            if ctx and ctx["account_id"] == account["id"]:
                self.contexts.pop(context_id, None)

    def relay(self, account, request):
        with self.lock:
            ctx = self.contexts.get(request.context_id)
        require(
            ctx
            and ctx["account_id"] == account["id"]
            and ctx["expires"] > time.time()
            and ctx["version"] == account["session_version"]
            and account["status"] == "connected",
            "聊天解锁会话已失效，请重新解锁",
            409,
        )
        require(
            (request.url in ctx["urls"] and request.method == "POST")
            or (request.url == FEATURES_URL and request.method == "GET"),
            "不允许访问此聊天服务地址",
            400,
        )
        try:
            body = base64.b64decode(request.body, validate=True)
        except (ValueError, TypeError):
            require(False, "聊天请求编码无效", 400)
        require(len(body) <= 1_000_000, "聊天请求过大", 413)
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() in ("content-type", "accept", "x-juicebox-version")
        }
        require(
            all(
                len(v) <= 200 and "\r" not in v and "\n" not in v
                for v in headers.values()
            ),
            "聊天请求头无效",
            400,
        )
        # Juicebox authenticates requests with the realm token issued by X.
        # Select it server-side; never forward arbitrary browser Authorization.
        if request.url in ctx["realm_auth"]:
            headers["authorization"] = "Bearer " + ctx["realm_auth"][request.url]
        proxy = self.store.decrypt(account["secret"])["proxy"]
        response = gateway.request(
            request.method,
            request.url,
            headers=headers,
            data=body,
            proxies={"https": proxy, "_account": account["id"]},
            timeout=30,
            allow_redirects=False,
        )
        require(len(response.content) <= 2_000_000, "聊天服务响应过大", 502)
        return {
            "status": response.status_code,
            "body": base64.b64encode(response.content).decode(),
            "content_type": response.headers.get(
                "content-type", "application/octet-stream"
            ),
        }
