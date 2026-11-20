import asyncio
import atexit
import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import websockets
import websockets.exceptions


class _SenderEventLoop(asyncio.SelectorEventLoop):
    """Event loop that runs default-executor work on its own daemon threads.

    CPython shuts down concurrent.futures, including every loop's default
    executor, before it runs atexit hooks. The sender still has blocking work
    to do when it flushes at exit: the session POST and the name lookup that
    asyncio performs for ``create_connection``. Through the default executor
    both fail ("cannot schedule new futures after interpreter shutdown"), so
    each call gets a short-lived daemon thread instead. Such calls are rare
    (session registration and reconnects), so no pool is needed.
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

        threading.Thread(target=work, name="AgentScopeClientIO", daemon=True).start()
        return future


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
        shutdown_timeout: float = 5.0,
    ):
        """
        Args:
            batch_size: Maximum events per WebSocket message.
            flush_interval_seconds: How long the sender idles when the buffer
                is empty before checking again.
            shutdown_timeout: Upper bound for delivering buffered events when
                the interpreter exits (see :meth:`stop`).
        """
        self.host = host
        self.port = port
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
        # Set by stop(): the sender delivers what is buffered, then exits.
        self._shutdown = threading.Event()
        self._shutdown_deadline = float("inf")
        self._atexit_registered = False

    def start(self) -> None:
        """Start the background connection thread and event loop."""
        with self._lock:
            if self.running:
                return
            self.running = True
            self._shutdown.clear()
            self._shutdown_deadline = float("inf")
            self.thread = threading.Thread(
                target=self._run_loop, name="AgentScopeClientThread", daemon=True
            )
            self.thread.start()
            if not self._atexit_registered:
                # Deliver buffered events when the program ends, so scripts do
                # not need to call stop() explicitly.
                atexit.register(self._stop_at_exit)
                self._atexit_registered = True

    def stop(self, timeout: float = 2.0) -> None:
        """Deliver buffered events, then stop the background client.

        Returns within roughly ``timeout`` seconds whatever the server state:
        events that cannot be delivered in time (server unreachable) are
        dropped. Never blocks on a full buffer.
        """
        with self._lock:
            if not self.running:
                return
            self._shutdown_deadline = time.monotonic() + max(0.0, timeout)
            self._shutdown.set()
            thread = self.thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout) + 0.5)
        with self._lock:
            self.running = False

    def _stop_at_exit(self) -> None:
        try:
            self.stop(timeout=self.shutdown_timeout)
        except Exception:
            pass

    def _shutdown_expired(self) -> bool:
        return self._shutdown.is_set() and time.monotonic() >= self._shutdown_deadline

    def _sleep_or_shutdown(self, seconds: float):
        """Sleep, but never past the shutdown deadline."""
        if self._shutdown.is_set():
            seconds = min(seconds, max(0.0, self._shutdown_deadline - time.monotonic()))
        return asyncio.sleep(seconds)

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
        url = f"http://{self.host}:{self.port}/api/sessions/{session_id}"
        data = json.dumps(
            {
                "status": status,
                "ended_at": datetime.now(timezone.utc).isoformat(),
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="PATCH",
        )

        def _do_patch() -> None:
            try:
                with urllib.request.urlopen(req, timeout=5):
                    logging.info(
                        f"AgentScope session {session_id} patched to status: {status}"
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
        self.loop = _SenderEventLoop()
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
        """Deliver buffered events until stop() asks to finish.

        The buffer is drained with non-blocking reads on this loop. Blocking
        queue.get() calls in an executor thread would keep the interpreter
        from exiting (it joins executor threads at shutdown).
        """
        backoff = 1.0
        max_backoff = 30.0
        failed_batch: list = []

        while not self._shutdown_expired():
            try:
                # 1. Ensure the session is registered with the server.
                if not self.session_id:
                    await self.loop.run_in_executor(None, self._create_session_sync)
                    if not self.session_id:
                        if self._shutdown.is_set() and self.queue.empty():
                            return
                        await self._sleep_or_shutdown(backoff)
                        backoff = min(backoff * 2, max_backoff)
                        continue

                # 2. Connect to the WebSocket ingestion endpoint.
                ws_uri = f"ws://{self.host}:{self.port}/ws?client_type=sdk"
                async with websockets.connect(ws_uri) as websocket:
                    logging.info(f"Connected to AgentScope server at {ws_uri}")
                    self.ws_connected = True
                    backoff = 1.0

                    # 3. Send buffered events in batches.
                    while not self._shutdown_expired():
                        batch = failed_batch or self._next_batch()
                        failed_batch = []
                        if not batch:
                            if self._shutdown.is_set():
                                return  # everything delivered
                            await asyncio.sleep(self.flush_interval_seconds)
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
                            logging.warning(
                                "Failed to send event batch to AgentScope "
                                f"server: {e}. Re-queueing."
                            )
                            failed_batch = batch
                            raise e  # Trigger reconnection and retry
                    return

            except (
                websockets.exceptions.WebSocketException,
                OSError,
                ConnectionRefusedError,
            ) as e:
                self.ws_connected = False
                if self._shutdown_expired():
                    break
                logging.warning(
                    "AgentScope server connection failed: "
                    f"{e}. Retrying in {backoff}s..."
                )
                try:
                    await self._sleep_or_shutdown(backoff)
                except Exception:
                    break
                backoff = min(backoff * 2, max_backoff)
            except Exception as e:
                if self._shutdown_expired():
                    break
                logging.error(f"Unexpected error in SDK client loop: {e}")
                try:
                    await self._sleep_or_shutdown(1.0)
                except Exception:
                    break
        self.ws_connected = False

    def _create_session_sync(self) -> None:
        """Issue synchronous POST request to initialize a session on the server."""
        url = f"http://{self.host}:{self.port}/api/sessions"
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
            headers={"Content-Type": "application/json"},
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
        except Exception as e:
            logging.warning(f"Failed to register session with AgentScope server: {e}")
