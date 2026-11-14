"""SDK-side API-key handling (no real server)."""

import asyncio
import io
import logging
import urllib.error
import urllib.request

import pytest

from agentscope.client import API_KEY_ENV, AgentScopeClient


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


def test_status_patch_carries_key(monkeypatch):
    captured = capture_urlopen(monkeypatch, response=io.BytesIO(b"{}"))
    started = []

    class InlineThread:
        def __init__(self, target, name=None, daemon=None):
            self.target = target

        def start(self):
            started.append(True)
            self.target()

    monkeypatch.setattr("agentscope.client.threading.Thread", InlineThread)
    AgentScopeClient(api_key="k-123")._send_status_patch("sess-1", "completed")
    assert started
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


def test_websocket_connect_receives_auth_header(monkeypatch):
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
    client.running = True
    client.loop = asyncio.new_event_loop()

    async def run_once():
        # StopLoop is caught by the generic handler; stop after first attempt.
        original_sleep = asyncio.sleep

        async def stop_sleep(_):
            client.running = False
            await original_sleep(0)

        monkeypatch.setattr("agentscope.client.asyncio.sleep", stop_sleep)
        await client._main_async_loop()

    try:
        client.loop.run_until_complete(run_once())
    finally:
        client.loop.close()

    assert calls, "websockets.connect was not called"
    uri, kwargs = calls[0]
    assert uri == "ws://localhost:8765/ws?client_type=sdk"
    assert kwargs["additional_headers"] == {"Authorization": "Bearer k-ws"}


def test_websocket_connect_without_key_sends_no_headers(monkeypatch):
    calls = []

    def fake_connect(uri, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("stop")

    monkeypatch.setattr("agentscope.client.websockets.connect", fake_connect)
    client = AgentScopeClient()
    client.session_id = "sess-1"
    client.running = True
    client.loop = asyncio.new_event_loop()

    async def stop_sleep(_):
        client.running = False

    monkeypatch.setattr("agentscope.client.asyncio.sleep", stop_sleep)
    try:
        client.loop.run_until_complete(client._main_async_loop())
    finally:
        client.loop.close()
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
