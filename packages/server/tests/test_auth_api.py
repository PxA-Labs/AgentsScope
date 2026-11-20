"""End-to-end auth behaviour for REST routes and the /ws endpoint."""

import logging
import re
import time
import uuid

import auth
import pytest
from auth import (
    API_KEY_ENV,
    API_KEYS_ENV,
    WS_CLOSE_UNAUTHORIZED,
    AuthConfigError,
    encode_ws_auth_protocol,
)
from fastapi.routing import APIWebSocketRoute
from fastapi.testclient import TestClient
from main import app
from starlette.routing import Route
from starlette.websockets import WebSocketDisconnect

KEY = "test-key-Abc123-0123456789"
OLD_KEY = "rotating-old-key-0123"
NEW_KEY = "rotating-new-key-4567"


@pytest.fixture(autouse=True)
def fresh_rejection_log():
    auth._rejection_log.reset()
    yield
    auth._rejection_log.reset()


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


# Routes that are deliberately reachable without a key. Anything else must
# live under /api or /ws, so a new top-level route cannot silently be public.
PUBLIC_PATHS = {"/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def concrete_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "probe-id", path)


def http_operations():
    """Every (method, path) the app serves over HTTP.

    Read from the OpenAPI schema rather than ``app.routes``, because newer
    FastAPI versions nest included routers there. Top-level routes that are
    hidden from the schema (the docs pages) are added from ``app.routes``.
    """
    ops = {
        (method.upper(), path)
        for path, item in app.openapi()["paths"].items()
        for method in item
    }
    for route in app.routes:
        if isinstance(route, Route) and not isinstance(route, APIWebSocketRoute):
            ops.update((m, route.path) for m in route.methods)
    return ops


def test_only_known_routes_are_public():
    paths = {path for _, path in http_operations()}
    paths.update(r.path for r in app.routes if isinstance(r, APIWebSocketRoute))
    unexpected = [
        p
        for p in sorted(paths)
        if p not in PUBLIC_PATHS and not (p.startswith("/api/") or p == "/ws")
    ]
    assert unexpected == []


def test_every_api_route_requires_the_key(with_auth):
    api_ops = sorted(op for op in http_operations() if op[1].startswith("/api/"))
    assert len(api_ops) >= 10, "route discovery looks broken"
    with TestClient(app) as client:
        for method, path in api_ops:
            # 401 comes before routing errors such as 404, so an attacker
            # cannot probe which sessions exist.
            res = client.request(method, concrete_path(path))
            assert res.status_code == 401, f"{method} {path}"
            assert res.headers["www-authenticate"] == "Bearer"


def test_every_websocket_route_requires_the_key(with_auth):
    ws_routes = [r for r in app.routes if isinstance(r, APIWebSocketRoute)]
    assert ws_routes, "route discovery looks broken"
    with TestClient(app) as client:
        for route in ws_routes:
            path = concrete_path(route.path) + "?client_type=sdk"
            with client.websocket_connect(path) as ws:
                with pytest.raises(WebSocketDisconnect) as exc:
                    ws.receive_text()
            assert exc.value.code == WS_CLOSE_UNAUTHORIZED, route.path


def test_auth_is_checked_before_the_body_is_parsed(with_auth):
    """An unauthenticated client must get 401, not validation details (422)."""
    with TestClient(app) as client:
        res = client.post(
            "/api/sessions",
            content=b"{not json",
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 401
        res = client.post("/api/sessions", json={"name": 123, "metadata": "x"})
        assert res.status_code == 401


def test_unknown_api_paths_are_protected_too(with_auth):
    # Covers routes added later and avoids leaking which paths exist.
    with TestClient(app) as client:
        assert client.get("/api/not-a-route").status_code == 401
        assert client.get("/api").status_code == 401
        assert client.get("/api/not-a-route", headers=bearer()).status_code == 404


def test_auth_applies_behind_a_root_path(with_auth):
    with TestClient(app, root_path="/agentscope") as client:
        assert client.get("/agentscope/api/sessions").status_code == 401
        res = client.get("/agentscope/api/sessions", headers=bearer())
        assert res.status_code == 200
        assert client.get("/agentscope/health").status_code == 200


def test_cors_preflight_and_401_carry_cors_headers(with_auth):
    origin = "http://localhost:3000"
    with TestClient(app) as client:
        preflight = client.options(
            "/api/sessions",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert preflight.status_code == 200
        assert "authorization" in preflight.headers["access-control-allow-headers"]
        # The browser can only read the 401 (and show the key prompt) if the
        # rejection carries CORS headers.
        res = client.get("/api/sessions", headers={"Origin": origin})
        assert res.status_code == 401
        assert res.headers["access-control-allow-origin"] == origin


def test_rest_accepts_valid_key(with_auth):
    with TestClient(app) as client:
        res = client.get("/api/sessions", headers=bearer())
    assert res.status_code == 200


def test_rotated_keys_are_all_accepted(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.setenv(API_KEYS_ENV, f"{OLD_KEY},{NEW_KEY}")
    with TestClient(app) as client:
        assert client.get("/api/sessions", headers=bearer(OLD_KEY)).status_code == 200
        assert client.get("/api/sessions", headers=bearer(NEW_KEY)).status_code == 200
        assert client.get("/api/sessions", headers=bearer(KEY)).status_code == 401


def test_single_key_with_comma_is_not_split(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, "secretkey-0123456789,ab")
    monkeypatch.delenv(API_KEYS_ENV, raising=False)
    with TestClient(app) as client:
        assert client.get("/api/sessions", headers=bearer("ab")).status_code == 401
        ok = client.get("/api/sessions", headers=bearer("secretkey-0123456789,ab"))
        assert ok.status_code == 200


@pytest.mark.parametrize("weak", ["change-me", "too-short"])
def test_server_refuses_to_start_with_a_weak_key(monkeypatch, weak):
    monkeypatch.setenv(API_KEY_ENV, weak)
    monkeypatch.delenv(API_KEYS_ENV, raising=False)
    with pytest.raises(AuthConfigError):
        with TestClient(app):
            pass


def test_rejection_is_logged_without_the_key(with_auth, caplog):
    with caplog.at_level(logging.WARNING, logger="auth"):
        with TestClient(app) as client:
            client.get("/api/sessions", headers=bearer("leaky-secret-value"))
    messages = [r.getMessage() for r in caplog.records if r.name == "auth"]
    assert any("Rejected unauthenticated GET /api/sessions" in m for m in messages)
    assert not any("leaky-secret-value" in m for m in messages)


def rejection_warnings(caplog):
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "auth"
        and r.levelno == logging.WARNING
        and r.getMessage().startswith("Rejected unauthenticated")
    ]


def test_rejection_logs_are_rate_limited_per_client(with_auth, caplog, monkeypatch):
    """A dashboard polling with a bad key must not flood the log."""
    now = [1000.0]
    monkeypatch.setattr(auth._rejection_log, "clock", lambda: now[0])
    with caplog.at_level(logging.WARNING, logger="auth"):
        with TestClient(app) as client:
            for _ in range(5):
                assert client.get("/api/sessions").status_code == 401
            for _ in range(3):
                with client.websocket_connect("/ws?client_type=ui") as ws:
                    with pytest.raises(WebSocketDisconnect):
                        ws.receive_text()
            assert len(rejection_warnings(caplog)) == 1

            now[0] += auth.REJECTION_LOG_WINDOW_SECONDS
            client.get("/api/sessions")
    warnings = rejection_warnings(caplog)
    assert len(warnings) == 2
    assert "7 similar rejections from this client suppressed" in warnings[1]


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
