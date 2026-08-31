# AgentScope Data Schema Reference

> [!NOTE]
> This document defines all data models, database schemas, API request/response shapes, and WebSocket message formats used across the three AgentScope modules (SDK, Server, UI). It serves as the canonical reference for ALL data structures in the system.

## 1. Overview

AgentScope relies on a consistent set of core data models across its stack:
- **TypeScript interfaces** for the frontend UI and SDK.
- **Pydantic models** for server-side validation and API contracts.
- **SQLAlchemy ORM models** for data persistence.

The system communicates via REST APIs for static data loading and WebSockets for real-time event streaming and ingestion.

## 2. Core Data Models

### 2.1 Session

A Session represents a single execution run of a multi-agent pipeline.

```typescript
interface Session {
  session_id: string          // UUID v4
  name: string                // human-readable, e.g. "research_pipeline_run_3"
  status: "running" | "completed" | "failed"
  started_at: string          // ISO 8601
  ended_at: string | null
  total_tokens: number
  total_cost_usd: number
  error_count: number
  agent_count: number         // distinct agent names seen
  metadata: Record<string, any>  // arbitrary user-supplied tags
}
```

### 2.2 AgentEvent

An AgentEvent represents a single observable action, state change, or output from any component within the agent pipeline.

```typescript
interface AgentEvent {
  event_id: string            // maps directly to LangChain's run_id (UUID)
  session_id: string
  parent_event_id: string | null  // maps to LangChain's parent_run_id
  event_type: EventType
  agent_name: string
  agent_type: "chain" | "llm" | "tool" | "retriever" | "agent" | "custom"
  timestamp: string           // ISO 8601
  latency_ms: number | null   // only on *_end events
  status: "running" | "completed" | "error"
  payload: LLMPayload | ToolPayload | ChainPayload | RetrieverPayload
}

type EventType =
  | "chain_start" | "chain_end" | "chain_error"
  | "llm_start" | "llm_end" | "llm_token" | "llm_error"
  | "tool_start" | "tool_end" | "tool_error"
  | "agent_action" | "agent_finish"
  | "retriever_start" | "retriever_end"
```

### 2.3 Payload Types

```typescript
interface LLMPayload {
  model: string
  prompts: string[]
  completion: string | null
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
  temperature: number | null
  streaming: boolean
}

interface ToolPayload {
  tool_name: string
  tool_description: string | null
  input: string
  output: string | null
  error: string | null
}

interface ChainPayload {
  chain_type: string
  inputs: Record<string, any>
  outputs: Record<string, any> | null
  error: string | null
}

interface RetrieverPayload {
  query: string
  documents: Array<{ content: string; metadata: Record<string, any> }> | null
}
```

## 3. Database Schema (SQLite / SQLAlchemy)

The server utilizes SQLite for local persistent storage. 

> [!TIP]
> SQLite is configured with `PRAGMA journal_mode=WAL;` and `PRAGMA foreign_keys=ON;` for better concurrency and integrity.

```sql
-- Enable WAL mode
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at DATETIME NOT NULL,
    ended_at DATETIME,
    total_tokens INTEGER DEFAULT 0,
    total_cost_usd REAL DEFAULT 0.0,
    error_count INTEGER DEFAULT 0,
    agent_count INTEGER DEFAULT 0,
    metadata JSON
);

CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    parent_event_id TEXT,
    event_type TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    latency_ms INTEGER,
    status TEXT NOT NULL,
    payload JSON,
    FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_event_id) REFERENCES events (event_id) ON DELETE SET NULL
);

-- Indexes for performance
CREATE INDEX idx_events_session_id ON events(session_id);
CREATE INDEX idx_events_parent_event_id ON events(parent_event_id);
```

## 4. API Request/Response Schemas

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/sessions` | `{ "name": "...", "metadata": {} }` | `Session` |
| GET | `/sessions` | `?page=1&limit=10` | `{ "sessions": Session[], "total": 100, "page": 1 }` |
| GET | `/sessions/{id}` | — | `Session` |
| PATCH | `/sessions/{id}` | `{ "status": "completed", "ended_at": "..." }` | `Session` |
| DELETE | `/sessions/{id}` | — | `{ "deleted": true }` |
| GET | `/sessions/{id}/events` | `?type=llm_start&agent=Agent1&limit=50` | `{ "events": AgentEvent[] }` |
| GET | `/sessions/{id}/events/{event_id}`| — | `AgentEvent` |
| GET | `/sessions/{id}/graph` | — | `GraphResponse` |
| GET | `/sessions/{id}/stats` | — | `StatsResponse` |
| GET | `/health` | — | `{ "status": "ok", "version": "1.0.0" }` |

### Derived API Response Types

```typescript
interface GraphResponse {
  nodes: ReactFlowNode[]
  edges: ReactFlowEdge[]
}

interface ReactFlowNode {
  id: string
  type: "ChainNode" | "LLMNode" | "ToolNode" | "RetrieverNode"
  position: { x: number; y: number }
  data: {
    label: string
    agentName: string
    eventType: string
    durationMs: number | null
    tokenCount: number | null
    status: "completed" | "error" | "running"
  }
}

interface ReactFlowEdge {
  id: string
  source: string
  target: string
  type: "default" | "error"
}

