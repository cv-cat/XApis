import json
import socket
import time
import pytest
from console.content import Content
from console.network import target, RemoteError


def rss(title="One"):
    return (
        '<rss version="2.0"><channel><title>AI</title><item><title>'
        + title
        + "</title><link>https://news.example/one</link><description><![CDATA[<p>Useful <b>facts</b>.</p><script>bad</script>]]></description><pubDate>Fri, 23 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>"
    ).encode()


def setup_source(admin, monkeypatch):
    monkeypatch.setattr("console.app.target", lambda *a, **k: None)
    sid = admin.post(
        "/api/sources",
        json={"name": "AI news", "url": "https://news.example/feed", "kind": "rss"},
    ).json()["id"]
    monkeypatch.setattr(
        "console.content.network.fetch", lambda *a, **k: (rss(), "application/rss+xml")
    )
    assert admin.post("/api/sources/" + sid + "/refresh").status_code == 200
    return sid


def setup_ai(admin, monkeypatch):
    monkeypatch.setattr("console.app.target", lambda *a, **k: None)
    r = admin.put(
        "/api/ai",
        json={
            "base_url": "https://ai.example/v1",
            "model": "test-model",
            "api_key": "top-secret-key",
            "instruction": "中文",
        },
    )
    assert r.status_code == 200


def test_sources_clean_and_deduplicate(admin, app, monkeypatch):
    sid = setup_source(admin, monkeypatch)
    admin.post("/api/sources/" + sid + "/refresh")
    rows = admin.get("/api/entries").json()
    assert len(rows) == 1 and rows[0]["summary"] == "Useful facts ."
    assert rows[0]["published"] > 0


def test_web_snapshots_only_create_for_changed_content(admin, monkeypatch):
    monkeypatch.setattr("console.app.target", lambda *a, **k: None)
    sid = admin.post(
        "/api/sources",
        json={"name": "Page", "url": "https://news.example/", "kind": "web"},
    ).json()["id"]
    data = [b"<html><title>News</title><article>Story One</article></html>"]
    monkeypatch.setattr(
        "console.content.network.fetch", lambda *a, **k: (data[0], "text/html")
    )
    for _ in range(2):
        assert admin.post("/api/sources/" + sid + "/refresh").status_code == 200
    assert len(admin.get("/api/entries").json()) == 1
    data[0] = b"<html><title>News</title><article>Story Two</article></html>"
    admin.post("/api/sources/" + sid + "/refresh")
    assert len(admin.get("/api/entries").json()) == 2


def test_ai_compatible_request_and_secrets(admin, app, monkeypatch):
    setup_ai(admin, monkeypatch)
    assert "top-secret-key" not in admin.get("/api/ai").text
    assert (
        "top-secret-key"
        not in app.state.store.one("SELECT secret FROM ai_settings")["secret"]
    )
    seen = {}

    def fetch(url, **kw):
        seen.update(url=url, **kw)
        return json.dumps(
            {"choices": [{"message": {"content": "一个值得关注的 AI 新变化。"}}]}
        ).encode(), "application/json"

    monkeypatch.setattr("console.content.network.fetch", fetch)
    r = admin.post("/api/ai/generate", json={"prompt": "写关于 AI 的一条贴文"})
    assert r.status_code == 200 and r.json()["text"].startswith("一个")
    assert seen["url"] == "https://ai.example/v1/chat/completions"
    assert (
        seen["payload"]["model"] == "test-model" and seen["api_key"] == "top-secret-key"
    )
    assert seen["payload"]["messages"][0]["role"] == "system"
    assert seen["payload"]["messages"][1]["role"] == "user"
    admin.put(
        "/api/ai",
        json={"base_url": "https://ai.example/v1", "model": "new-model", "api_key": ""},
    )
    assert (
        app.state.store.decrypt(
            app.state.store.one("SELECT secret FROM ai_settings")["secret"]
        )["api_key"]
        == "top-secret-key"
    )


