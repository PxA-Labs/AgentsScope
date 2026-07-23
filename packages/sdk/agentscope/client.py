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
    ):
        self.host = host
        self.port = port
        self.session_name = (
            session_name or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        self.session_metadata = session_metadata or {}
        self.session_id: Optional[str] = None
        self.queue: queue.Queue = queue.Queue()
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

    def stop(self) -> None:
        """Stop the background client and close resources."""
        with self._lock:
            if not self.running:
                return
            self.running = False
            self.queue.put(None)  # Sentinel to exit queue readers
            if self.loop and self.loop.is_running():
                self.loop.call_soon_threadsafe(self.loop.stop)
            if self.thread:
                self.thread.join(timeout=2.0)

    def emit(self, event: Dict[str, Any]) -> None:
        """Queue an event payload to be sent to the server.

        This call is non-blocking and returns in < 1ms.
        """
        if not self.running:
            self.start()
        self.queue.put(event)

    def patch_session_status(self, status: str) -> None:
        """Update the session status on the server.

        Args:
            status: "completed" or "failed"
        """
        if not self.session_id:
            return

        url = f"http://{self.host}:{self.port}/sessions/{self.session_id}"
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
                        f"AgentScope session {self.session_id} "
                        f"patched to status: {status}"
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
        finally:
            self.loop.close()

    async def _main_async_loop(self) -> None:
        import websockets

        backoff = 1.0
        max_backoff = 30.0

        while self.running:
            try:
                # 1. Ensure the session is registered with the Server
                if not self.session_id:
                    self._create_session_sync()
                    if not self.session_id:
                        # Server is down, wait and retry session creation
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, max_backoff)
                        continue

                # 2. Connect to the WebSocket ingestion endpoint
                ws_uri = f"ws://{self.host}:{self.port}/ws?client_type=sdk"
                async with websockets.connect(ws_uri) as websocket:
                    logging.info(f"Connected to AgentScope server at {ws_uri}")
                    self.ws_connected = True
                    backoff = 1.0  # Reset backoff on connection success

                    # 3. Read events from the queue and send them
                    while self.running:
                        # Fetch event from the blocking queue using loop executor
                        event = await self.loop.run_in_executor(None, self.queue.get)
                        if event is None:
                            break

                        # Encapsulate event into ingestion schema
                        message = {
                            "type": "event",
                            "session_id": self.session_id,
                            "event": event,
                        }

                        try:
                            await websocket.send(json.dumps(message))
                            self.queue.task_done()
                        except Exception as e:
                            logging.warning(
                                "Failed to send event to AgentScope "
                                f"server: {e}. Re-queueing."
                            )
                            self.queue.put(event)
                            raise e  # Trigger reconnection and retry

            except (
                websockets.exceptions.WebSocketException,
                OSError,
                ConnectionRefusedError,
            ) as e:
                self.ws_connected = False
                logging.warning(
                    "AgentScope server connection failed: "
                    f"{e}. Retrying in {backoff}s..."
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
            except Exception as e:
                logging.error(f"Unexpected error in SDK client loop: {e}")
                await asyncio.sleep(1.0)

    def _create_session_sync(self) -> None:
        """Issue synchronous POST request to initialize a session on the server."""
        url = f"http://{self.host}:{self.port}/sessions"
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
                self.session_id = res_data.get("session_id")
                logging.info(
                    f"AgentScope session successfully registered. ID: {self.session_id}"
                )
        except Exception as e:
            logging.warning(f"Failed to register session with AgentScope server: {e}")
