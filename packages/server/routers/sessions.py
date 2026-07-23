from datetime import datetime
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import SessionModel, EventModel
from schemas import (
    SessionCreate,
    SessionUpdate,
    SessionResponse,
    GraphResponse,
    StatsResponse,
    AgentStats,
    TokenTimelinePoint,
)
from ws_manager import manager
from graph_layout import compute_graph_layout

router = APIRouter(prefix="/sessions", tags=["sessions"])

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


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(session_in: SessionCreate, db: AsyncSession = Depends(get_db)):
    """Initialize a new observability session."""
    session_id = session_in.session_id or str(func.uuid())

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
        started_at=datetime.utcnow(),
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
    if session_update.ended_at:
        db_session.ended_at = session_update.ended_at
    else:
        db_session.ended_at = datetime.utcnow()

    # Recalculate session aggregates from events before finishing
    event_stmt = select(EventModel).where(EventModel.session_id == session_id)
    event_res = await db.execute(event_stmt)
    events = event_res.scalars().all()

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

            # calculate cost
            model = ev.payload.get("model") or ""
            prompt_tokens = ev.payload.get("prompt_tokens") or 0
            completion_tokens = ev.payload.get("completion_tokens") or 0
            total_cost += _calculate_llm_cost(model, prompt_tokens, completion_tokens)

    db_session.total_tokens = total_tokens
    db_session.total_cost_usd = total_cost
    db_session.error_count = error_count
    db_session.agent_count = len(agents)

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
    """Generate layout-positioned nodes and edges representing the agent call execution DAG."""
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
    """Compute aggregate execution stats, cost estimates, and token timelines for a session."""
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

    total_tokens = 0
    total_cost_usd = 0.0
    error_count = 0
    event_count = len(events)

    # Group stats by agent
    agent_info: Dict[str, Dict[str, Any]] = {}

    # Timeline
    timeline: List[TokenTimelinePoint] = []

    for ev in events:
        if ev.status == "error":
            error_count += 1

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
            total_tokens += tokens

            # cost
            model = ev.payload.get("model") or ""
            prompt_tokens = ev.payload.get("prompt_tokens") or 0
            completion_tokens = ev.payload.get("completion_tokens") or 0
            cost = _calculate_llm_cost(model, prompt_tokens, completion_tokens)
            total_cost_usd += cost

            agent_info[name]["total_tokens"] += tokens

            # Append timeline point
            timeline.append(
                TokenTimelinePoint(
                    timestamp=ev.timestamp.isoformat() + "Z",
                    cumulative_tokens=total_tokens,
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
        total_tokens=total_tokens,
        total_cost_usd=round(total_cost_usd, 6),
        total_duration_ms=total_duration_ms,
        event_count=event_count,
        error_count=error_count,
        agents=agents_list,
        token_timeline=timeline,
    )
