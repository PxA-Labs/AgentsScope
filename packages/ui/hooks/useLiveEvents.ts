"use client";

import { useEffect, useEffectEvent, useState } from "react";
import { notifyUnauthorized, openWebSocket, WS_CLOSE_UNAUTHORIZED } from "../lib/api";
import { useSessionStore } from "../store/sessionStore";
import type { AgentEvent, ReactFlowEdge, ReactFlowNode, Session } from "../types";

export type WsStatus = "connected" | "connecting" | "disconnected";

/** First reconnect delay; doubled after every failed attempt. */
export const WS_INITIAL_RECONNECT_DELAY_MS = 2000;
/** Upper bound for the reconnect delay. */
export const WS_MAX_RECONNECT_DELAY_MS = 30000;

type LiveMessage =
  | { type: "event"; session_id: string; event: AgentEvent }
  | {
      type: "graph_update";
      session_id: string;
      node: ReactFlowNode | null;
      edge: ReactFlowEdge | null;
    }
  | { type: "session_update"; session_id: string; session: Partial<Session> };

/**
 * The dashboard's only WebSocket: streams the active session's events, live
 * DAG deltas and session aggregates into the store.
 *
 * Reconnects with exponential backoff (2s, 4s, ... capped at 30s, reset on a
 * successful open). A close with code 4401 (rejected credentials) does not
 * reconnect; it raises UNAUTHORIZED_EVENT so the AuthBanner can ask for a key.
 * The socket is replaced when another session becomes active; updates to the
 * active session's aggregates (session_update) keep the same socket.
 *
 * Returns the connection status for the header indicator.
 */
export function useLiveEvents(refreshGraphAndStats: (sessionId: string) => void): WsStatus {
  // Keyed by id: session_update replaces the activeSession object on every
  // event, and reconnecting then would drop events sent in the meantime.
  const sessionId = useSessionStore((s) => s.activeSession?.session_id ?? null);
  const addEvent = useSessionStore((s) => s.addEvent);
  const applyGraphUpdate = useSessionStore((s) => s.applyGraphUpdate);
  const updateSessionMeta = useSessionStore((s) => s.updateSessionMeta);
  const [wsStatus, setWsStatus] = useState<WsStatus>("connecting");
  // Always calls the latest callback without making the socket depend on it.
  const onTerminalEvent = useEffectEvent((sessionId: string) => refreshGraphAndStats(sessionId));

  useEffect(() => {
    if (!sessionId) return;

    let ws: WebSocket | null = null;
    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
    let isCancelled = false;
    let currentDelay = WS_INITIAL_RECONNECT_DELAY_MS;

    const scheduleReconnect = () => {
      const nextDelay = currentDelay;
      currentDelay = Math.min(currentDelay * 2, WS_MAX_RECONNECT_DELAY_MS);
      reconnectTimeout = setTimeout(connectWS, nextDelay);
    };

    const handleMessage = (message: LiveMessage) => {
      if (message.session_id !== sessionId) return;
      if (message.type === "event") {
        addEvent(message.event);
        // Refresh stats when new terminal event lands
        const eventType = message.event.event_type;
        if (eventType.endsWith("_end") || eventType.endsWith("_error")) {
          onTerminalEvent(sessionId);
        }
      } else if (message.type === "graph_update") {
        // Live DAG streaming: merge the incremental node/edge. The full
        // layout is resynced from the REST graph endpoint on terminal events.
        if (message.node) applyGraphUpdate(message.node, message.edge);
      } else if (message.type === "session_update") {
        updateSessionMeta(message.session_id, message.session);
      }
    };

    function connectWS() {
      if (isCancelled) return;
      setWsStatus("connecting");
      try {
        ws = openWebSocket(`/ws?client_type=ui&session_id=${sessionId}`);

        ws.onopen = () => {
          if (isCancelled) return;
          setWsStatus("connected");
          currentDelay = WS_INITIAL_RECONNECT_DELAY_MS; // Reset backoff upon successful connection
        };

        ws.onmessage = (event) => {
          if (isCancelled) return;
          try {
            handleMessage(JSON.parse(event.data) as LiveMessage);
          } catch (err) {
            console.error("Error processing websocket payload:", err);
          }
        };

        ws.onerror = (err) => {
          if (isCancelled) return;
          console.warn("WebSocket encountered error:", err);
          setWsStatus("disconnected");
        };

        ws.onclose = (event) => {
          if (isCancelled) return;
          if (event.code === WS_CLOSE_UNAUTHORIZED) {
            // Retrying with the same credentials cannot succeed; wait for the
            // user to enter a key (saving it reloads the dashboard).
            setWsStatus("disconnected");
            notifyUnauthorized();
            return;
          }
          setWsStatus("connecting");
          scheduleReconnect();
        };
      } catch {
        if (isCancelled) return;
        setWsStatus("disconnected");
        scheduleReconnect();
      }
    }

    connectWS();
    return () => {
      isCancelled = true;
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (ws) ws.close();
    };
  }, [sessionId, addEvent, applyGraphUpdate, updateSessionMeta]);

  return wsStatus;
}
