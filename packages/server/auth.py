"""Optional single-tenant API-key authentication.

Authentication is **disabled** unless ``AGENTSCOPE_API_KEY`` (exactly one key,
never split) or ``AGENTSCOPE_API_KEYS`` (comma-separated, for rotation) is
set, which keeps the local, zero-configuration experience unchanged.

When enabled:

* Everything under ``/api`` requires ``Authorization: Bearer <key>``. This is
  enforced by :class:`APIKeyAuthMiddleware` before routing, so requests are
  rejected before any body is read and routes added later are covered too.
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

from fastapi import Request, WebSocket, status
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

try:  # Use the exact function Starlette's router matches routes with.
    from starlette._utils import get_route_path
except ImportError:  # pragma: no cover - older/newer Starlette layouts

    def get_route_path(scope: Scope) -> str:
        path: str = scope["path"]
        root_path = scope.get("root_path", "")
        if not root_path or not path.startswith(root_path):
            return path
        if path == root_path:
            return ""
        if path[len(root_path)] == "/":
            return path[len(root_path) :]
        return path


API_KEY_ENV = "AGENTSCOPE_API_KEY"
API_KEYS_ENV = "AGENTSCOPE_API_KEYS"

WS_SUBPROTOCOL = "agentscope"
WS_AUTH_PROTOCOL_PREFIX = "agentscope.auth."
WS_CLOSE_UNAUTHORIZED = 4401

# Key policy, enforced at startup by validate_auth_config(). Keys shorter than
# this, or copied from the examples in our docs, make the server refuse to
# start. They also never authenticate (fail closed) should the environment
# change after startup.
MIN_API_KEY_LENGTH = 16
PLACEHOLDER_API_KEYS = frozenset(
    {"change-me", "changeme", "old-key", "new-key", "<key>", "<old-key>", "<new-key>"}
)

logger = logging.getLogger(__name__)


class AuthConfigError(RuntimeError):
    """Raised at startup when the configured API keys are unsafe to use."""


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


def _weak_key_reason(key: str) -> Optional[str]:
    if key.lower() in PLACEHOLDER_API_KEYS:
        return "is a placeholder value from the documentation"
    if len(key) < MIN_API_KEY_LENGTH:
        return f"is shorter than {MIN_API_KEY_LENGTH} characters"
    return None


def validate_auth_config() -> None:
    """Check the API-key environment at startup.

    * Warns when a variable is set but blank and auth therefore stays disabled
      (e.g. ``AGENTSCOPE_API_KEY=${UNSET_VAR}`` in a compose file).
    * Warns when ``AGENTSCOPE_API_KEY`` contains a comma, since it is used as
      one key and is never split.
    * Raises :class:`AuthConfigError` for placeholder or short keys.

    Key values are never included in log messages or exceptions.
    """
    single_raw = os.getenv(API_KEY_ENV)
    if single_raw is not None and "," in single_raw:
        logger.warning(
            "%s contains a comma and is used as one single key. Use %s for "
            "several comma-separated keys.",
            API_KEY_ENV,
            API_KEYS_ENV,
        )

    problems = []
    single = (single_raw or "").strip()
    if single:
        reason = _weak_key_reason(single)
        if reason:
            problems.append(f"{API_KEY_ENV} {reason}")
    for index, key in enumerate(
        k.strip() for k in os.getenv(API_KEYS_ENV, "").split(",") if k.strip()
    ):
        reason = _weak_key_reason(key)
        if reason:
            problems.append(f"key #{index + 1} in {API_KEYS_ENV} {reason}")
    if problems:
        raise AuthConfigError(
            "Refusing to start with a weak API key: "
            + "; ".join(problems)
            + '. Generate one with: python -c "import secrets; '
            'print(secrets.token_urlsafe(32))"'
        )

    if auth_enabled():
        logger.info(
            "API-key authentication enabled (%d key(s) configured).",
            len(configured_api_keys()),
        )
        return
    blank = [name for name in (API_KEY_ENV, API_KEYS_ENV) if name in os.environ]
    if blank:
        logger.warning(
            "%s %s set but empty, so API-key authentication is DISABLED and "
            "/api and /ws are open to anyone who can reach this server.",
            " and ".join(blank),
            "is" if len(blank) == 1 else "are",
        )


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
        equal = hmac.compare_digest(candidate_digest, _digest(key))
        # Weak keys never authenticate, but they still count as configured
        # (auth stays enabled), so a bad key fails closed rather than open.
        matched |= equal and _weak_key_reason(key) is None
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


async def _reject_http(scope: Scope, receive: Receive, send: Send) -> None:
    request = Request(scope)
    safe_path = request.url.path.replace("\r", "").replace("\n", "")
    logger.warning(
        "Rejected unauthenticated %s %s from %s",
        request.method,
        safe_path,
        _client_for_log(request.client),
    )
    response = JSONResponse(
        {"detail": "Missing or invalid API key"},
        status_code=status.HTTP_401_UNAUTHORIZED,
        headers={"WWW-Authenticate": "Bearer"},
    )
    await response(scope, receive, send)


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


PROTECTED_PATH_PREFIXES = ("/api", "/ws")


def is_protected_path(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in PROTECTED_PATH_PREFIXES)


class APIKeyAuthMiddleware:
    """Pure ASGI middleware enforcing the API key on ``/api`` and ``/ws``.

    Runs before routing, so FastAPI never reads or validates the body of an
    unauthenticated request (401, not 422) and new routes under these
    prefixes are protected automatically. Other paths (``/health``, docs)
    pass through untouched. Add it *before* ``CORSMiddleware`` so CORS stays
    the outer layer: preflights are answered without a key and 401 responses
    still carry CORS headers the dashboard can read.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not auth_enabled():
            await self.app(scope, receive, send)
            return
        # Check the route path (root_path stripped, as the router sees it)
        # and the raw path, so a mismatch can only ever fail closed.
        if not (
            is_protected_path(get_route_path(scope)) or is_protected_path(scope["path"])
        ):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "http":
            headers = Request(scope).headers
            if is_valid_api_key(_bearer_token(headers.get("authorization"))):
                await self.app(scope, receive, send)
            else:
                await _reject_http(scope, receive, send)
            return

        if await authorize_websocket(WebSocket(scope, receive, send)):
            await self.app(scope, receive, send)
