import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func

from database import engine, Base, async_session_maker
from models import SessionModel, EventModel
from ws_manager import manager
from routers import sessions, events

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

PRICING_TABLE = {
    "gpt-4o": {"input": 2.50 / 1_000_000, "output": 10.00 / 1_000_000},
    "gpt-4": {"input": 30.00 / 1_000_000, "output": 60.00 / 1_000_000},
    "gpt-3.5-turbo": {"input": 0.50 / 1_000_000, "output": 1.50 / 1_000_000},
    "claude-3-5-sonnet": {"input": 3.00 / 1_000_000, "output": 15.00 / 1_000_000},
    "gemini-1.5-pro": {"input": 1.25 / 1_000_000, "output": 5.00 / 1_000_000},
}


def _calculate_llm_cost(
    model_name: str, prompt_tokens: int | None, completion_tokens: int | None
) -> float:
    if not model_name or model_name not in PRICING_TABLE:
        return 0.0
    prices = PRICING_TABLE[model_name]
    in_tokens = prompt_tokens or 0
    out_tokens = completion_tokens or 0
    return (in_tokens * prices["input"]) + (out_tokens * prices["output"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB schema
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Teardown connection pool
    await engine.dispose()


app = FastAPI(
    title="AgentScope Observability Server",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration (allow all for local dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount REST routers
app.include_router(sessions.router, prefix="/api")
app.include_router(events.router, prefix="/api")


@app.get("/health")
def health_check():
    """Verify application status and version."""
    return {"status": "ok", "version": "1.0.0"}


async def handle_sdk_event(message: dict) -> None:
    sess_id = message.get("session_id")
    event_data = message.get("event")
    if not sess_id or not event_data:
        return

    async with async_session_maker() as db:
        # 1. Resolve Session
        stmt = select(SessionModel).where(SessionModel.session_id == sess_id)
        res = await db.execute(stmt)
        session = res.scalars().first()
        if not session:
            session = SessionModel(
                session_id=sess_id,
                name=f"session_{sess_id[:8]}",
                status="running",
                started_at=datetime.utcnow(),
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

        # 2. Parse Timestamp
        ts_str = event_data.get("timestamp")
        if ts_str:
            ts_str = ts_str.replace("Z", "+00:00")
            ts = datetime.fromisoformat(ts_str)
        else:
            ts = datetime.utcnow()

        payload = event_data.get("payload") or {}

        # 3. Create Telemetry Event
        db_event = EventModel(
            event_id=event_data["event_id"],
            session_id=sess_id,
            parent_event_id=event_data.get("parent_event_id"),
            event_type=event_data["event_type"],
            agent_name=event_data["agent_name"],
            agent_type=event_data["agent_type"],
            timestamp=ts,
            latency_ms=event_data.get("latency_ms"),
            status=event_data["status"],
            payload=payload,
        )
        db.add(db_event)

        # 4. Update session metrics dynamically
        if db_event.status == "error":
            session.error_count += 1

        agent_name = db_event.agent_name
        if agent_name:
            # Check if this is a new agent name in this session context
            agent_stmt = select(func.count(EventModel.event_id)).where(
                EventModel.session_id == sess_id,
                EventModel.agent_name == agent_name,
            )
            agent_res = await db.execute(agent_stmt)
            count = agent_res.scalar() or 0
            if count == 0:
                session.agent_count += 1

        if db_event.event_type == "llm_end":
            prompt_tokens = payload.get("prompt_tokens") or 0
            completion_tokens = payload.get("completion_tokens") or 0
            tokens = payload.get("total_tokens") or (prompt_tokens + completion_tokens)
            if tokens:
                session.total_tokens += tokens

            model = payload.get("model") or ""
            cost = _calculate_llm_cost(model, prompt_tokens, completion_tokens)
            session.total_cost_usd += cost

        await db.commit()
        await db.refresh(session)

        # 5. Broadcast new event to session UI subscribers
        ui_event = {
            "event_id": db_event.event_id,
            "session_id": db_event.session_id,
            "parent_event_id": db_event.parent_event_id,
            "event_type": db_event.event_type,
            "agent_name": db_event.agent_name,
            "agent_type": db_event.agent_type,
            "timestamp": db_event.timestamp.isoformat() + "Z",
            "latency_ms": db_event.latency_ms,
            "status": db_event.status,
            "payload": db_event.payload,
        }
        await manager.broadcast_to_session_ui(
            sess_id, {"type": "event", "session_id": sess_id, "event": ui_event}
        )

        # 6. Broadcast updated session aggregates to global UI subscribers
        session_data = {
            "status": session.status,
            "total_tokens": session.total_tokens,
            "total_cost_usd": float(session.total_cost_usd),
            "error_count": session.error_count,
            "agent_count": session.agent_count,
        }
        await manager.broadcast_session_update(sess_id, session_data)


@app.websocket("/ws")
async def websocket_route(
    websocket: WebSocket,
    client_type: str = Query(...),
    session_id: Optional[str] = Query(None),
):
    """WebSocket router distinguishing SDK telemetry feeds from browser views."""
    if client_type == "sdk":
        await manager.connect_sdk(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)
                if message.get("type") == "event":
                    await handle_sdk_event(message)
        except WebSocketDisconnect:
            manager.disconnect_sdk(websocket)
        except Exception as e:
            logging.error(f"WebSocket exception in SDK loop: {e}")
            manager.disconnect_sdk(websocket)

    elif client_type == "ui":
        await manager.connect_ui(websocket, session_id)
        try:
            while True:
                # Keep connection open, UI clients only listen to broadcasts
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect_ui(websocket, session_id)
        except Exception as e:
            logging.error(f"WebSocket exception in UI client loop: {e}")
            manager.disconnect_ui(websocket, session_id)
