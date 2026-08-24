from datetime import datetime, timezone

from database import Base
from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship


class SessionModel(Base):
    """SQLAlchemy model representing an execution session."""

    __tablename__ = "sessions"

    session_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False)  # "running", "completed", "failed"
    started_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    ended_at = Column(DateTime, nullable=True)
    total_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    error_count = Column(Integer, default=0)
    agent_count = Column(Integer, default=0)
    metadata_ = Column("metadata", JSON, default=dict)

    # Cascades deletions down to individual events via database-level cascade
    events = relationship(
        "EventModel",
        back_populates="session",
    )


class EventModel(Base):
    """SQLAlchemy model representing a recorded telemetry event."""

    __tablename__ = "events"

    event_id = Column(String, primary_key=True)
    session_id = Column(
        String,
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    parent_event_id = Column(
        String,
        ForeignKey("events.event_id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    event_type = Column(String, nullable=False)
    agent_name = Column(String, nullable=False)
    agent_type = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    latency_ms = Column(Integer, nullable=True)
    status = Column(String, nullable=False)
    payload = Column(JSON, nullable=True)

    session = relationship("SessionModel", back_populates="events")
    parent = relationship("EventModel", remote_side=[event_id])
