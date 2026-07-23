import json
import logging
from typing import Dict, Set
from fastapi import WebSocket


class ConnectionManager:
    """Manages active WebSocket connections for both SDK publishers and UI subscribers."""

    def __init__(self):
        # Pool for SDK publishers
        self.sdk_connections: Set[WebSocket] = set()

        # Pool for UI subscribers: session_id -> Set[WebSocket]
        self.ui_connections: Dict[str, Set[WebSocket]] = {}

        # Pool for global UI subscribers (watching the session list sidebar, dashboard stats, etc.)
        self.global_ui_connections: Set[WebSocket] = set()

    async def connect_sdk(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.sdk_connections.add(websocket)
        logging.info(
            f"SDK client connected. Active SDK connections: {len(self.sdk_connections)}"
        )

    def disconnect_sdk(self, websocket: WebSocket) -> None:
        self.sdk_connections.discard(websocket)
        logging.info(
            f"SDK client disconnected. Active SDK connections: {len(self.sdk_connections)}"
        )

    async def connect_ui(
        self, websocket: WebSocket, session_id: str | None = None
    ) -> None:
        await websocket.accept()
        if session_id:
            if session_id not in self.ui_connections:
                self.ui_connections[session_id] = set()
            self.ui_connections[session_id].add(websocket)
            logging.info(
                f"UI client subscribed to session {session_id}. Active subscribers: {len(self.ui_connections[session_id])}"
            )
        else:
            self.global_ui_connections.add(websocket)
            logging.info(
                f"UI client subscribed globally. Active global subscribers: {len(self.global_ui_connections)}"
            )

    def disconnect_ui(
        self, websocket: WebSocket, session_id: str | None = None
    ) -> None:
        if session_id:
            if session_id in self.ui_connections:
                self.ui_connections[session_id].discard(websocket)
                if not self.ui_connections[session_id]:
                    del self.ui_connections[session_id]
            logging.info(f"UI client unsubscribed from session {session_id}")
        else:
            self.global_ui_connections.discard(websocket)
            logging.info("Global UI client disconnected")

    async def broadcast_to_session_ui(self, session_id: str, message: dict) -> None:
        """Send an event broadcast to UI clients listening to a specific session."""
        if session_id in self.ui_connections:
            message_str = json.dumps(message)
            disconnected = set()
            for connection in list(self.ui_connections[session_id]):
                try:
                    await connection.send_text(message_str)
                except Exception as e:
                    logging.warning(
                        f"Failed to send websocket message to UI client for session {session_id}: {e}"
                    )
                    disconnected.add(connection)

            for connection in disconnected:
                self.ui_connections[session_id].discard(connection)

    async def broadcast_session_update(
        self, session_id: str, session_data: dict
    ) -> None:
        """Broadcast a session status update (e.g., tokens, completed state) to all global UI dashboards

        and target session UIs.
        """
        payload = {
            "type": "session_update",
            "session_id": session_id,
            "session": session_data,
        }
        payload_str = json.dumps(payload)

        # 1. Broadcast to global UI subscribers
        disconnected_global = set()
        for connection in list(self.global_ui_connections):
            try:
                await connection.send_text(payload_str)
            except Exception as e:
                logging.warning(f"Failed to send global session update: {e}")
                disconnected_global.add(connection)

        for connection in disconnected_global:
            self.global_ui_connections.discard(connection)

        # 2. Also send directly to the specific session's UI view
        await self.broadcast_to_session_ui(session_id, payload)


# Global connection manager instance
manager = ConnectionManager()
