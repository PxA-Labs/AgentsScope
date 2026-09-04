import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Query, status
from graph_layout import compute_graph_layout
from models import EventModel, SessionModel
from pricing import calculate_cost as _calculate_llm_cost
from retention import prune_old_sessions
from schemas import (
    AgentStats,
    EventResponse,
    GraphResponse,
    SessionCreate,
    SessionExport,
    SessionImportPayload,
    SessionResponse,
    SessionUpdate,
    StatsResponse,
    TokenTimelinePoint,
)
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ws_manager import manager

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _compute_session_aggregates(events: List[EventModel]) -> Dict[str, Any]:
    """Compute aggregate token counts, costs, errors, and agent counts from events."""
    total_tokens = 0
    total_cost = 0.0
    error_count = 0
    agents = set()

    for ev in events:
        if ev.status == "error":
            error_count += 1
        if ev.agent_name:
            agents.add(ev.agent_name)
        if ev.event_type == "llm_end" and ev.payload:
            tokens = ev.payload.get("total_tokens") or 0
            total_tokens += tokens

            model = ev.payload.get("model") or ""
            prompt_tokens = ev.payload.get("prompt_tokens") or 0
            completion_tokens = ev.payload.get("completion_tokens") or 0
            total_cost += _calculate_llm_cost(model, prompt_tokens, completion_tokens)

    return {
        "total_tokens": total_tokens,
        "total_cost": total_cost,
        "error_count": error_count,
        "agent_count": len(agents),
    }


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(session_in: SessionCreate, db: AsyncSession = Depends(get_db)):
    """Initialize a new observability session."""
    session_id = session_in.session_id or str(uuid.uuid4())

    # Check if session already exists
    existing = await db.execute(
        select(SessionModel).where(SessionModel.session_id == session_id)
    )
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Session ID already exists"
        )

    db_session = SessionModel(
        session_id=session_id,
        name=session_in.name,
        status="running",
        started_at=datetime.now(timezone.utc),
        metadata_=session_in.metadata or {},
    )
    db.add(db_session)
    await db.commit()
    await db.refresh(db_session)

    # Broadcast session creation to global UI connections
    session_data = {
        "session_id": db_session.session_id,
        "name": db_session.name,
        "status": db_session.status,
        "started_at": db_session.started_at.isoformat(),
        "total_tokens": db_session.total_tokens,
        "total_cost_usd": db_session.total_cost_usd,
        "error_count": db_session.error_count,
        "agent_count": db_session.agent_count,
        "metadata": db_session.metadata_,
    }
    await manager.broadcast_session_update(db_session.session_id, session_data)

    return db_session


