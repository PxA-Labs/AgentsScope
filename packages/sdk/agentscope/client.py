import asyncio
import json
import logging
import queue
import threading
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import websockets
import websockets.exceptions


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
    ):
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
        """Stop the background client and close resources."""
        with self._lock:
            if not self.running:
                return
            self.running = False
            self.queue.put(None)  # Sentinel to exit queue readers
            # Let the async loop consume the sentinel and unwind the websocket
            # context manager. Calling loop.stop() here can leave the underlying
            # websockets keepalive task pending during shutdown.
            if self.thread and self.thread is not threading.current_thread():
                self.thread.join(timeout=timeout)

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
        max_backoff = 30.0
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
                ws_uri = f"ws://{self.host}:{self.port}/ws?client_type=sdk"
                async with websockets.connect(ws_uri) as websocket:
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
