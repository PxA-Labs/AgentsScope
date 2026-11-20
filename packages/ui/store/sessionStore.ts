import { create } from "zustand";
import {
  Session,
  AgentEvent,
  GraphResponse,
  ReactFlowNode,
  ReactFlowEdge,
  StatsResponse,
} from "../types";

/** Horizontal gap between provisionally placed sibling nodes (live DAG). */
const SIBLING_OFFSET_X = 280;
/** Vertical gap between a provisionally placed node and its parent. */
const CHILD_OFFSET_Y = 180;

function isNotEmpty(val: unknown): boolean {
  return (
    val !== null &&
    val !== undefined &&
    val !== "" &&
    !(Array.isArray(val) && val.length === 0)
  );
}

/**
 * Upsert an event into the feed. A new event_id is appended; a known one is
 * merged into the existing entry (e.g. a start event updated by its end):
 * the original timestamp is kept and empty incoming payload values never
 * overwrite values we already have.
 */
export function upsertEvent(events: AgentEvent[], event: AgentEvent): AgentEvent[] {
  const existingIndex = events.findIndex((e) => e.event_id === event.event_id);
  if (existingIndex === -1) return [...events, event];

  const existing = events[existingIndex];
  const mergedPayload = { ...existing.payload } as Record<string, unknown>;
  const incomingPayload = (event.payload || {}) as Record<string, unknown>;
  for (const key in incomingPayload) {
    if (Object.prototype.hasOwnProperty.call(incomingPayload, key)) {
      const val = incomingPayload[key];
      if (isNotEmpty(val)) {
        mergedPayload[key] = val;
      } else if (!(key in mergedPayload)) {
        mergedPayload[key] = val;
      }
    }
  }

  const newEvents = [...events];
  newEvents[existingIndex] = {
    ...existing,
    ...event,
    timestamp: existing.timestamp,
    payload: mergedPayload,
  };
  return newEvents;
}

/**
 * Merge one live DAG delta (a `graph_update` WebSocket message) into the
 * current graph. Known nodes keep their laid-out position and only refresh
 * their data; new nodes are placed provisionally below their parent, offset
 * by existing siblings, until the full layout is resynced from the REST
 * graph endpoint on the next terminal event.
 */
export function mergeGraphUpdate(
  prev: GraphResponse | null,
  node: ReactFlowNode,
  edge: ReactFlowEdge | null
): GraphResponse {
  if (!prev) {
    return {
      nodes: [node],
      edges: edge ? [edge] : [],
    };
  }
  const existingIdx = prev.nodes.findIndex((n) => n.id === node.id);
  const newNodes = [...prev.nodes];
  if (existingIdx >= 0) {
    newNodes[existingIdx] = {
      ...newNodes[existingIdx],
      data: { ...newNodes[existingIdx].data, ...node.data },
    };
  } else {
    const parent = edge ? prev.nodes.find((n) => n.id === edge.source) : undefined;
    const siblings = edge ? prev.edges.filter((e) => e.source === edge.source).length : 0;
    newNodes.push({
      ...node,
      position: parent
        ? {
            x: parent.position.x + siblings * SIBLING_OFFSET_X,
            y: parent.position.y + CHILD_OFFSET_Y,
          }
        : node.position,
    });
  }
  const newEdges = [...prev.edges];
  if (edge && !newEdges.some((e) => e.id === edge.id)) {
    newEdges.push(edge);
  }
  return { nodes: newNodes, edges: newEdges };
}

interface SessionState {
  sessions: Session[];
  activeSession: Session | null;
  events: AgentEvent[];
  graph: GraphResponse | null;
  stats: StatsResponse | null;
  setSessions: (sessions: Session[]) => void;
  setActiveSession: (session: Session | null) => void;
  setEvents: (events: AgentEvent[]) => void;
  addEvent: (event: AgentEvent) => void;
  updateSessionMeta: (sessionId: string, meta: Partial<Session>) => void;
  setGraph: (graph: GraphResponse | null) => void;
  applyGraphUpdate: (node: ReactFlowNode, edge: ReactFlowEdge | null) => void;
  setStats: (stats: StatsResponse | null) => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  sessions: [],
  activeSession: null,
  events: [],
  graph: null,
  stats: null,

  setSessions: (sessions) => set({ sessions }),

  setActiveSession: (activeSession) => set({ activeSession }),

  setEvents: (events) => set({ events }),

  addEvent: (event) =>
    set((state) => {
      // Only process event if it belongs to the active session
      if (state.activeSession?.session_id !== event.session_id) {
        return {};
      }
      return { events: upsertEvent(state.events, event) };
    }),

  updateSessionMeta: (sessionId, meta) =>
    set((state) => {
      // 1. Update session in list
      const updatedSessions = state.sessions.map((s) =>
        s.session_id === sessionId ? { ...s, ...meta } : s
      );

      // 2. Update activeSession if matched
      const updatedActive =
        state.activeSession?.session_id === sessionId
          ? { ...state.activeSession, ...meta }
          : state.activeSession;

      return {
        sessions: updatedSessions,
        activeSession: updatedActive,
      };
    }),

  setGraph: (graph) => set({ graph }),

  applyGraphUpdate: (node, edge) =>
    set((state) => ({ graph: mergeGraphUpdate(state.graph, node, edge) })),

  setStats: (stats) => set({ stats }),
}));
