import base64
import json
from types import SimpleNamespace

import pytest
from console import chat
from console.xbridge import auth_for
from x_apis.x_dm_api import XChatAPI
from x_apis.errors import GraphQLError


def keys_payload(uid="123"):
    realms = [
        {"id": "a" * 32, "address": "https://realm-b.x.com"},
        {
            "id": "b" * 32,
            "address": "https://realm-east1.x.com",
            "public_key": "00" * 32,
        },
    ]
    config = {
        "realms": realms,
        "register_threshold": 2,
        "recover_threshold": 2,
        "pin_hashing_mode": "Standard2019",
    }
    return {
        "data": {
            "user_results_by_rest_ids": [
                {
                    "rest_id": uid,
                    "result": {
                        "get_public_keys": {
                            "public_keys_with_token_map": [
                                {
                                    "public_key_with_metadata": {
                                        "version": "1",
                                        "public_key": {
                                            "public_key": "identity-fixture",
                                            "signing_public_key": "signing-fixture",
                                            "identity_public_key_signature": "signature-fixture",
                                        },
                                    },
                                    "token_map": {
                                        "max_guess_count": 20,
                                        "key_store_token_map_json": json.dumps(config),
                                        "token_map": [
                                            {
                                                "key": r["id"],
                                                "value": {
                                                    "address": r["address"],
                                                    "token": "fixture-token-" + r["id"],
                                                },
                                            }
                                            for r in realms
                                        ],
                                    },
                                }
                            ]
                        }
                    },
                }
            ]
        }
    }


def test_empty_inbox_is_not_raw_json_and_unknown_shape_is_not_empty(
    admin, account, monkeypatch
):
    monkeypatch.setattr(
        "console.app.XChatAPI.get_initial_chat_page",
        lambda auth: {
            "data": {
                "get_initial_chat_page": {
                    "__typename": "XChatGetInboxPageResponse",
                    "items": [],
                    "inboxCursor": {
                        "__typename": "XChatGetInboxPageEndCursor",
                        "graph_snapshot_id": "private-correlation",
                    },
                    "message_requests_count": 0,
                    "max_user_sequence_id": "private-sequence",
                }
            }
        },
    )
    response = admin.get(f"/api/accounts/{account}/chat/inbox")
    assert response.status_code == 200
    assert (
        response.json()["conversations"] == [] and response.json()["complete"] is True
    )
    assert response.json()["send_supported"] is True
    assert (
        "private-correlation" not in response.text
        and "private-sequence" not in response.text
    )
    monkeypatch.setattr(
        "console.app.XChatAPI.get_initial_chat_page", lambda auth: {"data": {}}
    )
    assert admin.get(f"/api/accounts/{account}/chat/inbox").status_code == 502


def test_chat_pin_encrypted_and_owner_scoped(admin, account, app, monkeypatch):
    monkeypatch.setattr(
        "console.app.XChatAPI.get_public_keys",
        lambda *a, **k: pytest.fail("saving must not call X"),
    )
    pin = "fixture-chat-pin"
    assert (
        admin.put(
            f"/api/accounts/{account}/chat/password", json={"pin": pin}
        ).status_code
        == 200
    )
    store = app.state.store
    row = store.one("SELECT * FROM accounts WHERE id=?", (account,))
    assert pin not in row["secret"] and store.decrypt(row["secret"])["chat_pin"] == pin
    for path in [f"/api/accounts/{account}/chat/status", "/api/accounts", "/api/audit"]:
        assert pin not in admin.get(path).text
    assert admin.get(f"/api/accounts/{account}/chat/status").json()["has_saved_pin"]
    assert (
        admin.put(
            "/api/accounts/not-owned/chat/password", json={"pin": pin}
        ).status_code
        == 404
    )
    auth = auth_for(store, row)
    auth.proxies["_on_cookies"](
        "https://x.com/", ["ct0=renewed; Domain=.x.com; Path=/"]
    )
    assert (
        store.decrypt(
            store.one("SELECT secret FROM accounts WHERE id=?", (account,))["secret"]
        )["chat_pin"]
        == pin
    )
    assert (
        admin.put(
            f"/api/accounts/{account}/proxy", json={"proxy": "http://new-proxy:8080"}
        ).status_code
        == 200
    )
    assert (
        store.decrypt(
            store.one("SELECT secret FROM accounts WHERE id=?", (account,))["secret"]
        )["chat_pin"]
        == pin
    )
    assert admin.delete(f"/api/accounts/{account}/chat/password").status_code == 200
    assert "chat_pin" not in store.decrypt(
        store.one("SELECT secret FROM accounts WHERE id=?", (account,))["secret"]
    )


