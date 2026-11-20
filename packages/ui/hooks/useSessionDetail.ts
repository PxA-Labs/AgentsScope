"use client";

import { useCallback } from "react";
import { getSessionEvents, getSessionGraph, getSessionStats } from "../lib/api";
import { useSessionStore } from "../store/sessionStore";
import type { Session } from "../types";

/**
 * Loading the selected session: its events, call graph and stats.
 *
 * `selectSession` makes a session active, clears the previous session's data
 * and then fetches events, graph and stats in turn; a failure in one does not
 * stop the others. `refreshGraphAndStats` re-reads graph and stats only (the
 * live feed calls it when a terminal event arrives).
 */
export function useSessionDetail() {
  const setActiveSession = useSessionStore((s) => s.setActiveSession);
  const setEvents = useSessionStore((s) => s.setEvents);
  const setGraph = useSessionStore((s) => s.setGraph);
  const setStats = useSessionStore((s) => s.setStats);

  const selectSession = useCallback(
    async (session: Session) => {
      setActiveSession(session);
      setEvents([]);
      setGraph(null);
      setStats(null);

      try {
        const data = await getSessionEvents(session.session_id);
        if (data) setEvents(data.events);
      } catch (e) {
        console.warn("Failed to fetch session events", e);
      }

      try {
        const graph = await getSessionGraph(session.session_id);
        if (graph) setGraph(graph);
      } catch (e) {
        console.warn("Failed to fetch session graph", e);
      }

      try {
        const stats = await getSessionStats(session.session_id);
        if (stats) setStats(stats);
      } catch (e) {
        console.warn("Failed to fetch session stats", e);
      }
    },
    [setActiveSession, setEvents, setGraph, setStats]
  );

  const refreshGraphAndStats = useCallback(
    async (sessionId: string) => {
      try {
        const graph = await getSessionGraph(sessionId);
        if (graph) setGraph(graph);

        const stats = await getSessionStats(sessionId);
        if (stats) setStats(stats);
      } catch (e) {
        console.warn("Refresh stats failed", e);
      }
    },
    [setGraph, setStats]
  );

  return { selectSession, refreshGraphAndStats };
}
