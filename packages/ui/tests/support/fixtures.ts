import type { AgentEvent, GraphResponse, ReactFlowEdge, ReactFlowNode, Session } from "../../types";

export function makeSession(overrides: Partial<Session> = {}): Session {
  return {
    session_id: "11111111-aaaa-bbbb-cccc-000000000001",
    name: "Research Crew",
    status: "running",
    started_at: "2026-11-20T10:00:00Z",
    ended_at: null,
    total_tokens: 120,
    total_cost_usd: 0.0012,
    error_count: 0,
    agent_count: 2,
    metadata: {},
    ...overrides,
  };
}

export function makeEvent(overrides: Partial<AgentEvent> = {}): AgentEvent {
  return {
    event_id: "evt-1",
    session_id: "11111111-aaaa-bbbb-cccc-000000000001",
    parent_event_id: null,
    event_type: "llm_start",
    agent_name: "planner",
    agent_type: "llm",
    timestamp: "2026-11-20T10:00:01Z",
    latency_ms: null,
    status: "running",
    payload: { model: "gpt-4o", prompts: ["Plan the trip"], completion: null },
    ...overrides,
  };
}

export function makeNode(id: string, overrides: Partial<ReactFlowNode> = {}): ReactFlowNode {
  return {
    id,
    type: "LLMNode",
    position: { x: 0, y: 0 },
    data: {
      label: id,
      agentName: `agent-${id}`,
      eventType: "llm_start",
      durationMs: null,
      tokenCount: null,
      status: "running",
    },
    ...overrides,
  };
}

export function makeEdge(source: string, target: string): ReactFlowEdge {
  return { id: `${source}->${target}`, source, target, type: "default" };
}

export function makeGraph(nodes: ReactFlowNode[], edges: ReactFlowEdge[] = []): GraphResponse {
  return { nodes, edges };
}
