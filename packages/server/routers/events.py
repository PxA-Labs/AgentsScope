from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import EventModel, SessionModel
from schemas import EventResponse, PaginatedEventsResponse

# Router prefix matches the session-event hierarchy
router = APIRouter(prefix="/sessions/{session_id}/events", tags=["events"])


@router.get("", response_model=PaginatedEventsResponse)
async def list_session_events(
    session_id: str,
    event_type: Optional[str] = Query(None, alias="type"),
    agent_name: Optional[str] = Query(None, alias="agent"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve logged telemetry events for a session with optional filters and offset pagination."""
    # First, verify session exists
    sess_stmt = select(SessionModel).where(SessionModel.session_id == session_id)
    sess_res = await db.execute(sess_stmt)
    if not sess_res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    # Build count query
    count_stmt = select(func.count(EventModel.event_id)).where(
        EventModel.session_id == session_id
    )
    if event_type:
        count_stmt = count_stmt.where(EventModel.event_type == event_type)
    if agent_name:
        count_stmt = count_stmt.where(EventModel.agent_name == agent_name)

    count_res = await db.execute(count_stmt)
    total_count = count_res.scalar() or 0

    # Build paginated query
    stmt = (
        select(EventModel)
        .where(EventModel.session_id == session_id)
        .order_by(EventModel.timestamp.asc())
    )
    if event_type:
        stmt = stmt.where(EventModel.event_type == event_type)
    if agent_name:
        stmt = stmt.where(EventModel.agent_name == agent_name)

    offset = (page - 1) * limit
    stmt = stmt.offset(offset).limit(limit)
    res = await db.execute(stmt)
    events = res.scalars().all()

    total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1

    return {
        "events": [EventResponse.model_validate(e) for e in events],
        "total_count": total_count,
        "page": page,
        "limit": limit,
        "total_pages": max(1, total_pages),
    }


@router.get("/{event_id}", response_model=EventResponse)
async def get_session_event(
    session_id: str,
    event_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve raw details of a specific telemetry event by its run ID."""
    stmt = (
        select(EventModel)
        .where(EventModel.session_id == session_id)
        .where(EventModel.event_id == event_id)
    )
    res = await db.execute(stmt)
    event = res.scalars().first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found"
        )
    return event
