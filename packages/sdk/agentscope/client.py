import asyncio
import atexit
import json
import logging
import os
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import weakref
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


class _SenderEventLoop(asyncio.SelectorEventLoop):
    """Event loop that runs default-executor work on its own daemon threads.

    CPython shuts down concurrent.futures, including every loop's default
    executor, before it runs atexit hooks. The sender still has blocking work
    to do when it flushes at exit: the session POST and the name lookup that
    asyncio performs for ``create_connection``. Through the default executor
    both fail ("cannot schedule new futures after interpreter shutdown"), so
    each call gets a short-lived daemon thread instead. Such calls are rare
    (session registration and reconnects), so no pool is needed. Where even
    starting a thread is refused at exit (Python 3.12.0-3.12.2), the call
    runs inline on the sender thread.
    """

    def run_in_executor(self, executor, func, *args):  # type: ignore[override]
        if executor is not None:
            return super().run_in_executor(executor, func, *args)
        if self.is_closed():
            raise RuntimeError("Event loop is closed")
        future = self.create_future()

        def settle(result: Any, error: Optional[BaseException]) -> None:
            if future.done():
                return
            if error is None:
                future.set_result(result)
            else:
                future.set_exception(error)

        def work() -> None:
            try:
                outcome = (func(*args), None)
            except BaseException as e:
                outcome = (None, e)
            try:
                self.call_soon_threadsafe(settle, *outcome)
            except RuntimeError:
                pass  # the loop was closed while the call ran

        thread = threading.Thread(target=work, name="AgentScopeClientIO", daemon=True)
        try:
            thread.start()
        except RuntimeError:
            # Python 3.12.0-3.12.2 refuse new threads once atexit hooks run
            # ("can't create new thread at interpreter shutdown"). Run the
            # call on this (the sender) thread instead: blocking the loop is
            # acceptable while flushing at exit, losing the events is not.
            work()
        return future