interface StatsResponse {
  total_tokens: number
  total_cost_usd: number
  total_duration_ms: number
  event_count: number
  error_count: number
  agents: Array<{
    name: string
    type: string
    call_count: number
    total_tokens: number
    avg_latency_ms: number
    error_count: number
  }>
  token_timeline: Array<{ timestamp: string; cumulative_tokens: number }>
}
```

## 5. WebSocket Message Formats

WebSockets are utilized for fast streaming of events from the SDK to the Server, and then broadcasting those to the UI.

### 5.1 Connection Handshake
- **UI Client:** `ws://localhost:8765/ws?client_type=ui&session_id={id}`
- **SDK Client:** `ws://localhost:8765/ws?client_type=sdk`

### 5.2 SDK → Server (Event Ingestion)
```json
{
  "type": "event",
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "event": { 
     "event_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d", 
     "event_type": "llm_start",
     "agent_name": "Writer",
     "agent_type": "llm",
     "status": "running",
     "timestamp": "2026-07-21T15:10:00Z"
  }
}
```

### 5.3 Server → UI (Broadcast)
Broadcasts include the same event shapes as ingestion, but also add `session_update` events when session states change globally.
```json
{
  "type": "session_update",
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "session": { 
     "status": "completed", 
     "ended_at": "2026-07-21T15:10:00Z", 
     "total_tokens": 4821 
  }
}
```

## 6. Pydantic Models (Python)

```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List, Union
from datetime import datetime
from enum import Enum

class SessionStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class Session(BaseModel):
    session_id: str
    name: str
    status: SessionStatus
    started_at: datetime
    ended_at: Optional[datetime] = None
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    error_count: int = 0
    agent_count: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)

class EventType(str, Enum):
    CHAIN_START = "chain_start"
    CHAIN_END = "chain_end"
    CHAIN_ERROR = "chain_error"
    LLM_START = "llm_start"
    LLM_END = "llm_end"
    LLM_TOKEN = "llm_token"
    LLM_ERROR = "llm_error"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    TOOL_ERROR = "tool_error"
    AGENT_ACTION = "agent_action"
    AGENT_FINISH = "agent_finish"
    RETRIEVER_START = "retriever_start"
    RETRIEVER_END = "retriever_end"

class LLMPayload(BaseModel):
    model: str
    prompts: List[str]
    completion: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    temperature: Optional[float] = None
    streaming: bool

class ToolPayload(BaseModel):
    tool_name: str
    tool_description: Optional[str] = None
    input: str
    output: Optional[str] = None
    error: Optional[str] = None

class ChainPayload(BaseModel):
    chain_type: str
    inputs: Dict[str, Any]
    outputs: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class Document(BaseModel):
    content: str
    metadata: Dict[str, Any]

class RetrieverPayload(BaseModel):
    query: str
    documents: Optional[List[Document]] = None

class AgentEvent(BaseModel):
    event_id: str
    session_id: str
    parent_event_id: Optional[str] = None
    event_type: EventType
    agent_name: str
    agent_type: str
    timestamp: datetime
    latency_ms: Optional[int] = None
    status: str
    payload: Union[LLMPayload, ToolPayload, ChainPayload, RetrieverPayload]
```

## 7. SQLAlchemy ORM Models (Python)

```python
from typing import Any, Dict
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class SessionModel(Base):
    __tablename__ = 'sessions'

    session_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    total_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    error_count = Column(Integer, default=0)
    agent_count = Column(Integer, default=0)
    metadata_ = Column("metadata", JSON, default=dict)

    events = relationship("EventModel", back_populates="session", cascade="all, delete-orphan")


class EventModel(Base):
    __tablename__ = 'events'

    event_id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey('sessions.session_id', ondelete='CASCADE'), index=True, nullable=False)
    parent_event_id = Column(String, ForeignKey('events.event_id', ondelete='SET NULL'), index=True, nullable=True)
    event_type = Column(String, nullable=False)
    agent_name = Column(String, nullable=False)
    agent_type = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    latency_ms = Column(Integer, nullable=True)
    status = Column(String, nullable=False)
    payload = Column(JSON, nullable=True)

    session = relationship("SessionModel", back_populates="events")
    parent = relationship("EventModel", remote_side=[event_id])
```

## 8. Token Pricing Table

> [!NOTE]  
> This pricing table is maintained in the repository-level [`pricing.json`](../pricing.json) file and loaded by both the SDK and Server, with embedded fallbacks for standalone package/container installations. Rates are estimates used for cost calculations during an active session.

| Model | Input Price ($ / 1M tokens) | Output Price ($ / 1M tokens) |
|---|---|---|
| `gpt-4o` | $2.50 | $10.00 |
| `gpt-4o-mini` | $0.15 | $0.60 |
| `gpt-4-turbo` | $10.00 | $30.00 |
| `gpt-4` | $30.00 | $60.00 |
| `gpt-3.5-turbo` | $0.50 | $1.50 |
| `claude-3-5-sonnet` | $3.00 | $15.00 |
| `claude-3-haiku` | $0.25 | $1.25 |
| `claude-3-opus` | $15.00 | $75.00 |
| `gemini-1.5-pro` | $1.25 | $5.00 |
| `gemini-1.5-flash` | $0.075 | $0.30 |

## 9. Enums & Constants

- **Session Statuses**: `running`, `completed`, `failed`
- **Agent Types**: `chain`, `llm`, `tool`, `retriever`, `agent`, `custom`
- **Event Statuses**: `running`, `completed`, `error`
- **Event Types**:
  - `chain_start`, `chain_end`, `chain_error`
  - `llm_start`, `llm_end`, `llm_token`, `llm_error`
  - `tool_start`, `tool_end`, `tool_error`
  - `agent_action`, `agent_finish`
  - `retriever_start`, `retriever_end`

---

*This document is auto-generated as the canonical reference for AgentScope data structures.*