def test_recovery_relay_is_bounded_to_account_realms_and_session(
    admin, account, app, monkeypatch
):
    monkeypatch.setattr(
        "console.chat.XChatAPI.get_public_keys", lambda *a, **kw: keys_payload()
    )
    assert admin.post(f"/api/accounts/{account}/chat/unlock-context").status_code == 409
    admin.put(
        f"/api/accounts/{account}/chat/password", json={"pin": "fixture-chat-pin"}
    )
    context = admin.post(f"/api/accounts/{account}/chat/unlock-context").json()
    assert context["user_id"] == "123" and context["pin"] == "fixture-chat-pin"
    calls = []
    monkeypatch.setattr(
        "console.chat.gateway.request",
        lambda method, url, **kw: (
            calls.append((method, url, kw))
            or SimpleNamespace(
                status_code=200,
                content=b"recovery-response",
                headers={"content-type": "application/octet-stream"},
            )
        ),
    )
    body = {
        "context_id": context["context_id"],
        "method": "POST",
        "url": "https://realm-b.x.com/req",
        "headers": {
            "content-type": "application/octet-stream",
            "authorization": "must-not-forward",
            "x-juicebox-version": "1",
        },
        "body": base64.b64encode(b"opaque-recovery-request").decode(),
    }
    response = admin.post(f"/api/accounts/{account}/chat/relay", json=body)
    assert (
        response.status_code == 200
        and base64.b64decode(response.json()["body"]) == b"recovery-response"
    )
    assert (
        calls[0][2]["proxies"]["_account"] == account and "cookies" not in calls[0][2]
    )
    assert calls[0][2]["headers"]["authorization"] == "Bearer fixture-token-" + "a" * 32
    assert calls[0][2]["headers"]["x-juicebox-version"] == "1"
    for url in [
        "http://127.0.0.1/",
        "https://api.x.com/2/tweets",
        "https://realm-b.x.com/req?target=other",
    ]:
        assert (
            admin.post(
                f"/api/accounts/{account}/chat/relay", json={**body, "url": url}
            ).status_code
            == 400
        )
    assert len(calls) == 1
    assert (
        admin.post(
            f"/api/accounts/{account}/chat/relay", json={**body, "pin": "must-not-echo"}
        ).status_code
        == 422
    )
    app.state.store.run(
        "UPDATE accounts SET session_version=session_version+1 WHERE id=?", (account,)
    )
    assert (
        admin.post(f"/api/accounts/{account}/chat/relay", json=body).status_code == 409
    )
    assert admin.post("/api/accounts/not-owned/chat/unlock-context").status_code == 404


def test_public_keys_never_return_recovery_tokens():
    parsed = chat.public_keys(keys_payload())
    assert len(parsed) == 1 and parsed[0]["userId"] == "123"
    assert "fixture-token" not in json.dumps(parsed)
    assert "key_store_token_map_json" not in json.dumps(parsed)


def test_chat_graphql_error_is_not_a_successful_empty_inbox(monkeypatch):
    from builder.auth import XAuth

    auth = XAuth().prepare_auth("auth_token=fixture; ct0=fixture")
    auth.client_transaction_id = lambda *a: "fixture-transaction"
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"errors": [{"code": 32, "message": "expired"}]},
    )
    monkeypatch.setattr("x_apis.x_dm_api.client.get", lambda *a, **k: response)
    with pytest.raises(GraphQLError) as raised:
        XChatAPI.get_initial_chat_page(auth)
    assert raised.value.code == 32


def test_inbox_does_not_show_unsupported_items_as_no_conversations():
    result = chat.inbox(
        {
            "data": {
                "get_initial_chat_page": {
                    "items": [{"unexpected": "opaque"}],
                    "inboxCursor": {},
                }
            }
        }
    )
    assert result["unrecognized_items"] == 1 and result["item_count"] == 1


def test_native_conversation_shape_and_pagination():
    raw = {
        "data": {
            "get_initial_chat_page": {
                "items": [
                    {
                        "conversation_detail": {
                            "conversation_id": "123:456",
                            "participants_results": [
                                {
                                    "rest_id": "123",
                                    "result": {
                                        "__typename": "User",
                                        "rest_id": "123",
                                        "core": {
                                            "name": "Self",
                                            "screen_name": "self_fixture",
                                        },
                                    },
                                },
                                {
                                    "rest_id": "456",
                                    "result": {
                                        "__typename": "User",
                                        "rest_id": "456",
                                        "core": {
                                            "name": "Recipient",
                                            "screen_name": "recipient_fixture",
                                        },
                                    },
                                },
                            ],
                        },
                        "latest_conversation_key_change_events": ["a2V5"],
                        "latest_message_events": ["bWVzc2FnZQ=="],
                        "has_more": True,
                    }
                ],
                "inboxCursor": {
                    "__typename": "XChatGetInboxPageContinueCursor",
                    "cursor_id": "fixture-page",
                    "graph_snapshot_id": "fixture-snapshot",
                    "graph_snapshot_restarted": False,
                },
            }
        }
    }
    result = chat.inbox(raw, "123")
    assert result["conversations"][0]["title"] == "Recipient"
    assert result["conversations"][0]["participant_ids"] == ["123", "456"]
    assert result["conversations"][0]["events"] == ["a2V5", "bWVzc2FnZQ=="]
    assert chat.parse_cursor(result["cursor"])["cursor_id"] == "fixture-page"
    assert chat.conversation_page(
        {
            "data": {
                "get_conversation_page": {
                    "encoded_message_events": ["bWVzc2FnZQ=="],
                    "missing_conversation_key_change_events": ["a2V5"],
                    "has_more": True,
                }
            }
        }
    )["events"] == ["a2V5", "bWVzc2FnZQ=="]
    with pytest.raises(Exception):
        chat.parse_cursor(base64.urlsafe_b64encode(b'{"url":"http://other"}'))