def test_rule_draft_then_publish_dedup_and_daily_cap(admin, account, app, monkeypatch):
    sid = setup_source(admin, monkeypatch)
    setup_ai(admin, monkeypatch)
    monkeypatch.setattr(
        Content,
        "generate",
        lambda *a, **k: {
            "text": "AI 新闻摘要 https://news.example/one",
            "weight": 50,
            "sources": [{"title": "One", "url": "https://news.example/one"}],
        },
    )
    body = {
        "name": "Daily AI",
        "account_id": account,
        "source_ids": [sid],
        "prompt": "摘要",
        "mode": "draft",
        "enabled": True,
        "interval_minutes": 15,
        "daily_limit": 1,
    }
    rid = admin.post("/api/rules", json=body).json()["id"]
    assert admin.post("/api/rules/" + rid + "/run").status_code == 200
    app.state.queue.tick()
    jobs = admin.get("/api/jobs").json()
    assert len(jobs) == 1 and jobs[0]["state"] == "draft"
    assert jobs[0]["payload"]["sources"][0]["url"] == "https://news.example/one"
    assert admin.delete("/api/sources/" + sid).status_code == 409
    admin.post("/api/rules/" + rid + "/run")
    app.state.queue.tick()
    assert len(admin.get("/api/jobs").json()) == 1
    assert "24 小时" in admin.get("/api/rules").json()[0]["last_result"]
    body["mode"] = "publish"
    body["daily_limit"] = 3
    assert admin.put("/api/rules/" + rid, json=body).status_code == 200
    admin.post("/api/rules/" + rid + "/run")
    app.state.queue.tick()
    assert len(admin.get("/api/jobs").json()) == 1  # source is already consumed
    # New item is now eligible for auto-publishing.
    monkeypatch.setattr(
        "console.content.network.fetch",
        lambda *a, **k: (rss("Two").replace(b"/one", b"/two"), "application/rss+xml"),
    )
    admin.post("/api/rules/" + rid + "/run")
    app.state.queue.tick()
    assert admin.get("/api/jobs").json()[0]["state"] == "queued"
    assert admin.post("/api/rules/" + rid + "/pause").status_code == 200
    assert admin.get("/api/jobs").json()[0]["state"] == "draft"


def test_pause_during_generation_prevents_publication(admin, account, app, monkeypatch):
    sid = setup_source(admin, monkeypatch)
    setup_ai(admin, monkeypatch)
    rid = admin.post(
        "/api/rules",
        json={
            "name": "AI",
            "account_id": account,
            "source_ids": [sid],
            "prompt": "摘要",
            "mode": "publish",
            "enabled": True,
        },
    ).json()["id"]

    def generate(*a, **kw):
        app.state.store.run("UPDATE rules SET enabled=0 WHERE id=?", (rid,))
        return {"text": "AI 新闻", "weight": 10, "sources": []}

    monkeypatch.setattr(Content, "generate", generate)
    admin.post("/api/rules/" + rid + "/run")
    app.state.queue.tick()
    assert admin.get("/api/jobs").json() == []
    assert app.state.store.all("SELECT * FROM rule_entries") == []


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "192.168.1.1"]
)
def test_ssrf_blocks_private_dns(address, monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 80))],
    )
    with pytest.raises(RemoteError):
        target("https://public-looking.example/feed")


def test_only_operator_allowlisted_ai_can_use_private_hosts(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ],
    )
    monkeypatch.setenv("CONSOLE_PRIVATE_AI_HOSTS", "ai.local")
    assert target("http://ai.local:8080/v1", True)[3] == "127.0.0.1"
    with pytest.raises(RemoteError):
        target("http://ai.local:8080/feed")
    with pytest.raises(RemoteError):
        target("http://other.local:8080/v1", True)


def test_modern_ai_budget_and_manual_compatibility(admin, app, monkeypatch):
    monkeypatch.setattr("console.app.target", lambda *a, **k: None)
    seen = []
    monkeypatch.setattr(
        "console.content.network.fetch",
        lambda *a, **k: (
            seen.append(k["payload"])
            or (
                json.dumps({"choices": [{"message": {"content": "AI 草稿"}}]}).encode(),
                "application/json",
            )
        ),
    )
    config = {
        "base_url": "https://compatible.example/v1",
        "model": "o3",
        "api_key": "test-key",
    }
    assert admin.put("/api/ai", json=config).status_code == 200
    assert admin.post("/api/ai/generate", json={"prompt": "写贴文"}).status_code == 200
    assert seen[-1]["max_completion_tokens"] == 4096 and "temperature" not in seen[-1]
    config["token_parameter"] = "max_tokens"
    assert admin.put("/api/ai", json=config).status_code == 200
    admin.post("/api/ai/generate", json={"prompt": "写贴文"})
    assert seen[-1]["max_tokens"] == 500 and "max_completion_tokens" not in seen[-1]


def test_live_http_compatible_ai_roundtrip(admin, monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    calls = []

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, self.headers.get("Authorization"), body))
            response = json.dumps(
                {
                    "choices": [
                        {"message": {"content": "真实 HTTP 测试：AI 写作接口已连接。"}}
                    ]
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setenv("CONSOLE_PRIVATE_AI_HOSTS", "127.0.0.1")
    try:
        r = admin.put(
            "/api/ai",
            json={
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                "model": "fixture-chat",
                "api_key": "private-fixture-key",
            },
        )
        assert r.status_code == 200, r.text
        r = admin.post("/api/ai/generate", json={"prompt": "写一条中文贴文"})
        assert r.status_code == 200, r.text
        assert r.json()["text"].startswith("真实 HTTP 测试")
        assert (
            calls[0][0] == "/v1/chat/completions"
            and calls[0][1] == "Bearer private-fixture-key"
        )
        assert calls[0][2]["model"] == "fixture-chat" and calls[0][2]["stream"] is False
        assert "private-fixture-key" not in admin.get("/api/ai").text
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
