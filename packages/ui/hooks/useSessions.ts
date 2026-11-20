"use client";

import { useCallback, useEffect } from "react";
import { listSessions } from "../lib/api";
import { useSessionStore } from "../store/sessionStore";
import type { Session } from "../types";
import { useUnauthorized } from "./useUnauthorized";

/** How often the session list is re-polled. */
export const SESSIONS_POLL_INTERVAL_MS = 4000;

/**
 * Keeps the session list in the store fresh: fetches it now and then every
 * SESSIONS_POLL_INTERVAL_MS, and auto-selects the newest session while none
 * is active. Polling pauses once the server rejects our credentials, since
 * retrying with them cannot succeed and only adds load on the server.
 *
 * Returns `refresh` for the manual refresh button and the import flow.
 */
export function useSessions(selectSession: (session: Session) => void) {
  const activeSession = useSessionStore((s) => s.activeSession);
  const setSessions = useSessionStore((s) => s.setSessions);
  const unauthorized = useUnauthorized();

  const refresh = useCallback(async () => {
    try {
      const data = await listSessions();
      if (data) {
        setSessions(data.sessions);

        // Auto-select first session if none selected
        if (data.sessions.length > 0 && !activeSession) {
          selectSession(data.sessions[0]);
        }
      }
    } catch (e) {
      console.warn("Failed to fetch sessions list", e);
    }
  }, [activeSession, selectSession, setSessions]);

  // Restarted whenever the active session changes (via `refresh`), which also
  // triggers an immediate refetch, as the dashboard has always done.
  useEffect(() => {
    if (unauthorized) return;
    refresh();
    const interval = setInterval(refresh, SESSIONS_POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refresh, unauthorized]);

  return { refresh };
}