def send_payload():
    return {
        "conversation_id": "123:456",
        "message_id": "12345678-abcd-4321-abcd-123456789abc",
        "encoded_message_create_event": "ZW5jcnlwdGVk",
        "encoded_message_event_signature": "c2lnbmF0dXJl",
    }


def test_send_policy_dedup_and_no_plaintext_storage(admin, account, app, monkeypatch):
    import time

    store = app.state.store
    calls = []
    monkeypatch.setattr(
        "console.app.XChatAPI.send_message",
        lambda auth, **body: calls.append(body) or "ZW5jcnlwdGVkLXJlc3VsdA==",
    )
    row = store.one("SELECT * FROM accounts WHERE id=?", (account,))
    store.run(
        "UPDATE account_policies SET warmup_until=? WHERE id=?",
        (time.time() + 86400, row["policy_id"]),
    )
    assert (
        admin.post(
            f"/api/accounts/{account}/chat/send", json=send_payload()
        ).status_code
        == 423
    )
    assert calls == [] and not store.all("SELECT * FROM chat_dispatches")
    store.run(
        "UPDATE account_policies SET warmup_until=0 WHERE id=?", (row["policy_id"],)
    )
    assert (
        admin.post(
            f"/api/accounts/{account}/chat/send",
            json={**send_payload(), "text": "plaintext-not-allowed"},
        ).status_code
        == 422
    )
    assert (
        admin.post(
            f"/api/accounts/{account}/chat/send", json=send_payload()
        ).status_code
        == 200
    )
    assert (
        admin.post(
            f"/api/accounts/{account}/chat/send", json=send_payload()
        ).status_code
        == 409
    )
    assert len(calls) == 1
    persisted = store.one("SELECT * FROM chat_dispatches")
    assert persisted["state"] == "responded" and "ZW5jcnlwdGVk" not in json.dumps(
        persisted
    )
    assert (
        admin.post("/api/accounts/not-owned/chat/send", json=send_payload()).status_code
        == 404
    )


def test_unknown_send_outcome_is_never_retried(admin, account, app, monkeypatch):
    calls = []

    def fail(*a, **k):
        calls.append(1)
        raise TimeoutError("private-payload-must-not-leak")

    monkeypatch.setattr("console.app.XChatAPI.send_message", fail)
    result = admin.post(f"/api/accounts/{account}/chat/send", json=send_payload())
    assert result.status_code == 502 and "private-payload" not in result.text
    assert (
        app.state.store.one("SELECT state FROM chat_dispatches")["state"] == "uncertain"
    )
    assert (
        admin.post(
            f"/api/accounts/{account}/chat/send", json=send_payload()
        ).status_code
        == 409
    )
    assert calls == [1]


def test_web_send_uses_signed_ciphertext_and_checks_confirmation(monkeypatch):
    from builder.auth import XAuth

    auth = XAuth().prepare_auth("auth_token=fixture; ct0=fixture")
    auth.client_transaction_id = lambda *a: "fixture-transaction"
    calls = []
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "data": {
                "xchat_send_create_message_event": {"encoded_message_event": "ZXZlbnQ="}
            }
        },
    )
    monkeypatch.setattr(
        "x_apis.x_dm_api.client.post",
        lambda *a, **kw: calls.append((a, kw)) or response,
    )
    assert XChatAPI.send_message(auth, **send_payload()) == "ZXZlbnQ="
    assert "/SendMessageCreateMutation" in calls[0][0][0]
    assert (
        calls[0][1]["json"]["variables"]["message_id"] == send_payload()["message_id"]
    )
    response.json = lambda: {"data": {"xchat_send_create_message_event": {}}}
    with pytest.raises(RuntimeError):
        XChatAPI.send_message(auth, **send_payload())


