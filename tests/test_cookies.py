from console.cookies import parse_updates, hook
from console.xbridge import auth_for


def test_cookie_refresh_merge_is_encrypted_and_updates_live_auth(admin, account, app):
    store = app.state.store
    a = store.one("SELECT * FROM accounts WHERE id=?", (account,))
    auth = auth_for(store, a)
    callback = auth.proxies["_on_cookies"]
    outcome = callback(
        "https://x.com/i/api/graphql/x",
        [
            "ct0=rotated; Domain=.x.com; Path=/; Secure; HttpOnly",
            "guest_id=new; Domain=.x.com; Path=/",
        ],
    )
    assert outcome["status"] == "applied" and outcome["changed"] == ["ct0", "guest_id"]
    row = store.one("SELECT * FROM accounts WHERE id=?", (account,))
    secret = store.decrypt(row["secret"])
    assert "rotated" not in row["secret"]
    assert (
        "ct0=rotated" in secret["cookies"]
        and "auth_token=test-auth" in secret["cookies"]
    )
    assert auth.ct0 == "rotated" and row["cookie_updated"] > 0
    assert secret["cookie_meta"]["ct0"]["secure"]
    callback("https://x.com/", ["guest_id=deleted; Max-Age=0; Domain=.x.com; Path=/"])
    assert "guest_id" not in auth.cookie
    assert (
        "guest_id="
        not in store.decrypt(
            store.one("SELECT secret FROM accounts WHERE id=?", (account,))["secret"]
        )["cookies"]
    )


def test_stale_request_cannot_overwrite_new_session(admin, account, app):
    store = app.state.store
    a = store.one("SELECT * FROM accounts WHERE id=?", (account,))
    old = auth_for(store, a)
    assert (
        admin.put(
            "/api/accounts/" + account + "/proxy", json={"proxy": "http://new:8080"}
        ).status_code
        == 200
    )
    outcome = old.proxies["_on_cookies"](
        "https://x.com/", ["auth_token=stale; Domain=.x.com; Path=/"]
    )
    assert outcome["status"] == "stale_session"
    secret = store.decrypt(
        store.one("SELECT secret FROM accounts WHERE id=?", (account,))["secret"]
    )
    assert "cookies" not in secret
    assert secret["proxy"] == "http://new:8080"


def test_cookie_domain_and_expiration():
    assert parse_updates("https://x.com/", ["a=b; Domain=evil.example"]) == []
    assert parse_updates("https://abs.twimg.com/", ["a=b; Domain=.twimg.com"]) == []
    changes = parse_updates(
        "https://x.com/", ["a=b; Expires=Thu, 01 Jan 1970 00:00:00 GMT"]
    )
    assert changes[0]["deleted"]


def test_anonymous_signing_material_cannot_clear_account_csrf(monkeypatch):
    from builder.auth import XAuth
    from builder.header import HeaderBuilder, HeaderType

    auth = XAuth(proxies={"https": "socks5://proxy:1080"}).prepare_auth(
        "auth_token=authenticated; ct0=paired-csrf"
    )

    def dangerous_callback(*a):
        auth.cookie.pop("ct0", None)

    auth.proxies["_on_cookies"] = dangerous_callback

    class Transaction:
        def generate(self, *a):
            return "transaction"

    def from_network(proxies):
        # Reproduce the anonymous /i/flow/login Set-Cookie: ct0=; Max-Age<0.
        if proxies.get("_on_cookies"):
            proxies["_on_cookies"]("https://x.com/i/flow/login", ["ct0=; Max-Age=0"])
        return Transaction()

    monkeypatch.setattr("builder.auth.ClientTransaction.from_network", from_network)
    headers = (
        HeaderBuilder.build(HeaderType.POST)
        .with_csrf(auth)
        .with_xctid(auth, "GET", "/viewer")
        .get()
    )
    assert auth.ct0 == "paired-csrf" and headers["x-csrf-token"] == auth.ct0
    assert auth.auth_token == "authenticated"


def test_csrf_header_uses_final_cookie_state_after_material_initialization():
    from builder.auth import XAuth
    from builder.header import HeaderBuilder, HeaderType

    auth = XAuth().prepare_auth("auth_token=a; ct0=old")

    def generate(*a):
        auth.update_cookies({"ct0": "fresh"})
        return "transaction"

    auth.client_transaction_id = generate
    headers = (
        HeaderBuilder.build(HeaderType.POST)
        .with_csrf(auth)
        .with_xctid(auth, "GET", "/viewer")
        .get()
    )
    assert headers["x-csrf-token"] == "fresh"
