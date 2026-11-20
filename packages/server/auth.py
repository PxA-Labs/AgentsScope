"""Optional single-tenant API-key authentication.

Authentication is **disabled** unless ``AGENTSCOPE_API_KEY`` (exactly one key,
never split) or ``AGENTSCOPE_API_KEYS`` (comma-separated, for rotation) is
set, which keeps the local, zero-configuration experience unchanged.

When enabled:

* REST routes under ``/api`` require ``Authorization: Bearer <key>``.
* The ``/ws`` endpoint accepts the key either as an ``Authorization: Bearer``
  header (used by the Python SDK) or, because browsers cannot set headers on
  WebSocket connections, as a ``Sec-WebSocket-Protocol`` entry of the form
  ``agentscope.auth.<base64url(key)>`` offered next to ``agentscope``. The key
  is never put in the URL, so it does not end up in access logs.
* Rejected WebSocket clients are accepted and immediately closed with code
  ``4401`` so browsers can tell "unauthorized" apart from "server down".
"""

import base64
import binascii
import hashlib
import hmac
import logging
import os
from typing import List, Optional

from fastapi import HTTPException, Request, WebSocket, status

API_KEY_ENV = "AGENTSCOPE_API_KEY"
API_KEYS_ENV = "AGENTSCOPE_API_KEYS"

WS_SUBPROTOCOL = "agentscope"
WS_AUTH_PROTOCOL_PREFIX = "agentscope.auth."
WS_CLOSE_UNAUTHORIZED = 4401

logger = logging.getLogger(__name__)


def configured_api_keys() -> List[str]:
    """Return the accepted API keys (empty list means auth is disabled).

    Read on each call so that tests and process managers that change the
    environment take effect without re-importing the module.
    """
    keys: List[str] = []
    # AGENTSCOPE_API_KEY is exactly one key and is never split: a key that
    # happens to contain a comma must not turn into several shorter keys.
    single = os.getenv(API_KEY_ENV, "").strip()
    if single:
        keys.append(single)
    raw_list = os.getenv(API_KEYS_ENV, "")
    keys.extend(k.strip() for k in raw_list.split(",") if k.strip())
    return keys


def auth_enabled() -> bool:
    return bool(configured_api_keys())


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def is_valid_api_key(candidate: Optional[str]) -> bool:
    """Constant-time comparison against every configured key.

    SHA-256 digests are compared rather than the raw strings, so both sides
    always have the same length and timing does not reveal the key length.
    """
    if not candidate:
        return False
    candidate_digest = _digest(candidate)
    matched = False
    for key in configured_api_keys():
        # Compare against all keys (no early exit) so timing does not reveal
        # which key, if any, partially matched.
        matched |= hmac.compare_digest(candidate_digest, _digest(key))
    return matched


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def encode_ws_auth_protocol(api_key: str) -> str:
    """Build the ``Sec-WebSocket-Protocol`` entry that carries an API key."""
    encoded = base64.urlsafe_b64encode(api_key.encode("utf-8")).decode("ascii")
    return WS_AUTH_PROTOCOL_PREFIX + encoded.rstrip("=")


def _decode_ws_auth_protocol(protocol: str) -> Optional[str]:
    encoded = protocol[len(WS_AUTH_PROTOCOL_PREFIX) :]
    if not encoded:
        return None
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        # validate=True rejects characters outside the base64url alphabet
        # instead of silently discarding them.
        decoded = base64.b64decode(
            padded.encode("ascii"), altchars=b"-_", validate=True
        ).decode("utf-8")
    except (binascii.Error, UnicodeError, ValueError):
        return None
    return decoded or None


def offered_subprotocols(websocket: WebSocket) -> List[str]:
    raw = websocket.headers.get("sec-websocket-protocol", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def negotiated_subprotocol(websocket: WebSocket) -> Optional[str]:
    """Subprotocol to echo on accept.

    Browsers abort the handshake if they offered subprotocols and the server
    selects none, so echo ``agentscope`` when it was offered. The auth entry is
    never echoed back.
    """
    if WS_SUBPROTOCOL in offered_subprotocols(websocket):
        return WS_SUBPROTOCOL
    return None


def _websocket_token(websocket: WebSocket) -> Optional[str]:
    token = _bearer_token(websocket.headers.get("authorization"))
    if token:
        return token
    for protocol in offered_subprotocols(websocket):
        if protocol.startswith(WS_AUTH_PROTOCOL_PREFIX):
            return _decode_ws_auth_protocol(protocol)
    return None


def _client_for_log(client) -> str:
    host = getattr(client, "host", None) or "unknown"
    return host.replace("\r", "").replace("\n", "")


async def require_api_key(request: Request) -> None:
    """FastAPI dependency guarding REST routes."""
    if not auth_enabled():
        return
    if is_valid_api_key(_bearer_token(request.headers.get("authorization"))):
        return
    safe_path = request.url.path.replace("\r", "").replace("\n", "")
    logger.warning(
        "Rejected unauthenticated %s %s from %s",
        request.method,
        safe_path,
        _client_for_log(request.client),
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid API key",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def authorize_websocket(websocket: WebSocket) -> bool:
    """Return True if the WebSocket may proceed; otherwise reject it.

    Must be called before ``accept()``. On rejection the socket is accepted
    (with the negotiated subprotocol, so browsers complete the handshake) and
    immediately closed with ``WS_CLOSE_UNAUTHORIZED``; no messages are read.
    """
    if not auth_enabled():
        return True
    if is_valid_api_key(_websocket_token(websocket)):
        return True
    logger.warning(
        "Rejected unauthenticated WebSocket connection from %s",
        _client_for_log(websocket.client),
    )
    await websocket.accept(subprotocol=negotiated_subprotocol(websocket))
    await websocket.close(code=WS_CLOSE_UNAUTHORIZED, reason="Unauthorized")
    return False