class _Sender:
    """State owned by one background sender thread.

    Every start() creates a fresh instance, so a thread that outlives a
    timed-out stop() never shares its loop, wake-up events or deadline with a
    newer one. Methods not marked async are safe to call from any thread.
    """

    def __init__(self) -> None:
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.shutdown = threading.Event()
        self.deadline = float("inf")
        self.idle = False
        self._has_events: Optional[asyncio.Event] = None
        self._stop_requested: Optional[asyncio.Event] = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called on the sender thread once its loop is running."""
        self._has_events = asyncio.Event()
        self._stop_requested = asyncio.Event()
        self.loop = loop

    def expired(self) -> bool:
        return self.shutdown.is_set() and time.monotonic() >= self.deadline

    def request_stop(self, deadline: float) -> None:
        """Ask the sender to deliver what is buffered and exit by ``deadline``."""
        self.deadline = min(self.deadline, deadline)
        self.shutdown.set()
        self._call_soon(self._on_stop_requested)

    def notify_event(self) -> None:
        """Wake the sender if it is waiting for events. Cheap when it is busy."""
        if self.idle:
            self.idle = False
            self._call_soon(self._on_event)

    def _call_soon(self, callback: Any) -> None:
        loop = self.loop
        if loop is None:
            # Not bound yet: the sender checks the buffer and `shutdown`
            # before it waits, so nothing is missed.
            return
        try:
            loop.call_soon_threadsafe(callback)
        except RuntimeError:
            pass  # the loop has already closed

    def _on_event(self) -> None:
        if self._has_events is not None:
            self._has_events.set()

    def _on_stop_requested(self) -> None:
        if self._stop_requested is not None:
            self._stop_requested.set()
        self._on_event()

    async def wait_for_events(self, buffer: queue.Queue, timeout: float) -> None:
        """Wait until emit() or stop() wakes us, or ``timeout`` elapses."""
        assert self._has_events is not None
        self._has_events.clear()
        # Publish `idle` before the final check: an emit() that lands after
        # the check sees idle=True and wakes us, so no event waits for the
        # timeout.
        self.idle = True
        try:
            if buffer.empty() and not self.shutdown.is_set():
                await asyncio.wait_for(self._has_events.wait(), timeout)
        except asyncio.TimeoutError:
            pass
        finally:
            self.idle = False

    async def backoff(self, seconds: float) -> None:
        """Sleep before a retry. stop() cuts the sleep short; once stopping,
        retries continue until the deadline but never sleep past it."""
        if self.shutdown.is_set():
            await asyncio.sleep(
                max(0.0, min(seconds, self.deadline - time.monotonic()))
            )
            return
        assert self._stop_requested is not None
        try:
            await asyncio.wait_for(self._stop_requested.wait(), seconds)
        except asyncio.TimeoutError:
            pass


# Clients whose buffered events should be delivered when the interpreter
# exits. Weak references, so stopped clients can be garbage collected; a
# running sender thread keeps its own client alive.
_live_clients: "weakref.WeakSet[AgentScopeClient]" = weakref.WeakSet()
_exit_hook_lock = threading.Lock()
_exit_hook_registered = False


def _track_for_exit(client: "AgentScopeClient") -> None:
    global _exit_hook_registered
    with _exit_hook_lock:
        _live_clients.add(client)
        if not _exit_hook_registered:
            # Registered on first use rather than at import, so it runs
            # before atexit hooks the program registered earlier (LIFO).
            atexit.register(_stop_clients_at_exit)
            _exit_hook_registered = True


def _stop_clients_at_exit() -> None:
    """Deliver buffered events of every running client, in parallel.

    All clients are asked to stop first, each with its own shutdown_timeout
    measured from the same moment, and only then joined. Exit therefore
    takes as long as the slowest client, not the sum of all of them.
    """
    now = time.monotonic()
    with _exit_hook_lock:
        clients = list(_live_clients)
    stopping = []
    for client in clients:
        try:
            sender = client._request_stop(client.shutdown_timeout, now=now)
        except Exception:
            continue
        if sender is not None:
            stopping.append((client, sender))
    for client, sender in stopping:
        try:
            client._join_sender(sender)
        except Exception:
            pass


class AgentScopeClient:
    """Thread-safe WebSocket and REST client for the AgentScope observability server.

    Employs a background daemon thread with its own asyncio event loop to handle
    all networking out-of-band. Ensures zero latency impact on the agent pipeline.
    """

    # Reconnect backoff bounds, in seconds.
    _initial_backoff = 1.0
    _max_backoff = MAX_BACKOFF_SECONDS

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
        shutdown_timeout: float = 5.0,
    ):
        """Create a client.

        Args:
            host: Server host name (ignored when ``base_url`` is given).
            port: Server port (ignored when ``base_url`` is given).
            batch_size: Maximum events per WebSocket message.
            flush_interval_seconds: Safety-net period at which an idle sender
                re-checks the buffer. New events wake the sender immediately,
                so this adds no latency.
            api_key: API key for servers with authentication enabled. Defaults
                to the AGENTSCOPE_API_KEY environment variable.
            secure: Use TLS (``https``/``wss``) for ``host:port``.
            base_url: Full server URL such as ``https://agentscope.example.com``
                (``http``/``https``/``ws``/``wss``); its scheme decides between
                plain and TLS connections.
            shutdown_timeout: Upper bound for delivering buffered events when
                the interpreter exits (see :meth:`stop`).
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
        self.shutdown_timeout = max(0.0, shutdown_timeout)
        self._lock = threading.Lock()
        self._sender: Optional[_Sender] = None
        # A batch taken from the buffer whose send failed. It outlives the
        # sender, so the next one (after a reconnect or a restart following
        # a timed-out stop) delivers it first, in order.
        self._unsent: list = []

    def start(self) -> None:
        """Start the background connection thread and event loop."""
        with self._lock:
            if self.running:
                return
            self.running = True
            sender = _Sender()
            sender.thread = threading.Thread(
                target=self._run_loop,
                args=(sender,),
                name="AgentScopeClientThread",
                daemon=True,
            )
            self._sender = sender
            self.thread = sender.thread
            sender.thread.start()
        # Deliver buffered events when the program ends, so scripts do not
        # need to call stop() explicitly.
        _track_for_exit(self)

    def stop(self, timeout: float = 2.0) -> None:
        """Deliver buffered events, then stop the background client.

        Returns within ``timeout + 0.5`` seconds whatever the server state:
        the sender gets ``timeout`` to deliver, plus 0.5 s to close the
        connection. Never blocks on a full buffer.

        Events that cannot be delivered in time (server unreachable, key
        rejected) are not discarded: they stay buffered, in order, and are
        sent when a later emit() restarts the sender. The exit hook flushes
        only running clients, so events still buffered in a stopped client
        are lost when the process exits.

        ``running`` becomes False once the background thread has exited. If
        the thread is still busy when stop() returns (for example stuck in a
        slow session request), ``running`` stays True until it finishes, and
        no second sender thread is started in the meantime.
        """
        sender = self._request_stop(timeout)
        if sender is not None:
            self._join_sender(sender)
        # The thread clears `running` itself when it exits (see _run_loop).

    def _request_stop(
        self, timeout: float, now: Optional[float] = None
    ) -> Optional[_Sender]:
        """Ask the running sender to flush and exit; return it, don't wait."""
        with self._lock:
            if not self.running or self._sender is None:
                return None
            sender = self._sender
            start = time.monotonic() if now is None else now
            sender.request_stop(start + max(0.0, timeout))
            return sender

    @staticmethod
    def _join_sender(sender: _Sender) -> None:
        """Wait for the sender until its deadline plus 0.5 s to close up."""
        thread = sender.thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, sender.deadline - time.monotonic()) + 0.5)

    def _auth_headers(self) -> Dict[str, str]:
        if not self._api_key:
            return {}
        return {"Authorization": f"Bearer {self._api_key}"}

    def _json_request(
        self, url: str, data: bytes, method: str
    ) -> urllib.request.Request:
        """Build a JSON REST request carrying the API key, if one is set.

        The key is attached as an *unredirected* header: urllib copies ordinary
        headers onto the new request when it follows a 301/302/303, so a proxy
        redirecting an https call to plain http (or to another host) would
        otherwise receive the key in cleartext.
        """
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        for name, value in self._auth_headers().items():
            req.add_unredirected_header(name, value)
        return req

    def _warn_unauthorized(self) -> None:
        # Log the actionable hint once instead of on every retry.
        if not self._auth_warning_logged:
            self._auth_warning_logged = True
            logging.warning(_UNAUTHORIZED_HINT)

    def _next_batch(self) -> list:
        """Take up to batch_size buffered events without blocking."""
        batch = []
        while len(batch) < self.batch_size:
            try:
                batch.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return batch

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
        sender = self._sender
        if sender is not None:
            sender.notify_event()

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

        req = self._json_request(url, data, "PATCH")

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

    def _run_loop(self, sender: _Sender) -> None:
        try:
            self._run_sender(sender)
        finally:
            # Only now is the client really stopped (see stop()).
            with self._lock:
                if self._sender is sender:
                    self.running = False
                    self.ws_connected = False

    def _run_sender(self, sender: _Sender) -> None:
        # The loop stays local to this thread (and its _Sender); self.loop is
        # only kept up to date for callers that inspect it.
        loop = _SenderEventLoop()
        self.loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._main_async_loop(sender))
        except (RuntimeError, asyncio.CancelledError):
            pass
        finally:
            sender.loop = None
            try:
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            finally:
                loop.close()

    async def _main_async_loop(self, sender: _Sender) -> None:
        """Deliver buffered events until stop() asks to finish.

        The buffer is drained with non-blocking reads on this loop. Blocking
        queue.get() calls in an executor thread would keep the interpreter
        from exiting (it joins executor threads at shutdown). When the buffer
        is empty the loop waits until emit() or stop() wakes it.
        """
        loop = asyncio.get_running_loop()
        sender.bind(loop)
        backoff = self._initial_backoff

        while not sender.expired():
            try:
                # 1. Ensure the session is registered with the server.
                if not self.session_id:
                    await loop.run_in_executor(None, self._create_session_sync)
                    if not self.session_id:
                        if sender.shutdown.is_set() and self.queue.empty():
                            return
                        await sender.backoff(backoff)
                        backoff = min(backoff * 2, self._max_backoff)
                        continue

                # 2. Connect to the WebSocket ingestion endpoint.
                ws_uri = f"{self.ws_base_url}/ws?client_type=sdk"
                async with websockets.connect(
                    ws_uri, additional_headers=self._auth_headers() or None
                ) as websocket:
                    logging.info(f"Connected to AgentScope server at {ws_uri}")
                    self.ws_connected = True
                    backoff = self._initial_backoff

                    # 3. Send buffered events in batches.
                    while not sender.expired():
                        batch = self._unsent or self._next_batch()
                        self._unsent = []
                        if not batch:
                            if sender.shutdown.is_set():
                                return  # everything delivered
                            await sender.wait_for_events(
                                self.queue, self.flush_interval_seconds
                            )
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
                            self._unsent = batch
                            raise e  # Trigger reconnection and retry
                    return

            except (
                websockets.exceptions.WebSocketException,
                OSError,
                ConnectionRefusedError,
            ) as e:
                self.ws_connected = False
                if sender.expired():
                    break
                if _is_auth_close(e):
                    # The server completes the handshake and then closes with
                    # 4401, so the reset-on-connect above would otherwise
                    # retry every second. Retrying with the same key cannot
                    # succeed: wait the maximum and log the hint only once.
                    self._warn_unauthorized()
                    backoff = self._max_backoff
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
                    await sender.backoff(backoff)
                except Exception:
                    break
                backoff = min(backoff * 2, self._max_backoff)
            except Exception as e:
                if sender.expired():
                    break
                logging.error(f"Unexpected error in SDK client loop: {e}")
                try:
                    await sender.backoff(1.0)
                except Exception:
                    break
        self.ws_connected = False

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

        req = self._json_request(url, data, "POST")

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
