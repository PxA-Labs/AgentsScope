import { create } from "zustand";
import { Session, AgentEvent } from "../types";

interface SessionState {
  sessions: Session[];
  activeSession: Session | null;
  events: AgentEvent[];
  setSessions: (sessions: Session[]) => void;
  setActiveSession: (session: Session | null) => void;
  setEvents: (events: AgentEvent[]) => void;
  addEvent: (event: AgentEvent) => void;
  updateSessionMeta: (sessionId: string, meta: Partial<Session>) => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  sessions: [],
  activeSession: null,
  events: [],

  setSessions: (sessions) => set({ sessions }),

  setActiveSession: (activeSession) => set({ activeSession }),

  setEvents: (events) => set({ events }),

  addEvent: (event) =>
    set((state) => {
      // Only process event if it belongs to the active session
      if (state.activeSession?.session_id !== event.session_id) {
        return {};
      }

      const existingIndex = state.events.findIndex(
        (e) => e.event_id === event.event_id
      );

      let newEvents;
      if (existingIndex > -1) {
        // Merge or replace existing event (e.g. start -> end update)
        newEvents = [...state.events];
        newEvents[existingIndex] = {
          ...newEvents[existingIndex],
          ...event,
          timestamp: newEvents[existingIndex].timestamp,
          payload: {
            ...newEvents[existingIndex].payload,
            ...event.payload,
          },
        };
      } else {
        // Append new event
        newEvents = [...state.events, event];
      }

      return { events: newEvents };
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
}));
