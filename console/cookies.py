"""Merge Set-Cookie updates transactionally, without overwriting concurrent sessions."""

from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie, CookieError
import time
from urllib.parse import urlsplit
from utils.x_util import trans_cookies, cookies_to_str


def parse_updates(url, headers, now=None):
    now = time.time() if now is None else now
    host = (urlsplit(url).hostname or "").lower()
    if not (
        host == "x.com"
        or host.endswith(".x.com")
        or host == "twitter.com"
        or host.endswith(".twitter.com")
    ):
        return []
    updates = []
    for line in headers:
        parsed = SimpleCookie()
        try:
            parsed.load(line)
        except CookieError:
            continue
        for name, morsel in parsed.items():
            domain = (morsel["domain"] or host).lower().lstrip(".")
            if not (host == domain or host.endswith("." + domain)):
                continue
            if domain not in ("x.com", "twitter.com") and not domain.endswith(
                (".x.com", ".twitter.com")
            ):
                continue
            deleted = False
            expires = None
            try:
                if morsel["max-age"]:
                    age = int(morsel["max-age"])
                    deleted = age <= 0
                    expires = now + age
                elif morsel["expires"]:
                    expires = parsedate_to_datetime(morsel["expires"]).timestamp()
                    deleted = expires <= now
            except (ValueError, TypeError, OverflowError):
                pass
            updates.append(
                {
                    "name": name,
                    "value": morsel.value,
                    "deleted": deleted,
                    "domain": domain,
                    "path": morsel["path"] or "/",
                    "expires": expires,
                    "secure": bool(morsel["secure"]),
                    "http_only": bool(morsel["httponly"]),
                }
            )
    return updates


def hook(store, account_id, session_version, auth_getter=None):
    def save(url, headers):
        updates = parse_updates(url, headers)
        if not updates:
            return {"status": "ignored", "received": len(headers), "updated": [], "removed": []}
        with store.connect(immediate=True) as db:
            row = db.execute(
                "SELECT secret,session_version FROM accounts WHERE id=?", (account_id,)
            ).fetchone()
            if not row or row["session_version"] != session_version:
                return {"status": "stale_session", "received": len(headers), "updated": [], "removed": []}
            secret = store.decrypt(row["secret"])
            cookies = trans_cookies(secret.get("cookies", ""))
            meta = secret.get("cookie_meta", {})
            updated, removed, changed = [], [], []
            for change in updates:
                name = change["name"]
                if change["deleted"]:
                    removed.append(name)
                    cookies.pop(name, None)
                    meta.pop(name, None)
                else:
                    updated.append(name)
                    if cookies.get(name) != change["value"]:
                        changed.append(name)
                    cookies[name] = change["value"]
                    meta[name] = {
                        k: v
                        for k, v in change.items()
                        if k not in ("name", "value", "deleted")
                    }
            secret["cookies"] = cookies_to_str(cookies)
            secret["cookie_meta"] = meta
            saved_at = time.time()
            db.execute(
                "UPDATE accounts SET secret=?,cookie_updated=? WHERE id=?",
                (store.encrypt(secret), saved_at, account_id),
            )
        auth = auth_getter() if auth_getter else None
        if auth:
            for change in updates:
                if change["deleted"]:
                    auth.cookie.pop(change["name"], None)
                else:
                    auth.cookie[change["name"]] = change["value"]
            auth.cookie_str = cookies_to_str(auth.cookie)
        return {"status": "applied", "received": len(headers), "updated": updated,
                "changed": changed, "removed": removed, "saved_at": saved_at}

    return save
