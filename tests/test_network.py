import pytest
from console import network


class Response:
    status = 200
    headers = {"Content-Type": "application/json"}

    def stream(self, *a, **k):
        yield b"hello"

    def close(self):
        pass


def test_dns_pinning_redirect_and_size(monkeypatch):
    monkeypatch.setattr(
        network,
        "target",
        lambda *a, **k: (
            network.urlsplit("https://ai.example/v1"),
            "ai.example",
            443,
            "203.0.113.1",
        ),
    )
    seen = {}
    response = Response()

    class Pool:
        def __init__(self, **kw):
            seen["pool"] = kw

        def urlopen(self, *a, **kw):
            seen["request"] = kw
            return response

        def close(self):
            pass

    monkeypatch.setattr(network.urllib3, "HTTPSConnectionPool", Pool)
    assert network.fetch("https://ai.example/v1", api_key="key")[0] == b"hello"
    assert seen["pool"]["host"] == "203.0.113.1"
    assert seen["pool"]["server_hostname"] == "ai.example"
    assert seen["pool"]["assert_hostname"] == "ai.example"
    assert seen["request"]["headers"]["Host"] == "ai.example"
    assert seen["request"]["redirect"] is False
    response.status = 302
    with pytest.raises(network.RemoteError, match="重定向"):
        network.fetch("https://ai.example/v1", api_key="key")
    response.status = 200
    with pytest.raises(network.RemoteError, match="过大"):
        network.fetch("https://ai.example/v1", limit=2)
