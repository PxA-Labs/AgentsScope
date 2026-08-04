from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, AliasChoices


class SessionStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SessionCreate(BaseModel):
    session_id: Optional[str] = None
    name: str
    metadata: Optional[Dict[str, Any]] = None


class SessionUpdate(BaseModel):
    status: SessionStatus
    ended_at: Optional[datetime] = None


class SessionResponse(BaseModel):
    session_id: str
    name: str
    status: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    error_count: int = 0
    agent_count: int = 0
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata_", "metadata"),
    )

    class Config:
        from_attributes = True


class EventResponse(BaseModel):
    event_id: str
    session_id: str
    parent_event_id: Optional[str] = None
    event_type: str
    agent_name: str
    agent_type: str
    timestamp: datetime
    latency_ms: Optional[int] = None
    status: str
    payload: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class NodePosition(BaseModel):
    x: float
    y: float


class NodeData(BaseModel):
    label: str
    agentName: str
    eventType: str
    durationMs: Optional[int] = None
    tokenCount: Optional[int] = None
    status: str


class ReactFlowNode(BaseModel):
    id: str
    type: str
    position: NodePosition
    data: NodeData


class ReactFlowEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str = "default"  # "default" or "error"


class GraphResponse(BaseModel):
    nodes: List[ReactFlowNode]
    edges: List[ReactFlowEdge]


class AgentStats(BaseModel):
    name: str
    type: str
    call_count: int
    total_tokens: int
    avg_latency_ms: float
    error_count: int


class TokenTimelinePoint(BaseModel):
    timestamp: str
    cumulative_tokens: int


class StatsResponse(BaseModel):
    total_tokens: int
    total_cost_usd: float
    total_duration_ms: int
    event_count: int
    error_count: int
    agents: List[AgentStats]
    token_timeline: List[TokenTimelinePoint]


class PaginatedEventsResponse(BaseModel):
    events: List[EventResponse]
    total_count: int
    page: int
    limit: int
    total_pages: int

