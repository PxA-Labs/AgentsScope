export type SessionStatus = "running" | "completed" | "failed";

export interface Session {
  session_id: string;
  name: string;
  status: SessionStatus;
  started_at: string; // ISO 8601
  ended_at: string | null;
  total_tokens: number;
  total_cost_usd: number;
  error_count: number;
  agent_count: number;
  metadata: Record<string, any>;
}

export type EventType =
  | "chain_start"
  | "chain_end"
  | "chain_error"
  | "llm_start"
  | "llm_end"
  | "llm_token"
  | "llm_error"
  | "tool_start"
  | "tool_end"
  | "tool_error"
  | "agent_action"
  | "agent_finish"
  | "retriever_start"
  | "retriever_end";

export interface LLMPayload {
  model: string;
  prompts: string[];
  completion: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  temperature: number | null;
  streaming: boolean;
}

export interface ToolPayload {
  tool_name: string;
  tool_description: string | null;
  input: string;
  output: string | null;
  error: string | null;
}

export interface ChainPayload {
  chain_type: string;
  inputs: Record<string, any>;
  outputs: Record<string, any> | null;
  error: string | null;
}

export interface Document {
  content: string;
  metadata: Record<string, any>;
}

export interface RetrieverPayload {
  query: string;
  documents: Document[] | null;
}

export interface AgentEvent {
  event_id: string;
  session_id: string;
  parent_event_id: string | null;
  event_type: EventType;
  agent_name: string;
  agent_type: "chain" | "llm" | "tool" | "retriever" | "agent" | "custom";
  timestamp: string; // ISO 8601
  latency_ms: number | null;
  status: "running" | "completed" | "error";
  payload: LLMPayload | ToolPayload | ChainPayload | RetrieverPayload | Record<string, any>;
}

// React Flow Layout Types
export interface ReactFlowNode {
  id: string;
  type: "ChainNode" | "LLMNode" | "ToolNode" | "RetrieverNode";
  position: { x: number; y: number };
  data: {
    label: string;
    agentName: string;
    eventType: string;
    durationMs: number | null;
    tokenCount: number | null;
    status: "completed" | "error" | "running";
  };
}

export interface ReactFlowEdge {
  id: string;
  source: string;
  target: string;
  type: "default" | "error";
}

export interface GraphResponse {
  nodes: ReactFlowNode[];
  edges: ReactFlowEdge[];
}

// Session Statistics Types
export interface AgentStats {
  name: string;
  type: string;
  call_count: number;
  total_tokens: number;
  avg_latency_ms: number;
  error_count: number;
}

export interface TokenTimelinePoint {
  timestamp: string;
  cumulative_tokens: number;
}

export interface StatsResponse {
  total_tokens: number;
  total_cost_usd: number;
  total_duration_ms: number;
  event_count: number;
  error_count: number;
  agents: AgentStats[];
  token_timeline: TokenTimelinePoint[];
}
