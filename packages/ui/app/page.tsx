"use client";

import React, { useCallback, useState } from "react";
import { Activity } from "lucide-react";
import { AgentGraph } from "../components/AgentGraph";
import { EventFeed } from "../components/EventFeed";
import { MemoriesPanel } from "../components/MemoriesPanel";
import { SessionHeader, type DashboardTab } from "../components/SessionHeader";
import { SessionList } from "../components/SessionList";
import { StatsPanel } from "../components/StatsPanel";
import { useLiveEvents } from "../hooks/useLiveEvents";
import { useMemories } from "../hooks/useMemories";
import { useSessionDetail } from "../hooks/useSessionDetail";
import { useSessions } from "../hooks/useSessions";
import { useSessionStore } from "../store/sessionStore";
import type { Session } from "../types";

function NoSessionSelected() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground text-center p-8">
      <Activity className="w-16 h-16 text-muted-foreground/20 mb-4 animate-pulse" />
      <h2 className="text-lg font-bold text-white mb-1">No Active Session Selected</h2>
      <p className="text-xs max-w-xs">
        Select an execution session from the left sidebar list or launch an agent pipeline to start
        streaming telemetry.
      </p>
    </div>
  );
}

export default function Dashboard() {
  const sessions = useSessionStore((s) => s.sessions);
  const activeSession = useSessionStore((s) => s.activeSession);
  const events = useSessionStore((s) => s.events);
  const graph = useSessionStore((s) => s.graph);
  const stats = useSessionStore((s) => s.stats);

  const [activeTab, setActiveTab] = useState<DashboardTab>("execution");
  // Kept here (not in the feed) so expanded cards survive switching tabs.
  const [expandedEvents, setExpandedEvents] = useState<Record<string, boolean>>({});

  const { selectSession, refreshGraphAndStats } = useSessionDetail();
  const { refresh: refreshSessions } = useSessions(selectSession);
  const wsStatus = useLiveEvents(refreshGraphAndStats);
  const memories = useMemories(activeSession, activeTab === "memories");

  const handleImported = useCallback(
    async (session: Session) => {
      await refreshSessions();
      selectSession(session);
    },
    [refreshSessions, selectSession]
  );

  const toggleExpandEvent = useCallback((eventId: string) => {
    setExpandedEvents((prev) => ({
      ...prev,
      [eventId]: !prev[eventId],
    }));
  }, []);

  return (
    <div className="flex h-screen overflow-hidden text-gray-200">
      <SessionList
        sessions={sessions}
        activeSessionId={activeSession?.session_id ?? null}
        onSelect={selectSession}
        onRefresh={refreshSessions}
        onImported={handleImported}
      />

      <main className="flex-1 flex flex-col overflow-hidden bg-background">
        {activeSession ? (
          <>
            <SessionHeader
              session={activeSession}
              wsStatus={wsStatus}
              activeTab={activeTab}
              onTabChange={setActiveTab}
            />
            <StatsPanel session={activeSession} stats={stats} />

            {activeTab === "execution" ? (
              <div className="flex-1 flex overflow-hidden p-4 pt-0 gap-4">
                <EventFeed
                  events={events}
                  expandedEvents={expandedEvents}
                  onToggleEvent={toggleExpandEvent}
                />
                <AgentGraph graph={graph} />
              </div>
            ) : (
              <MemoriesPanel {...memories} />
            )}
          </>
        ) : (
          <NoSessionSelected />
        )}
      </main>
    </div>
  );
}