def test_settings_sync_is_not_a_broken_message_and_cursor_keeps_page_boundary(
    admin, account, app, monkeypatch
):
    import struct

    def event(seq, mid, suffix=b"\0"):
        parts = []
        for field, value in [(1, seq), (2, mid)]:
            raw = value.encode()
            parts.append(struct.pack(">bhi", 11, field, len(raw)) + raw)
        return base64.b64encode(b"".join(parts) + suffix).decode()

    settings = event("900", "settings-fixture")
    delivered = event("900", "settings-fixture", b"\x02\x00\x0b\x01\x00")
    normal = event("899", "message-fixture")
    assert settings != delivered
    monkeypatch.setattr(
        "console.app.XChatAPI.get_initial_chat_page",
        lambda *a, **kw: {
            "data": {
                "get_initial_chat_page": {
                    "items": [],
                    "latest_user_metadata_message_event": settings,
                    "inboxCursor": {"__typename": "XChatGetInboxPageEndCursor"},
                }
            }
        },
    )
    assert admin.get(f"/api/accounts/{account}/chat/inbox").status_code == 200
    monkeypatch.setattr(
        "console.app.XChatAPI.get_conversation_page",
        lambda *a, **kw: {
            "data": {
                "get_conversation_page": {
                    "encoded_message_events": [delivered, normal],
                    "missing_conversation_key_change_events": [
                        event("100", "older-key-fixture")
                    ],
                    "has_more": True,
                }
            }
        },
    )
    result = admin.get(f"/api/accounts/{account}/chat/conversations/123:123").json()
    assert result["system_event_count"] == 1 and delivered not in result["events"]
    assert normal in result["events"] and result["before"] == "899"
    assert result["page_events"] == [normal]
    other = admin.get(f"/api/accounts/{account}/chat/conversations/123:456").json()
    assert other["system_event_count"] == 0 and delivered in other["events"]
    for invalid in [
        "not base64",
        "AA==",
        base64.b64encode(b"\x0b\x00\x02\xff\xff\xff\xff").decode(),
    ]:
        assert chat.event_header(invalid) == {}


def test_key_setup_cannot_rotate_existing_conversation_or_bypass_warmup(
    admin, account, app, monkeypatch
):
    import time

    body = {
        "conversation_id": "123:456",
        "conversation_key_version": "1",
        "conversation_participant_keys": [
            {
                "user_id": uid,
                "public_key_version": "1",
                "encrypted_conversation_key": "a2V5",
            }
            for uid in ["123", "456"]
        ],
        "action_signatures": [
            {
                "message_id": "12345678-abcd-4321-abcd-123456789abc",
                "encoded_message_event_detail": "ZXZlbnQ=",
                "message_event_signature": {
                    "public_key_version": "1",
                    "signature_version": "7",
                    "signature": "c2ln",
                    "signing_public_key": "cHVi",
                },
            }
        ],
    }
    calls = []
    monkeypatch.setattr(
        "console.app.XChatAPI.add_conversation_keys",
        lambda *a, **k: (
            calls.append(k) or {"conversation_key_change_sequence_id": "1000"}
        ),
    )
    monkeypatch.setattr(
        "console.app.XChatAPI.get_conversation_page",
        lambda *a, **k: {
            "data": {
                "get_conversation_page": {
                    "encoded_message_events": ["ZXZlbnQ="],
                    "has_more": False,
                }
            }
        },
    )
    assert (
        admin.post(
            f"/api/accounts/{account}/chat/conversation-keys", json=body
        ).status_code
        == 409
    )
    assert not calls
    store = app.state.store
    row = store.one("SELECT * FROM accounts WHERE id=?", (account,))
    store.run(
        "UPDATE account_policies SET warmup_until=? WHERE id=?",
        (time.time() + 86400, row["policy_id"]),
    )
    monkeypatch.setattr(
        "console.app.XChatAPI.get_conversation_page",
        lambda *a, **k: pytest.fail("warmup must block before X requests"),
    )
    assert (
        admin.post(
            f"/api/accounts/{account}/chat/conversation-keys", json=body
        ).status_code
        == 423
    )
    store.run(
        "UPDATE account_policies SET warmup_until=0 WHERE id=?", (row["policy_id"],)
    )
    monkeypatch.setattr(
        "console.app.XChatAPI.get_conversation_page",
        lambda *a, **k: {
            "data": {
                "get_conversation_page": {
                    "encoded_message_events": [],
                    "has_more": False,
                }
            }
        },
    )
    assert (
        admin.post(
            f"/api/accounts/{account}/chat/conversation-keys",
            json={**body, "conversation_id": "456:789"},
        ).status_code
        == 400
    )
    assert (
        admin.post(
            f"/api/accounts/{account}/chat/conversation-keys", json=body
        ).status_code
        == 200
    )
    assert len(calls) == 1
