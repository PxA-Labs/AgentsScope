"""Unit tests for auth.py helpers (no HTTP)."""

import pytest
from auth import (
    API_KEY_ENV,
    API_KEYS_ENV,
    WS_AUTH_PROTOCOL_PREFIX,
    _bearer_token,
    _decode_ws_auth_protocol,
    auth_enabled,
    configured_api_keys,
    encode_ws_auth_protocol,
    is_valid_api_key,
)


@pytest.fixture(autouse=True)
def clear_auth_env(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.delenv(API_KEYS_ENV, raising=False)


def test_auth_disabled_by_default():
    assert configured_api_keys() == []
    assert auth_enabled() is False
    assert is_valid_api_key("anything") is False


def test_single_and_rotated_keys_are_combined(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, "primary")
    monkeypatch.setenv(API_KEYS_ENV, " old-key , new-key ,, ")
    assert configured_api_keys() == ["primary", "old-key", "new-key"]
    assert auth_enabled() is True
    for key in ("primary", "old-key", "new-key"):
        assert is_valid_api_key(key)


def test_blank_env_values_do_not_enable_auth(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, "   ")
    monkeypatch.setenv(API_KEYS_ENV, ",")
    assert auth_enabled() is False


@pytest.mark.parametrize("candidate", [None, "", "primar", "primary2", "PRIMARY"])
def test_invalid_candidates_rejected(monkeypatch, candidate):
    monkeypatch.setenv(API_KEY_ENV, "primary")
    assert is_valid_api_key(candidate) is False


@pytest.mark.parametrize(
    "header,expected",
    [
        ("Bearer abc", "abc"),
        ("bearer abc", "abc"),
        ("BEARER   abc  ", "abc"),
        ("Basic abc", None),
        ("Bearer", None),
        ("Bearer   ", None),
        ("abc", None),
        (None, None),
    ],
)
def test_bearer_token_parsing(header, expected):
    assert _bearer_token(header) == expected


@pytest.mark.parametrize(
    "key", ["simple", "with/slash+plus=eq", "ünïcode-🔑", "a" * 200]
)
def test_ws_auth_protocol_round_trip(key):
    protocol = encode_ws_auth_protocol(key)
    assert protocol.startswith(WS_AUTH_PROTOCOL_PREFIX)
    # RFC 6455 subprotocol values must be HTTP tokens: no separators or padding.
    assert all(c.isalnum() or c in "-_." for c in protocol)
    assert _decode_ws_auth_protocol(protocol) == key


@pytest.mark.parametrize(
    "protocol",
    [
        WS_AUTH_PROTOCOL_PREFIX,
        WS_AUTH_PROTOCOL_PREFIX + "!!!",
        WS_AUTH_PROTOCOL_PREFIX + "_w",
    ],
)
def test_malformed_ws_auth_protocol_returns_none(protocol):
    assert _decode_ws_auth_protocol(protocol) is None
