"""Server URL derivation: plain http/ws by default, https/wss when asked."""

import asyncio
import io
import logging
import urllib.request

import pytest

from agentscope.client import API_KEY_ENV, AgentScopeClient, server_urls


@pytest.fixture(autouse=True)
def clear_key_env(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({}, ("http://localhost:8765", "ws://localhost:8765")),
        (
            {"host": "10.0.0.5", "port": 9000},
            ("http://10.0.0.5:9000", "ws://10.0.0.5:9000"),
        ),
        ({"secure": True}, ("https://localhost:8765", "wss://localhost:8765")),
        (
            {"host": "obs.example.com", "port": 443, "secure": True},
            ("https://obs.example.com:443", "wss://obs.example.com:443"),
        ),
        (
            {"base_url": "https://obs.example.com"},
            ("https://obs.example.com", "wss://obs.example.com"),
        ),
        (
            {"base_url": "wss://obs.example.com:8443/agentscope/"},
            (
                "https://obs.example.com:8443/agentscope",
                "wss://obs.example.com:8443/agentscope",
            ),
        ),
        ({"base_url": "http://box:8765"}, ("http://box:8765", "ws://box:8765")),
        ({"base_url": "ws://box:8765"}, ("http://box:8765", "ws://box:8765")),
        (
            {"base_url": "HTTPS://Obs.Example.com", "secure": True},
            ("https://Obs.Example.com", "wss://Obs.Example.com"),
        ),
        # base_url wins over host/port.
        (
            {"host": "ignored", "port": 1, "base_url": "https://real.example"},
            ("https://real.example", "wss://real.example"),
        ),
    ],
)
def test_server_url_derivation(kwargs, expected):
    assert server_urls(**kwargs) == expected
    client = AgentScopeClient(**kwargs)
    assert (client.http_base_url, client.ws_base_url) == expected


@pytest.mark.parametrize(
    "base_url",
    [
        "obs.example.com",  # no scheme
        "ftp://obs.example.com",
        "https://",
        "https://user:pw@obs.example.com",  # credentials don't belong in URLs
        "https://obs.example.com/?token=x",
        "https://obs.example.com/#frag",
        "https://obs.example.com:notaport",
    ],
)
def test_invalid_base_url_is_rejected(base_url):
    with pytest.raises(ValueError):
        AgentScopeClient(base_url=base_url)


@pytest.mark.parametrize("base_url", ["http://obs.example.com", "ws://obs.example.com"])
def test_secure_flag_conflicting_with_plain_base_url_is_rejected(base_url):
    with pytest.raises(ValueError):
        AgentScopeClient(base_url=base_url, secure=True)


def test_host_and_port_attributes_follow_base_url():
    client = AgentScopeClient(base_url="https://obs.example.com")
    assert (client.host, client.port) == ("obs.example.com", 443)
    client = AgentScopeClient(base_url="ws://box")
    assert (client.host, client.port) == ("box", 80)


def capture_urlopen(monkeypatch, body=b'{"session_id": "sess-1"}'):
    captured = []

    def fake_urlopen(req, timeout=None):
        captured.append(req)
        return io.BytesIO(body)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return captured


def test_rest_calls_use_https(monkeypatch):
    captured = capture_urlopen(monkeypatch)
    client = AgentScopeClient(base_url="https://obs.example.com/agentscope")
    client._create_session_sync()
    assert captured[0].full_url == "https://obs.example.com/agentscope/api/sessions"

    class InlineThread:
        def __init__(self, target, name=None, daemon=None):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr("agentscope.client.threading.Thread", InlineThread)
    client._send_status_patch("sess-1", "completed")
    assert (
        captured[1].full_url == "https://obs.example.com/agentscope/api/sessions/sess-1"
    )


def test_websocket_uses_wss(monkeypatch):
    uris = []

    def fake_connect(uri, **kwargs):
        uris.append(uri)
        raise RuntimeError("stop")

    monkeypatch.setattr("agentscope.client.websockets.connect", fake_connect)
    client = AgentScopeClient(host="obs.example.com", port=443, secure=True)
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
    assert uris == ["wss://obs.example.com:443/ws?client_type=sdk"]


def cleartext_warnings(caplog):
    return [r for r in caplog.records if "unencrypted" in r.getMessage()]


def test_warns_when_key_would_travel_in_cleartext_to_a_remote_host(caplog):
    with caplog.at_level(logging.WARNING):
        AgentScopeClient(host="obs.example.com", api_key="secret-key-value")
    warnings = cleartext_warnings(caplog)
    assert len(warnings) == 1
    assert "secret-key-value" not in warnings[0].getMessage()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"api_key": "k"},  # localhost
        {"host": "127.0.0.1", "api_key": "k"},
        {"host": "::1", "api_key": "k"},
        {"host": "obs.example.com", "secure": True, "api_key": "k"},
        {"base_url": "https://obs.example.com", "api_key": "k"},
        {"host": "obs.example.com"},  # no key, nothing to leak
    ],
)
def test_no_cleartext_warning_when_safe(caplog, kwargs):
    with caplog.at_level(logging.WARNING):
        AgentScopeClient(**kwargs)
    assert cleartext_warnings(caplog) == []


def test_callback_and_configure_forward_url_options(monkeypatch):
    from agentscope import decorators

    monkeypatch.setattr(decorators, "_global_client", None)
    decorators.configure(base_url="https://obs.example.com")
    try:
        assert decorators.get_global_client().ws_base_url == "wss://obs.example.com"
    finally:
        decorators.get_global_client().stop()
        monkeypatch.setattr(decorators, "_global_client", None)

    decorators.configure(host="obs.example.com", port=443, secure=True)
    try:
        client = decorators.get_global_client()
        assert client.http_base_url == "https://obs.example.com:443"
    finally:
        decorators.get_global_client().stop()
        monkeypatch.setattr(decorators, "_global_client", None)

    pytest.importorskip("langchain_core")
    from agentscope import AgentScopeCallback

    cb = AgentScopeCallback(base_url="https://obs.example.com")
    assert cb.client.http_base_url == "https://obs.example.com"
    cb = AgentScopeCallback(host="obs.example.com", port=443, secure=True)
    assert cb.client.ws_base_url == "wss://obs.example.com:443"
