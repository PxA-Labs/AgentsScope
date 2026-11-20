"""Unit tests for auth.py helpers (no HTTP)."""

import logging

import auth
import pytest
from auth import (
    API_KEY_ENV,
    API_KEYS_ENV,
    MIN_API_KEY_LENGTH,
    WS_AUTH_PROTOCOL_PREFIX,
    AuthConfigError,
    _bearer_token,
    _decode_ws_auth_protocol,
    auth_enabled,
    configured_api_keys,
    encode_ws_auth_protocol,
    is_valid_api_key,
    validate_auth_config,
)


@pytest.fixture(autouse=True)
def clear_auth_env(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.delenv(API_KEYS_ENV, raising=False)


def test_auth_disabled_by_default():
    assert configured_api_keys() == []
    assert auth_enabled() is False
    assert is_valid_api_key("anything") is False


PRIMARY = "primary-key-0123456789"
OLD = "rotating-old-key-0123"
NEW = "rotating-new-key-4567"


def test_single_and_rotated_keys_are_combined(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, PRIMARY)
    monkeypatch.setenv(API_KEYS_ENV, f" {OLD} , {NEW} ,, ")
    assert configured_api_keys() == [PRIMARY, OLD, NEW]
    assert auth_enabled() is True
    for key in (PRIMARY, OLD, NEW):
        assert is_valid_api_key(key)


def test_single_key_variable_is_not_split_on_commas(monkeypatch):
    # AGENTSCOPE_API_KEY holds exactly one key. Splitting it would turn a key
    # containing a comma into several much weaker keys.
    monkeypatch.setenv(API_KEY_ENV, " secretkey-0123456789,ab ")
    assert configured_api_keys() == ["secretkey-0123456789,ab"]
    assert is_valid_api_key("secretkey-0123456789,ab")
    assert not is_valid_api_key("ab")
    assert not is_valid_api_key("secretkey-0123456789")


def test_blank_env_values_do_not_enable_auth(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, "   ")
    monkeypatch.setenv(API_KEYS_ENV, ",")
    assert auth_enabled() is False


@pytest.mark.parametrize(
    "candidate", [None, "", PRIMARY[:-1], PRIMARY + "2", PRIMARY.upper()]
)
def test_invalid_candidates_rejected(monkeypatch, candidate):
    monkeypatch.setenv(API_KEY_ENV, PRIMARY)
    assert is_valid_api_key(candidate) is False


def test_comparison_uses_fixed_length_digests(monkeypatch):
    """Compare SHA-256 digests so the key length is not leaked via timing."""
    calls = []
    real = auth.hmac.compare_digest

    def spy(a, b):
        calls.append((len(a), len(b)))
        return real(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", spy)
    monkeypatch.setenv(API_KEY_ENV, PRIMARY)
    monkeypatch.setenv(API_KEYS_ENV, f"{OLD},{NEW}x")
    assert is_valid_api_key("short") is False
    assert is_valid_api_key(NEW + "x") is True
    # Every configured key is compared (no early exit), always 32 vs 32 bytes.
    assert calls == [(32, 32)] * 6


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


# --- Startup validation ------------------------------------------------------


def auth_warnings(caplog):
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "auth" and r.levelno == logging.WARNING
    ]


def test_validation_is_quiet_when_auth_is_not_configured(caplog):
    with caplog.at_level(logging.INFO, logger="auth"):
        validate_auth_config()
    assert auth_warnings(caplog) == []


@pytest.mark.parametrize(
    "env_name,value", [(API_KEY_ENV, "   "), (API_KEY_ENV, ""), (API_KEYS_ENV, " , ")]
)
def test_blank_value_warns_that_auth_is_disabled(monkeypatch, caplog, env_name, value):
    monkeypatch.setenv(env_name, value)
    with caplog.at_level(logging.WARNING, logger="auth"):
        validate_auth_config()
    warnings = auth_warnings(caplog)
    assert len(warnings) == 1
    assert env_name in warnings[0]
    assert "DISABLED" in warnings[0]


def test_blank_value_is_harmless_when_other_variable_has_keys(monkeypatch, caplog):
    monkeypatch.setenv(API_KEY_ENV, " ")
    monkeypatch.setenv(API_KEYS_ENV, f"{OLD},{NEW}")
    with caplog.at_level(logging.WARNING, logger="auth"):
        validate_auth_config()
    assert auth_warnings(caplog) == []


def test_comma_in_single_key_variable_warns(monkeypatch, caplog):
    monkeypatch.setenv(API_KEY_ENV, f"{OLD},{NEW}")
    with caplog.at_level(logging.WARNING, logger="auth"):
        validate_auth_config()
    warnings = auth_warnings(caplog)
    assert len(warnings) == 1
    assert API_KEYS_ENV in warnings[0]
    assert OLD not in warnings[0] and NEW not in warnings[0]


@pytest.mark.parametrize(
    "env_name,value",
    [
        (API_KEY_ENV, "change-me"),
        (API_KEY_ENV, "CHANGE-ME"),
        (API_KEY_ENV, "xyz123"),
        (API_KEY_ENV, "a" * (MIN_API_KEY_LENGTH - 1)),
        (API_KEYS_ENV, f"{OLD},old-key"),
        (API_KEYS_ENV, f"{OLD},tiny"),
    ],
)
def test_weak_keys_refuse_to_start(monkeypatch, env_name, value):
    monkeypatch.setenv(env_name, value)
    with pytest.raises(AuthConfigError) as exc:
        validate_auth_config()
    message = str(exc.value)
    assert env_name in message
    # The offending value itself is never echoed.
    for part in value.split(","):
        assert part not in message


def test_minimum_length_key_is_accepted(monkeypatch, caplog):
    monkeypatch.setenv(API_KEY_ENV, "k" * MIN_API_KEY_LENGTH)
    with caplog.at_level(logging.WARNING, logger="auth"):
        validate_auth_config()
    assert auth_warnings(caplog) == []


@pytest.mark.parametrize("weak", ["change-me", "short"])
def test_weak_keys_never_authenticate_but_keep_auth_enabled(monkeypatch, weak):
    """Fail closed if the environment changes after startup validation."""
    monkeypatch.setenv(API_KEY_ENV, weak)
    assert auth_enabled() is True
    assert is_valid_api_key(weak) is False