@router.get("", response_model=Dict[str, Any])
async def list_sessions(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a paginated list of all sessions, ordered chronologically descending."""
    offset = (page - 1) * limit

    # Fetch count
    count_stmt = select(func.count()).select_from(SessionModel)
    count_res = await db.execute(count_stmt)
    total = count_res.scalar() or 0

    # Fetch sessions
    stmt = (
        select(SessionModel)
        .order_by(SessionModel.started_at.desc())
        .offset(offset)
        .limit(limit)
    )
    res = await db.execute(stmt)
    sessions = res.scalars().all()

    return {
        "sessions": [SessionResponse.model_validate(s) for s in sessions],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve detailed state of a single session."""
    stmt = select(SessionModel).where(SessionModel.session_id == session_id)
    res = await db.execute(stmt)
    db_session = res.scalars().first()
    if not db_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return db_session


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str,
    session_update: SessionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Modify details or state of a session (e.g. mark as completed or failed)."""
    stmt = select(SessionModel).where(SessionModel.session_id == session_id)
    res = await db.execute(stmt)
    db_session = res.scalars().first()
    if not db_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    db_session.status = session_update.status.value
    if session_update.ended_at is not None:
        db_session.ended_at = session_update.ended_at
    elif session_update.status.value in ["completed", "failed"]:
        db_session.ended_at = datetime.now(timezone.utc)

    # Recalculate session aggregates from events before finishing
    event_stmt = select(EventModel).where(EventModel.session_id == session_id)
    event_res = await db.execute(event_stmt)
    events = event_res.scalars().all()

    aggregates = _compute_session_aggregates(events)
    db_session.total_tokens = aggregates["total_tokens"]
    db_session.total_cost_usd = aggregates["total_cost"]
    db_session.error_count = aggregates["error_count"]
    db_session.agent_count = aggregates["agent_count"]

    await db.commit()
    await db.refresh(db_session)

    # Broadcast status change to connected UIs
    session_data = {
        "status": db_session.status,
        "ended_at": db_session.ended_at.isoformat() if db_session.ended_at else None,
        "total_tokens": db_session.total_tokens,
        "total_cost_usd": db_session.total_cost_usd,
        "error_count": db_session.error_count,
        "agent_count": db_session.agent_count,
    }
    await manager.broadcast_session_update(db_session.session_id, session_data)

    return db_session


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a session and all its associated events."""
    stmt = select(SessionModel).where(SessionModel.session_id == session_id)
    res = await db.execute(stmt)
    db_session = res.scalars().first()
    if not db_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    await db.execute(delete(SessionModel).where(SessionModel.session_id == session_id))
    await db.commit()
    return


@router.get("/{session_id}/graph", response_model=GraphResponse)
async def get_session_graph(session_id: str, db: AsyncSession = Depends(get_db)):
    """Generate layout nodes and edges representing the execution DAG."""
    # Ensure session exists
    sess_stmt = select(SessionModel).where(SessionModel.session_id == session_id)
    sess_res = await db.execute(sess_stmt)
    if not sess_res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    # Query all events for the session
    stmt = select(EventModel).where(EventModel.session_id == session_id)
    res = await db.execute(stmt)
    events = res.scalars().all()

    return compute_graph_layout(events)


@router.get("/{session_id}/stats", response_model=StatsResponse)
async def get_session_stats(session_id: str, db: AsyncSession = Depends(get_db)):
    """Compute aggregate execution stats, costs, and token timelines."""
    sess_stmt = select(SessionModel).where(SessionModel.session_id == session_id)
    sess_res = await db.execute(sess_stmt)
    db_session = sess_res.scalars().first()
    if not db_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    stmt = (
        select(EventModel)
        .where(EventModel.session_id == session_id)
        .order_by(EventModel.timestamp.asc())
    )
    res = await db.execute(stmt)
    events = res.scalars().all()

    aggregates = _compute_session_aggregates(events)
    event_count = len(events)

    # Group stats by agent
    agent_info: Dict[str, Dict[str, Any]] = {}

    # Timeline
    timeline: List[TokenTimelinePoint] = []
    current_cumulative_tokens = 0

    for ev in events:
        name = ev.agent_name or ev.agent_type or "Unknown"
        if name not in agent_info:
            agent_info[name] = {
                "name": name,
                "type": ev.agent_type,
                "call_count": 0,
                "total_tokens": 0,
                "latencies": [],
                "errors": 0,
            }

        agent_info[name]["call_count"] += 1
        if ev.status == "error":
            agent_info[name]["errors"] += 1
        if ev.latency_ms is not None:
            agent_info[name]["latencies"].append(ev.latency_ms)

        if ev.event_type == "llm_end" and ev.payload:
            tokens = ev.payload.get("total_tokens") or 0
            current_cumulative_tokens += tokens
            agent_info[name]["total_tokens"] += tokens

            # Append timeline point
            timeline.append(
                TokenTimelinePoint(
                    timestamp=ev.timestamp.replace(tzinfo=timezone.utc).isoformat(),
                    cumulative_tokens=current_cumulative_tokens,
                )
            )

    # Format agent stats list
    agents_list = []
    for info in agent_info.values():
        lats = info["latencies"]
        avg_lat = sum(lats) / len(lats) if lats else 0.0
        agents_list.append(
            AgentStats(
                name=info["name"],
                type=info["type"],
                call_count=info["call_count"],
                total_tokens=info["total_tokens"],
                avg_latency_ms=round(avg_lat, 2),
                error_count=info["errors"],
            )
        )

    # Duration calculation
    total_duration_ms = 0
    if events:
        start_t = events[0].timestamp
        end_t = db_session.ended_at or events[-1].timestamp
        total_duration_ms = int((end_t - start_t).total_seconds() * 1000)

    return StatsResponse(
        total_tokens=aggregates["total_tokens"],
        total_cost_usd=round(aggregates["total_cost"], 6),
        total_duration_ms=total_duration_ms,
        event_count=event_count,
        error_count=aggregates["error_count"],
        agents=agents_list,
        token_timeline=timeline,
    )


@router.get("/{session_id}/export", response_model=SessionExport)
async def export_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """Export an entire session and all telemetry events as JSON."""
    sess_stmt = select(SessionModel).where(SessionModel.session_id == session_id)
    sess_res = await db.execute(sess_stmt)
    db_session = sess_res.scalars().first()
    if not db_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    event_stmt = (
        select(EventModel)
        .where(EventModel.session_id == session_id)
        .order_by(EventModel.timestamp.asc())
    )
    event_res = await db.execute(event_stmt)
    events = event_res.scalars().all()

    return SessionExport(
        version="1.0",
        exported_at=datetime.now(timezone.utc),
        session=SessionResponse.model_validate(db_session),
        events=[EventResponse.model_validate(ev) for ev in events],
    )


@router.post(
    "/import", response_model=SessionResponse, status_code=status.HTTP_201_CREATED
)
async def import_session(
    payload: SessionImportPayload, db: AsyncSession = Depends(get_db)
):
    """Import a session and its associated events from a JSON export."""
    imported_sess = payload.session
    session_id = imported_sess.session_id

    # Check if session exists; if so, create with a unique disambiguated ID
    existing_stmt = select(SessionModel).where(SessionModel.session_id == session_id)
    existing_res = await db.execute(existing_stmt)
    existing_session = existing_res.scalars().first()

    target_session_id = session_id
    if existing_session:
        target_session_id = f"{session_id}_imported_{uuid.uuid4().hex[:6]}"

    # Check for any conflicting event_ids in the database
    incoming_event_ids = [ev.event_id for ev in payload.events]
    existing_event_ids = set()
    if incoming_event_ids:
        chk_stmt = select(EventModel.event_id).where(
            EventModel.event_id.in_(incoming_event_ids)
        )
        chk_res = await db.execute(chk_stmt)
        existing_event_ids = set(chk_res.scalars().all())

    # Map original event IDs to new unique event IDs if conflict exists
    event_id_map: Dict[str, str] = {}
    for ev in payload.events:
        if ev.event_id in existing_event_ids or existing_session:
            event_id_map[ev.event_id] = f"{ev.event_id}_{uuid.uuid4().hex[:6]}"

    db_session = SessionModel(
        session_id=target_session_id,
        name=(
            imported_sess.name
            if not existing_session
            else f"{imported_sess.name} (Imported)"
        ),
        status=imported_sess.status,
        started_at=imported_sess.started_at,
        ended_at=imported_sess.ended_at,
        total_tokens=imported_sess.total_tokens,
        total_cost_usd=imported_sess.total_cost_usd,
        error_count=imported_sess.error_count,
        agent_count=imported_sess.agent_count,
        metadata_=imported_sess.metadata or {},
    )
    db.add(db_session)
    await db.flush()

    for ev in payload.events:
        new_event_id = event_id_map.get(ev.event_id, ev.event_id)
        new_parent_id = (
            event_id_map.get(ev.parent_event_id, ev.parent_event_id)
            if ev.parent_event_id
            else None
        )

        db_event = EventModel(
            event_id=new_event_id,
            session_id=target_session_id,
            parent_event_id=new_parent_id,
            event_type=ev.event_type,
            agent_name=ev.agent_name,
            agent_type=ev.agent_type,
            timestamp=ev.timestamp,
            latency_ms=ev.latency_ms,
            status=ev.status,
            payload=ev.payload,
        )
        db.add(db_event)

    await db.commit()
    await db.refresh(db_session)

    # Broadcast imported session to UI clients
    session_data = {
        "session_id": db_session.session_id,
        "name": db_session.name,
        "status": db_session.status,
        "started_at": db_session.started_at.isoformat(),
        "total_tokens": db_session.total_tokens,
        "total_cost_usd": db_session.total_cost_usd,
        "error_count": db_session.error_count,
        "agent_count": db_session.agent_count,
        "metadata": db_session.metadata_,
    }
    await manager.broadcast_session_update(db_session.session_id, session_data)

    return db_session


@router.post("/prune", response_model=Dict[str, Any])
async def prune_sessions(
    retention_days: Optional[int] = Query(
        None, description="Prune sessions older than N days"
    ),
    max_sessions: Optional[int] = Query(
        None, description="Prune oldest sessions if total count exceeds N"
    ),
    vacuum: bool = Query(
        True, description="Execute SQLite auto-vacuum after pruning"
    ),
):
    """Manually trigger session retention pruning and SQLite auto-vacuum."""
    pruned = await prune_old_sessions(
        retention_days=retention_days,
        max_sessions=max_sessions,
        vacuum=vacuum,
    )
    return {
        "status": "success",
        "pruned_sessions": pruned,
        "vacuum_executed": vacuum and pruned > 0,
    }

