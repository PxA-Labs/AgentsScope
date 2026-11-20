"""SDK-side API-key handling (no real server)."""

import io
import logging
import threading
import time
import urllib.error
import urllib.request

import pytest

import agentscope.client
from agentscope.client import (
    API_KEY_ENV,
    MAX_BACKOFF_SECONDS,
    WS_CLOSE_UNAUTHORIZED,
    AgentScopeClient,
)

RealThread = threading.Thread


@pytest.fixture(autouse=True)
def clear_key_env(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)


def capture_urlopen(monkeypatch, response=None, error=None):
    captured = []

    def fake_urlopen(req, timeout=None):
        captured.append(req)
        if error is not None:
            raise error
        return response or io.BytesIO(b'{"session_id": "sess-1"}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return captured


def http_401(url="http://localhost:8765/api/sessions"):
    return urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b""))


def test_no_key_sends_no_authorization_header(monkeypatch):
    captured = capture_urlopen(monkeypatch)
    client = AgentScopeClient()
    client._create_session_sync()
    assert client.session_id == "sess-1"
    assert captured[0].get_header("Authorization") is None


def test_explicit_key_is_sent_on_session_creation(monkeypatch):
    captured = capture_urlopen(monkeypatch)
    AgentScopeClient(api_key="k-123")._create_session_sync()
    assert captured[0].get_header("Authorization") == "Bearer k-123"
    assert captured[0].get_header("Content-type") == "application/json"


def test_key_falls_back_to_environment(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, "env-key")
    captured = capture_urlopen(monkeypatch)
    AgentScopeClient()._create_session_sync()
    assert captured[0].get_header("Authorization") == "Bearer env-key"


def test_explicit_key_overrides_environment(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, "env-key")
    captured = capture_urlopen(monkeypatch)
    AgentScopeClient(api_key="arg-key")._create_session_sync()
    assert captured[0].get_header("Authorization") == "Bearer arg-key"


def test_status_patch_carries_key(monkeypatch, inline_status_patch):
    captured = capture_urlopen(monkeypatch, response=io.BytesIO(b"{}"))
    AgentScopeClient(api_key="k-123")._send_status_patch("sess-1", "completed")
    assert inline_status_patch
    # Only the PATCH thread runs inline: threading.Thread itself and the
    # threads the sender creates through agentscope.client stay real.
    assert threading.Thread is RealThread
    assert isinstance(
        agentscope.client.threading.Thread(target=lambda: None), RealThread
    )
    assert captured[0].get_method() == "PATCH"
    assert captured[0].get_header("Authorization") == "Bearer k-123"


def test_401_is_logged_once_and_never_raises(monkeypatch, caplog):
    capture_urlopen(monkeypatch, error=http_401())
    client = AgentScopeClient(api_key="bad-key")
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            client._create_session_sync()  # must not raise
    hints = [r for r in caplog.records if "rejected the API key" in r.getMessage()]
    assert len(hints) == 1
    assert client.session_id is None
    assert all("bad-key" not in r.getMessage() for r in caplog.records)


def test_other_http_errors_keep_generic_warning(monkeypatch, caplog):
    err = urllib.error.HTTPError("u", 500, "boom", {}, io.BytesIO(b""))
    capture_urlopen(monkeypatch, error=err)
    with caplog.at_level(logging.WARNING):
        AgentScopeClient(api_key="k")._create_session_sync()
    messages = [r.getMessage() for r in caplog.records]
    assert any("Failed to register session" in m for m in messages)
    assert not any("rejected the API key" in m for m in messages)


def test_websocket_connect_receives_auth_header(monkeypatch, run_sender_loop):
    """The background loop must pass the Bearer header to websockets.connect."""
    calls = []

    class StopLoop(Exception):
        pass

    def fake_connect(uri, **kwargs):
        calls.append((uri, kwargs))
        raise StopLoop

    monkeypatch.setattr("agentscope.client.websockets.connect", fake_connect)
    client = AgentScopeClient(api_key="k-ws")
    client.session_id = "sess-1"  # skip REST registration
    # StopLoop is caught by the generic handler, which backs off; the fixture
    # stops the sender at that first backoff.
    run_sender_loop(client)

    assert len(calls) == 1, "websockets.connect was not called"
    uri, kwargs = calls[0]
    assert uri == "ws://localhost:8765/ws?client_type=sdk"
    assert kwargs["additional_headers"] == {"Authorization": "Bearer k-ws"}


