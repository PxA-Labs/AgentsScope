import asyncio
import json
import logging
import os
import queue
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import websockets
import websockets.exceptions

API_KEY_ENV = "AGENTSCOPE_API_KEY"
WS_CLOSE_UNAUTHORIZED = 4401
MAX_BACKOFF_SECONDS = 30.0
# A plain literal (no interpolated values) so log scanners can see that no
# credential is ever logged; it only names the environment variable.
_UNAUTHORIZED_HINT = (
    "AgentScope server rejected the API key (401). Pass api_key=... or set the "
    "AGENTSCOPE_API_KEY environment variable to a key configured on the server."
)

_CLEARTEXT_KEY_WARNING = (
    "AgentScope is configured with an API key but connects to a non-local "
    "server over plain http/ws, so the key travels unencrypted. Use "
    "base_url='https://...' or secure=True."
)
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
_SECURE_SCHEMES = {"https", "wss"}
_PLAIN_SCHEMES = {"http", "ws"}


def server_urls(
    host: str = "localhost",
    port: int = 8765,
    secure: bool = False,
    base_url: Optional[str] = None,
) -> Tuple[str, str]:
    """Return the ``(http_base, ws_base)`` URLs of the AgentScope server.

    With ``base_url`` (``http``, ``https``, ``ws`` or ``wss``; an optional path
    prefix is kept for reverse proxies) ``host`` and ``port`` are ignored and
    the scheme decides between plain and TLS. Otherwise ``secure`` selects
    ``https``/``wss`` instead of ``http``/``ws`` for ``host:port``.

    Raises:
        ValueError: if ``base_url`` is malformed, or ``secure=True`` is
            combined with a plain ``http``/``ws`` base URL.
    """
    if base_url is None:
        http_scheme, ws_scheme = ("https", "wss") if secure else ("http", "ws")
        netloc = f"{host}:{port}"
        return f"{http_scheme}://{netloc}", f"{ws_scheme}://{netloc}"

    parsed = urllib.parse.urlsplit(base_url.strip())
    scheme = parsed.scheme.lower()
    if scheme not in _SECURE_SCHEMES | _PLAIN_SCHEMES:
        raise ValueError("base_url must start with http://, https://, ws:// or wss://")
    if not parsed.hostname:
        raise ValueError("base_url must include a host name")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            "base_url must not contain credentials, a query string or a fragment"
        )
    parsed.port  # raises ValueError for a malformed port
    is_secure = scheme in _SECURE_SCHEMES
    if secure and not is_secure:
        raise ValueError(f"secure=True conflicts with the {scheme}:// base_url")
    prefix = f"{parsed.netloc}{parsed.path.rstrip('/')}"
    if is_secure:
        return f"https://{prefix}", f"wss://{prefix}"
    return f"http://{prefix}", f"ws://{prefix}"


def _is_auth_close(exc: BaseException) -> bool:
    """True if the server closed the WebSocket because it rejected the key."""
    return (
        isinstance(exc, websockets.exceptions.ConnectionClosed)
        and exc.rcvd is not None
        and exc.rcvd.code == WS_CLOSE_UNAUTHORIZED
    )


