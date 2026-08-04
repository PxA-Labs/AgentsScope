import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from database import engine, Base, async_session_maker
from models import SessionModel, EventModel
from ws_manager import manager
from routers import sessions, events
from pricing import calculate_cost as _calculate_llm_cost

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


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

# CORS configuration (allow environment-driven explicit origin allowlist)
cors_origins_raw = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
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


def merge_payloads(existing: dict, incoming: dict) -> dict:
    """Merge incoming event payload with existing, avoiding overwrites with empty values."""
    merged = dict(existing)
    for k, v in incoming.items():
        if v is not None and v != "" and v != []:
            merged[k] = v
        elif k not in merged:
            merged[k] = v
    return merged


async def handle_sdk_event(message: dict) -> None:
    sess_id = message.get("session_id")
    event_data = message.get("event")
    if not sess_id or not event_data:
        return

    required_fields = ["event_id", "event_type", "agent_name", "agent_type", "status"]
    if not all(field in event_data for field in required_fields):
        logging.warning("Skipping malformed event due to missing required fields")
        return

    async with async_session_maker() as db:
        try:
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

            # Variables to track prior state for idempotent updates
            is_new_event = False
            prev_status = None
            prev_tokens = 0
            prev_cost = 0.0

            # 3. Create or Update Telemetry Event atomically
            try:
                async with db.begin_nested():
                    event_stmt = select(EventModel).where(
                        EventModel.session_id == sess_id,
                        EventModel.event_id == event_data["event_id"]
                    )
                    event_res = await db.execute(event_stmt)
                    db_event = event_res.scalars().first()

                    if db_event:
                        prev_status = db_event.status
                        if db_event.event_type == "llm_end":
                            merged_payload = db_event.payload or {}
                            prompt_tokens = merged_payload.get("prompt_tokens") or 0
                            completion_tokens = merged_payload.get("completion_tokens") or 0
                            prev_tokens = merged_payload.get("total_tokens") or (
                                prompt_tokens + completion_tokens
                            )
                            model = merged_payload.get("model") or ""
                            prev_cost = _calculate_llm_cost(model, prompt_tokens, completion_tokens)

                        # Update existing event properties
                        db_event.event_type = event_data["event_type"]
                        db_event.status = event_data["status"]
                        if event_data.get("latency_ms") is not None:
                            db_event.latency_ms = event_data["latency_ms"]
                        db_event.payload = merge_payloads(db_event.payload or {}, payload)
                    else:
                        is_new_event = True
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
                    await db.flush()
            except IntegrityError:
                # Concurrent insert collision; retry the lookup-and-merge
                event_stmt = select(EventModel).where(
                    EventModel.session_id == sess_id,
                    EventModel.event_id == event_data["event_id"]
                )
                event_res = await db.execute(event_stmt)
                db_event = event_res.scalars().first()
                if db_event:
                    prev_status = db_event.status
                    if db_event.event_type == "llm_end":
                        merged_payload = db_event.payload or {}
                        prompt_tokens = merged_payload.get("prompt_tokens") or 0
                        completion_tokens = merged_payload.get("completion_tokens") or 0
                        prev_tokens = merged_payload.get("total_tokens") or (
                            prompt_tokens + completion_tokens
                        )
                        model = merged_payload.get("model") or ""
                        prev_cost = _calculate_llm_cost(model, prompt_tokens, completion_tokens)

                    is_new_event = False
                    db_event.event_type = event_data["event_type"]
                    db_event.status = event_data["status"]
                    if event_data.get("latency_ms") is not None:
                        db_event.latency_ms = event_data["latency_ms"]
                    db_event.payload = merge_payloads(db_event.payload or {}, payload)

            # 4. Update session metrics dynamically and idempotently
            if is_new_event:
                if event_data["status"] == "error":
                    session.error_count += 1

                agent_name = db_event.agent_name
                if agent_name:
                    with db.no_autoflush:
                        agent_stmt = select(func.count(EventModel.event_id)).where(
                            EventModel.session_id == sess_id,
                            EventModel.agent_name == agent_name,
                        )
                        agent_res = await db.execute(agent_stmt)
                        count = agent_res.scalar() or 0
                    if count <= 1:
                        session.agent_count += 1
                if db_event.event_type == "llm_end":
                    merged_payload = db_event.payload or {}
                    prompt_tokens = merged_payload.get("prompt_tokens") or 0
                    completion_tokens = merged_payload.get("completion_tokens") or 0
                    tokens = merged_payload.get("total_tokens") or (
                        prompt_tokens + completion_tokens
                    )
                    if tokens:
                        session.total_tokens += tokens

                    model = merged_payload.get("model") or ""
                    cost = _calculate_llm_cost(model, prompt_tokens, completion_tokens)
                    session.total_cost_usd += cost
            else:
                # Event already existed: handle status transition deltas
                if prev_status != "error" and event_data["status"] == "error":
                    session.error_count += 1
                elif prev_status == "error" and event_data["status"] != "error":
                    session.error_count = max(0, session.error_count - 1)

                # Handle token/cost deltas if we are currently at llm_end
                if db_event.event_type == "llm_end":
                    merged_payload = db_event.payload or {}
                    prompt_tokens = merged_payload.get("prompt_tokens") or 0
                    completion_tokens = merged_payload.get("completion_tokens") or 0
                    new_tokens = merged_payload.get("total_tokens") or (
                        prompt_tokens + completion_tokens
                    )
                    model = merged_payload.get("model") or ""
                    new_cost = _calculate_llm_cost(model, prompt_tokens, completion_tokens)

                    token_delta = new_tokens - prev_tokens
                    cost_delta = new_cost - prev_cost

                    session.total_tokens += token_delta
                    session.total_cost_usd += cost_delta

            # Implicit session status synchronization from root terminal events (Sub-Issue 5.2)
            if db_event.event_type == "chain_end" and not db_event.parent_event_id:
                session.status = "completed"
                session.ended_at = ts
            elif db_event.event_type == "chain_error" and not db_event.parent_event_id:
                session.status = "failed"
                session.ended_at = ts

            await db.commit()
            await db.refresh(session)
            await db.refresh(db_event)
            # 5. Broadcast updated event to session UI subscribers
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

        except IntegrityError as ie:
            await db.rollback()
            logging.info(
                f"Skipping event_id {event_data.get('event_id')} as it is an idempotent duplicate or constraint failure: {ie}."
            )
        except Exception as e:
            await db.rollback()
            logging.error(f"Error handling SDK event in database: {e}")


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
            try:
                await websocket.close()
            except Exception:
                pass
        except Exception as e:
            logging.error(f"WebSocket exception in SDK loop: {e}")
            manager.disconnect_sdk(websocket)
            try:
                await websocket.close()
            except Exception:
                pass

    elif client_type == "ui":
        await manager.connect_ui(websocket, session_id)
        try:
            while True:
                # Keep connection open, UI clients only listen to broadcasts
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect_ui(websocket, session_id)
            try:
                await websocket.close()
            except Exception:
                pass
        except Exception as e:
            logging.error(f"WebSocket exception in UI client loop: {e}")
            manager.disconnect_ui(websocket, session_id)
            try:
                await websocket.close()
            except Exception:
                pass