def test_websocket_connect_without_key_sends_no_headers(monkeypatch, run_sender_loop):
    calls = []

    def fake_connect(uri, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("stop")

    monkeypatch.setattr("agentscope.client.websockets.connect", fake_connect)
    client = AgentScopeClient()
    client.session_id = "sess-1"
    run_sender_loop(client)
    assert len(calls) == 1
    assert calls[0]["additional_headers"] is None


def test_callback_and_configure_forward_api_key(monkeypatch):
    pytest.importorskip("langchain_core")
    from agentscope import AgentScopeCallback, decorators

    cb = AgentScopeCallback(api_key="cb-key")
    assert cb.client._auth_headers() == {"Authorization": "Bearer cb-key"}

    monkeypatch.setattr(decorators, "_global_client", None)
    decorators.configure(api_key="cfg-key")
    try:
        assert decorators.get_global_client()._auth_headers() == {
            "Authorization": "Bearer cfg-key"
        }
    finally:
        decorators.get_global_client().stop()
        monkeypatch.setattr(decorators, "_global_client", None)


def test_api_key_not_exposed_in_repr():
    client = AgentScopeClient(api_key="super-secret")
    assert "super-secret" not in repr(client)
    assert "super-secret" not in str(vars(client).get("api_key", ""))


class RejectingSocket:
    """A server that completes the handshake, then closes with 4401."""

    def __init__(self, connects, uri):
        connects.append(uri)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, _message):
        from websockets.exceptions import ConnectionClosedError
        from websockets.frames import Close

        raise ConnectionClosedError(Close(WS_CLOSE_UNAUTHORIZED, "Unauthorized"), None)


def patch_4401_server(monkeypatch):
    connects = []
    monkeypatch.setattr(
        "agentscope.client.websockets.connect",
        lambda uri, **kwargs: RejectingSocket(connects, uri),
    )
    return connects


def test_4401_close_backs_off_to_max_instead_of_reconnecting_every_second(
    monkeypatch, caplog, run_sender_loop
):
    connects = patch_4401_server(monkeypatch)
    client = AgentScopeClient(api_key="bad-key")
    client.session_id = "sess-1"
    client.queue.put({"event_id": "e1"})
    with caplog.at_level(logging.DEBUG):
        sleeps = run_sender_loop(client, backoffs=5)
    assert len(connects) == 5
    # The handshake succeeds before the 4401 close, which used to reset the
    # backoff to 1 s each time. Rejected credentials won't fix themselves.
    assert sleeps == [MAX_BACKOFF_SECONDS] * 5
    assert AgentScopeClient._max_backoff == MAX_BACKOFF_SECONDS
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    # One actionable hint; the per-retry noise is demoted to DEBUG.
    assert warnings == [warnings[0]] and "rejected the API key" in warnings[0]
    assert all("bad-key" not in r.getMessage() for r in caplog.records)


def test_stop_interrupts_the_4401_backoff(monkeypatch, caplog):
    """stop() must not wait out the 30 s backoff after a 4401 close."""
    connects = patch_4401_server(monkeypatch)

    def register(self):
        self.session_id = "sess-1"

    monkeypatch.setattr(AgentScopeClient, "_create_session_sync", register)
    client = AgentScopeClient(api_key="bad-key")
    with caplog.at_level(logging.WARNING):
        client.emit({"event_id": "e1"})
        deadline = time.monotonic() + 5
        while not connects and time.monotonic() < deadline:
            time.sleep(0.01)
        assert connects, "the sender never connected"
        time.sleep(0.1)  # now inside the 30 s backoff
        started = time.monotonic()
        client.stop(timeout=0.5)
        elapsed = time.monotonic() - started
    assert elapsed < 2.0
    assert client.running is False
    # Retries continue only until the stop deadline.
    assert len(connects) <= 3
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1 and "rejected the API key" in warnings[0]


# --- the key must not follow redirects ---------------------------------------
#
# urllib forwards ordinary request headers when it follows a 301/302/303. A
# misconfigured or hostile proxy in front of an https server could redirect the
# session POST to plain http (or another host) and receive the key in
# cleartext. The Authorization header must stay on the original request only.


def _serve(handler_cls):
    import http.server
    import threading

    server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_authorization_header_is_not_forwarded_on_redirect():
    import http.server

    seen_by_target = []

    class Target(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen_by_target.append(self.headers.get("Authorization"))
            body = b'{"session_id": "sess-redirected"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    target = _serve(Target)

    class Redirector(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(302)
            self.send_header(
                "Location", f"http://127.0.0.1:{target.server_port}/stolen"
            )
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    redirector = _serve(Redirector)
    try:
        client = AgentScopeClient(
            base_url=f"http://127.0.0.1:{redirector.server_port}",
            api_key="secret-key-should-not-leak-0123",
        )
        client._create_session_sync()
    finally:
        redirector.shutdown()
        target.shutdown()

    assert seen_by_target == [None]
