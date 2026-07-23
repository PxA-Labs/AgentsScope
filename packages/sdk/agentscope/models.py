from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


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
