"""End-to-end auth behaviour for REST routes and the /ws endpoint."""

import logging
import time
import uuid

import pytest
from auth import (
    API_KEY_ENV,
    API_KEYS_ENV,
    WS_CLOSE_UNAUTHORIZED,
    encode_ws_auth_protocol,
)
from fastapi.testclient import TestClient
from main import app
from starlette.websockets import WebSocketDisconnect

KEY = "test-key-Abc123"


@pytest.fixture
def no_auth(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.delenv(API_KEYS_ENV, raising=False)


@pytest.fixture
def with_auth(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, KEY)
    monkeypatch.delenv(API_KEYS_ENV, raising=False)


def bearer(key: str = KEY) -> dict:
    return {"Authorization": f"Bearer {key}"}


def sdk_event(session_id: str, event_id: str) -> dict:
    return {
        "type": "event",
        "session_id": session_id,
        "event": {
            "event_id": event_id,
            "event_type": "tool_end",
            "agent_name": "auth-tool",
            "agent_type": "tool",
            "status": "completed",
            "timestamp": "2026-11-15T12:00:00.000Z",
            "latency_ms": 5,
            "payload": {"tool_name": "auth-tool", "input": "x", "output": "y"},
        },
    }


def wait_for_events(client: TestClient, session_id: str, expected: int, **kwargs):
    for _ in range(50):
        res = client.get(f"/api/sessions/{session_id}/events", **kwargs)
        if res.status_code == 200 and len(res.json()["events"]) >= expected:
            return res.json()["events"]
        time.sleep(0.05)
    raise AssertionError(f"expected {expected} events for {session_id}")


# --- Auth disabled (default) -------------------------------------------------


def test_rest_and_ws_open_when_no_key_configured(no_auth):
    with TestClient(app) as client:
        assert client.get("/api/sessions").status_code == 200
        with client.websocket_connect("/ws?client_type=ui") as ws:
            assert ws.accepted_subprotocol is None


# --- REST --------------------------------------------------------------------


def test_health_and_docs_stay_public(with_auth):
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/openapi.json").status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-key"},
        {"Authorization": f"Basic {KEY}"},
        {"Authorization": KEY},
        {"X-API-Key": KEY},
    ],
)
def test_rest_rejects_missing_or_invalid_credentials(with_auth, headers):
    with TestClient(app) as client:
        res = client.get("/api/sessions", headers=headers)
    assert res.status_code == 401
    assert res.headers["www-authenticate"] == "Bearer"
    assert res.json() == {"detail": "Missing or invalid API key"}


def test_every_router_is_protected(with_auth):
    with TestClient(app) as client:
        for path in (
            "/api/sessions",
            "/api/sessions/some-id",
            "/api/sessions/some-id/export",
            "/api/sessions/some-id/events",
            "/api/sessions/some-id/memories",
        ):
            # 401 comes before routing errors such as 404, so an attacker
            # cannot probe which sessions exist.
            assert client.get(path).status_code == 401, path
        assert (
            client.post("/api/sessions", json={"name": "x"}).status_code == 401
        ), "writes must be protected too"


def test_rest_accepts_valid_key(with_auth):
    with TestClient(app) as client:
        res = client.get("/api/sessions", headers=bearer())
    assert res.status_code == 200


def test_rotated_keys_are_all_accepted(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.setenv(API_KEYS_ENV, "old-key,new-key")
    with TestClient(app) as client:
        assert client.get("/api/sessions", headers=bearer("old-key")).status_code == 200
        assert client.get("/api/sessions", headers=bearer("new-key")).status_code == 200
        assert client.get("/api/sessions", headers=bearer(KEY)).status_code == 401


def test_rejection_is_logged_without_the_key(with_auth, caplog):
    with caplog.at_level(logging.WARNING, logger="auth"):
        with TestClient(app) as client:
            client.get("/api/sessions", headers=bearer("leaky-secret-value"))
    messages = [r.getMessage() for r in caplog.records if r.name == "auth"]
    assert any("Rejected unauthenticated GET /api/sessions" in m for m in messages)
    assert not any("leaky-secret-value" in m for m in messages)


# --- WebSocket ---------------------------------------------------------------


@pytest.mark.parametrize("client_type", ["sdk", "ui"])
def test_ws_without_credentials_is_closed_with_4401(with_auth, client_type):
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws?client_type={client_type}") as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_text()
    assert exc.value.code == WS_CLOSE_UNAUTHORIZED


def test_ws_with_wrong_header_key_is_rejected(with_auth):
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws?client_type=sdk", headers=bearer("nope")
        ) as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_text()
    assert exc.value.code == WS_CLOSE_UNAUTHORIZED


def test_sdk_ws_with_bearer_header_can_ingest_events(with_auth):
    session_id = f"auth-sdk-{uuid.uuid4()}"
    event_id = f"ev-{uuid.uuid4()}"
    with TestClient(app) as client:
        created = client.post(
            "/api/sessions",
            json={"session_id": session_id, "name": "auth"},
            headers=bearer(),
        )
        assert created.status_code == 201
        with client.websocket_connect("/ws?client_type=sdk", headers=bearer()) as ws:
            ws.send_json(sdk_event(session_id, event_id))
            events = wait_for_events(client, session_id, 1, headers=bearer())
    assert [e["event_id"] for e in events] == [event_id]


def test_browser_style_subprotocol_auth(with_auth):
    """Browsers cannot set headers, so the UI offers the key as a subprotocol."""
    protocols = ["agentscope", encode_ws_auth_protocol(KEY)]
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws?client_type=ui", subprotocols=protocols
        ) as ws:
            # Only the plain protocol is echoed; the key is never sent back.
            assert ws.accepted_subprotocol == "agentscope"


def test_browser_style_subprotocol_with_wrong_key_is_rejected(with_auth):
    protocols = ["agentscope", encode_ws_auth_protocol("wrong")]
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws?client_type=ui", subprotocols=protocols
        ) as ws:
            # The handshake still completes (so a browser sees code 4401
            # rather than a generic connection failure).
            assert ws.accepted_subprotocol == "agentscope"
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_text()
    assert exc.value.code == WS_CLOSE_UNAUTHORIZED


def test_subprotocol_echo_without_auth_enabled(no_auth):
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws?client_type=ui", subprotocols=["agentscope"]
        ) as ws:
            assert ws.accepted_subprotocol == "agentscope"
