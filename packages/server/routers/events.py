from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import EventModel, SessionModel
from schemas import EventResponse

# Router prefix matches the session-event hierarchy
router = APIRouter(prefix="/sessions/{session_id}/events", tags=["events"])


@router.get("", response_model=Dict[str, List[EventResponse]])
async def list_session_events(
    session_id: str,
    event_type: Optional[str] = Query(None, alias="type"),
    agent_name: Optional[str] = Query(None, alias="agent"),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all logged telemetry events for a session, with optional type and agent filters."""
    # First, verify session exists
    sess_stmt = select(SessionModel).where(SessionModel.session_id == session_id)
    sess_res = await db.execute(sess_stmt)
    if not sess_res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    # Build filtered query
    stmt = (
        select(EventModel)
        .where(EventModel.session_id == session_id)
        .order_by(EventModel.timestamp.asc())
    )
    if event_type:
        stmt = stmt.where(EventModel.event_type == event_type)
    if agent_name:
        stmt = stmt.where(EventModel.agent_name == agent_name)

    stmt = stmt.limit(limit)
    res = await db.execute(stmt)
    events = res.scalars().all()

    return {"events": [EventResponse.model_validate(e) for e in events]}


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