class AgentScopeClient:
    """Thread-safe WebSocket and REST client for the AgentScope observability server.

    Employs a background daemon thread with its own asyncio event loop to handle
    all networking out-of-band. Ensures zero latency impact on the agent pipeline.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8765,
        session_name: Optional[str] = None,
        session_metadata: Optional[Dict[str, Any]] = None,
        batch_size: int = 50,
        flush_interval_seconds: float = 0.1,
        api_key: Optional[str] = None,
        secure: bool = False,
        base_url: Optional[str] = None,
    ):
        """Create a client.

        Args:
            host: Server host name (ignored when ``base_url`` is given).
            port: Server port (ignored when ``base_url`` is given).
            api_key: API key for servers with authentication enabled. Defaults
                to the AGENTSCOPE_API_KEY environment variable.
            secure: Use TLS (``https``/``wss``) for ``host:port``.
            base_url: Full server URL such as ``https://agentscope.example.com``
                (``http``/``https``/``ws``/``wss``); its scheme decides between
                plain and TLS connections.
        """
        self.http_base_url, self.ws_base_url = server_urls(host, port, secure, base_url)
        if base_url is None:
            self.host = host
            self.port = port
        else:
            parsed = urllib.parse.urlsplit(self.http_base_url)
            self.host = parsed.hostname or host
            self.port = parsed.port or (443 if parsed.scheme == "https" else 80)
        # Explicit argument wins; otherwise fall back to the environment.
        # Never logged or included in repr.
        self._api_key: Optional[str] = api_key or os.getenv(API_KEY_ENV) or None
        if (
            self._api_key
            and self.http_base_url.startswith("http://")
            and self.host.lower() not in _LOOPBACK_HOSTS
            and not self.host.startswith("127.")
        ):
            logging.warning(_CLEARTEXT_KEY_WARNING)
        self._auth_warning_logged = False
        self.session_name = (
            session_name or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        self.session_metadata = session_metadata or {}
        self.batch_size = max(1, batch_size)
        self.flush_interval_seconds = max(0.01, flush_interval_seconds)
        self.session_id: Optional[str] = None
        self.pending_status: Optional[str] = None
        self.queue: queue.Queue = queue.Queue(maxsize=5000)
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.running = False
        self.ws_connected = False
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the background connection thread and event loop."""
        with self._lock:
            if self.running:
                return
            self.running = True
            self.thread = threading.Thread(
                target=self._run_loop, name="AgentScopeClientThread", daemon=True
            )
            self.thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the background client and close resources.

        Never blocks indefinitely, even with a full buffer and an unreachable
        server. It can take up to ``timeout + 0.5`` seconds: up to 0.5 s
        (capped at ``timeout``) waiting for buffer space for the shutdown
        sentinel, then up to ``timeout`` joining the background thread.
        """
        with self._lock:
            if not self.running:
                return
            self.running = False
            self._enqueue_shutdown_sentinel(timeout)
            # Let the async loop consume the sentinel and unwind the websocket
            # context manager. Calling loop.stop() here can leave the underlying
            # websockets keepalive task pending during shutdown.
            if self.thread and self.thread is not threading.current_thread():
                self.thread.join(timeout=timeout)

    def _auth_headers(self) -> Dict[str, str]:
        if not self._api_key:
            return {}
        return {"Authorization": f"Bearer {self._api_key}"}

    def _warn_unauthorized(self) -> None:
        # Log the actionable hint once instead of on every retry.
        if not self._auth_warning_logged:
            self._auth_warning_logged = True
            logging.warning(_UNAUTHORIZED_HINT)

    def _enqueue_shutdown_sentinel(self, timeout: float) -> None:
        """Queue the sentinel that tells the sender loop to exit, never blocking.

        A blocking put() deadlocks when the buffer is full and nothing drains it
        (server unreachable). If the server is reachable, the sender frees space
        within milliseconds, so wait briefly to avoid dropping events; otherwise
        evict the oldest buffered event so the sentinel always fits.
        """
        try:
            self.queue.put(None, timeout=min(0.5, max(0.0, timeout)))
            return
        except queue.Full:
            pass
        while True:
            try:
                self.queue.put_nowait(None)
                return
            except queue.Full:
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                except queue.Empty:
                    pass

    def emit(self, event: Dict[str, Any]) -> None:
        """Queue an event payload to be sent to the server.

        This call is non-blocking and returns in < 1ms.
        """
        if not self.running:
            self.start()
        # Non-blocking eviction loop: if queue is full, evict oldest element
        while True:
            try:
                self.queue.put_nowait(event)
                break
            except queue.Full:
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                except queue.Empty:
                    pass

    def patch_session_status(self, status: str) -> None:
        """Update the session status on the server.

        Args:
            status: "completed" or "failed"
        """
        with self._lock:
            if not self.session_id:
                self.pending_status = status
                return
            session_id = self.session_id

        self._send_status_patch(session_id, status)

    def _send_status_patch(self, session_id: str, status: str) -> None:
        url = f"{self.http_base_url}/api/sessions/{session_id}"
        data = json.dumps(
            {
                "status": status,
                "ended_at": datetime.now(timezone.utc).isoformat(),
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", **self._auth_headers()},
            method="PATCH",
        )

        def _do_patch() -> None:
            try:
                with urllib.request.urlopen(req, timeout=5):
                    logging.info(
                        f"AgentScope session {session_id} patched to status: {status}"
                    )
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    self._warn_unauthorized()
                else:
                    logging.warning(
                        f"AgentScope failed to patch session status to {status}: {e}"
                    )
            except Exception as e:
                logging.warning(
                    f"AgentScope failed to patch session status to {status}: {e}"
                )

        # Run REST calls in an independent thread to prevent blocking
        threading.Thread(
            target=_do_patch,
            name="AgentScopeSessionPatchThread",
            daemon=True,
        ).start()

    def _run_loop(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main_async_loop())
        except (RuntimeError, asyncio.CancelledError):
            pass
        finally:
            try:
                pending = [t for t in asyncio.all_tasks(self.loop) if not t.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    self.loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            finally:
                self.loop.close()

    async def _main_async_loop(self) -> None:
        backoff = 1.0
        max_backoff = MAX_BACKOFF_SECONDS
        failed_batch = []

        while self.running:
            try:
                # 1. Ensure the session is registered with the Server
                if not self.session_id:
                    await self.loop.run_in_executor(None, self._create_session_sync)
                    if not self.session_id:
                        # Server is down, wait and retry session creation
                        if not self.running:
                            break
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, max_backoff)
                        continue

                # 2. Connect to the WebSocket ingestion endpoint
                ws_uri = f"{self.ws_base_url}/ws?client_type=sdk"
                async with websockets.connect(
                    ws_uri, additional_headers=self._auth_headers() or None
                ) as websocket:
                    logging.info(f"Connected to AgentScope server at {ws_uri}")
                    self.ws_connected = True
                    backoff = 1.0  # Reset backoff on connection success

                    # 3. Read events from the queue in batches and send them
                    while self.running:
                        batch = []
                        if failed_batch:
                            batch = failed_batch
                            failed_batch = []
                        else:
                            event = await self.loop.run_in_executor(
                                None, self.queue.get
                            )
                            if event is None:
                                break
                            batch.append(event)
                            while len(batch) < self.batch_size:
                                try:
                                    nxt = self.queue.get_nowait()
                                    if nxt is None:
                                        self.queue.put(None)
                                        break
                                    batch.append(nxt)
                                except queue.Empty:
                                    break

                        if not batch:
                            continue

                        if len(batch) == 1:
                            message = {
                                "type": "event",
                                "session_id": self.session_id,
                                "event": batch[0],
                            }
                        else:
                            message = {
                                "type": "events_batch",
                                "session_id": self.session_id,
                                "events": batch,
                            }

                        try:
                            await websocket.send(json.dumps(message))
                            for _ in range(len(batch)):
                                self.queue.task_done()
                        except Exception as e:
                            if not _is_auth_close(e):
                                logging.warning(
                                    "Failed to send event batch to AgentScope "
                                    f"server: {e}. Re-queueing."
                                )
                            failed_batch = batch
                            raise e  # Trigger reconnection and retry

            except (
                websockets.exceptions.WebSocketException,
                OSError,
                ConnectionRefusedError,
            ) as e:
                self.ws_connected = False
                if not self.running:
                    break
                if _is_auth_close(e):
                    # The server completes the handshake and then closes with
                    # 4401, so the reset-on-connect above would otherwise
                    # retry every second. Retrying with the same key cannot
                    # succeed: wait the maximum and log the hint only once.
                    self._warn_unauthorized()
                    backoff = max_backoff
                    logging.debug(
                        "AgentScope server rejected the API key (4401). "
                        f"Retrying in {backoff}s..."
                    )
                else:
                    logging.warning(
                        "AgentScope server connection failed: "
                        f"{e}. Retrying in {backoff}s..."
                    )
                try:
                    await asyncio.sleep(backoff)
                except Exception:
                    break
                backoff = min(backoff * 2, max_backoff)
            except Exception as e:
                if not self.running:
                    break
                logging.error(f"Unexpected error in SDK client loop: {e}")
                try:
                    await asyncio.sleep(1.0)
                except Exception:
                    break

    def _create_session_sync(self) -> None:
        """Issue synchronous POST request to initialize a session on the server."""
        url = f"{self.http_base_url}/api/sessions"
        session_uuid = str(uuid.uuid4())
        data = json.dumps(
            {
                "session_id": session_uuid,
                "name": self.session_name,
                "metadata": self.session_metadata,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", **self._auth_headers()},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                new_session_id = res_data.get("session_id")

                status_to_patch = None
                with self._lock:
                    self.session_id = new_session_id
                    logging.info(
                        "AgentScope session successfully registered. "
                        f"ID: {self.session_id}"
                    )
                    if self.pending_status:
                        status_to_patch = self.pending_status
                        self.pending_status = None

                if status_to_patch:
                    self._send_status_patch(new_session_id, status_to_patch)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self._warn_unauthorized()
            else:
                logging.warning(
                    f"Failed to register session with AgentScope server: {e}"
                )
        except Exception as e:
            logging.warning(f"Failed to register session with AgentScope server: {e}")
