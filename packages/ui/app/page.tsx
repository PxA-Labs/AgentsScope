"use client";

import React, { useEffect, useState, useRef } from "react";
import { useSessionStore } from "../store/sessionStore";
import { Session, AgentEvent, ReactFlowNode, ReactFlowEdge } from "../types";
import {
  Activity,
  Layers,
  Cpu,
  Wrench,
  Database,
  ChevronDown,
  ChevronUp,
  DollarSign,
  Clock,
  AlertTriangle,
  Play,
  CheckCircle,
  XCircle,
  HelpCircle,
  RefreshCw,
  Search,
} from "lucide-react";

export default function Dashboard() {
  const {
    sessions,
    activeSession,
    events,
    setSessions,
    setActiveSession,
    setEvents,
    addEvent,
    updateSessionMeta,
  } = useSessionStore();

  const [graphData, setGraphData] = useState<{
    nodes: ReactFlowNode[];
    edges: ReactFlowEdge[];
  } | null>(null);
  const [statsData, setStatsData] = useState<any>(null);
  const [expandedEvents, setExpandedEvents] = useState<Record<string, boolean>>(
    {}
  );
  const [searchQuery, setSearchQuery] = useState("");

  const eventFeedEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll event feed to bottom
  useEffect(() => {
    eventFeedEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  // Fetch Session list
  const fetchSessionsList = async () => {
    try {
      const res = await fetch("http://127.0.0.1:8765/api/sessions");
      if (res.ok) {
        const data = await res.json();
        setSessions(data);

        // Auto-select first session if none selected
        if (data.length > 0 && !activeSession) {
          handleSelectSession(data[0]);
        }
      }
    } catch (e) {
      console.warn("Failed to fetch sessions list", e);
    }
  };

  useEffect(() => {
    fetchSessionsList();
    const interval = setInterval(fetchSessionsList, 4000);
    return () => clearInterval(interval);
  }, [activeSession]);

  // Handle active session selection
  const handleSelectSession = async (session: Session) => {
    setActiveSession(session);
    setEvents([]);
    setGraphData(null);
    setStatsData(null);

    // Fetch existing events
    try {
      const resEvents = await fetch(
        `http://127.0.0.1:8765/api/sessions/${session.session_id}/events`
      );
      if (resEvents.ok) {
        const eventsData = await resEvents.json();
        setEvents(eventsData);
      }
    } catch (e) {
      console.warn("Failed to fetch session events", e);
    }

    // Fetch graph
    try {
      const resGraph = await fetch(
        `http://127.0.0.1:8765/api/sessions/${session.session_id}/graph`
      );
      if (resGraph.ok) {
        const graph = await resGraph.json();
        setGraphData(graph);
      }
    } catch (e) {
      console.warn("Failed to fetch session graph", e);
    }

    // Fetch stats
    try {
      const resStats = await fetch(
        `http://127.0.0.1:8765/api/sessions/${session.session_id}/stats`
      );
      if (resStats.ok) {
        const stats = await resStats.json();
        setStatsData(stats);
      }
    } catch (e) {
      console.warn("Failed to fetch session stats", e);
    }
  };

  // WebSocket event stream
  useEffect(() => {
    if (!activeSession) return;

    let ws: WebSocket;
    const connectWS = () => {
      const host = window.location.hostname || "127.0.0.1";
      ws = new WebSocket(`ws://${host}:8765/ws?client_type=ui`);

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === "event" && message.session_id === activeSession.session_id) {
            addEvent(message.event);
            // Refresh graph & stats when new terminal event lands
            if (message.event.event_type.endsWith("_end") || message.event.event_type.endsWith("_error")) {
              fetchGraphAndStats(activeSession.session_id);
            }
          } else if (message.type === "session_update" && message.session_id === activeSession.session_id) {
            updateSessionMeta(message.session_id, message.meta);
          }
        } catch (err) {
          console.error("Error processing websocket payload:", err);
        }
      };

      ws.onclose = () => {
        setTimeout(connectWS, 2000);
      };
    };

    connectWS();
    return () => ws?.close();
  }, [activeSession]);

  const fetchGraphAndStats = async (sessionId: string) => {
    try {
      const resGraph = await fetch(`http://127.0.0.1:8765/api/sessions/${sessionId}/graph`);
      if (resGraph.ok) setGraphData(await resGraph.json());

      const resStats = await fetch(`http://127.0.0.1:8765/api/sessions/${sessionId}/stats`);
      if (resStats.ok) setStatsData(await resStats.json());
    } catch (e) {
      console.warn("Refresh stats failed", e);
    }
  };

  const toggleExpandEvent = (eventId: string) => {
    setExpandedEvents((prev) => ({
      ...prev,
      [eventId]: !prev[eventId],
    }));
  };

  const getEventIcon = (type: string) => {
    switch (type) {
      case "chain_start":
      case "chain_end":
      case "chain_error":
        return <Layers className="w-4 h-4 text-purple-400" />;
      case "llm_start":
      case "llm_end":
      case "llm_token":
      case "llm_error":
        return <Cpu className="w-4 h-4 text-sky-400" />;
      case "tool_start":
      case "tool_end":
      case "tool_error":
        return <Wrench className="w-4 h-4 text-emerald-400" />;
      case "retriever_start":
      case "retriever_end":
        return <Database className="w-4 h-4 text-amber-400" />;
      default:
        return <Activity className="w-4 h-4 text-gray-400" />;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "completed":
        return (
          <span className="flex items-center gap-1 text-xs text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full font-medium">
            <CheckCircle className="w-3 h-3" /> Completed
          </span>
        );
      case "failed":
      case "error":
        return (
          <span className="flex items-center gap-1 text-xs text-rose-400 bg-rose-500/10 px-2 py-0.5 rounded-full font-medium">
            <XCircle className="w-3 h-3" /> Failed
          </span>
        );
      case "running":
        return (
          <span className="flex items-center gap-1 text-xs text-purple-400 bg-purple-500/10 px-2 py-0.5 rounded-full font-medium animate-pulse">
            <Activity className="w-3 h-3 animate-spin" /> Running
          </span>
        );
      default:
        return (
          <span className="flex items-center gap-1 text-xs text-gray-400 bg-gray-500/10 px-2 py-0.5 rounded-full font-medium">
            <HelpCircle className="w-3 h-3" /> Unknown
          </span>
        );
    }
  };

  const formatTimestamp = (iso: string) => {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };

  // Filter sessions
  const filteredSessions = sessions.filter((s) =>
    s.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex h-screen overflow-hidden text-gray-200">
      {/* Sidebar Session List */}
      <aside className="w-80 border-r border-border bg-card flex flex-col flex-shrink-0">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-purple-600 flex items-center justify-center font-bold text-lg text-white">
              A
            </div>
            <div>
              <h1 className="font-bold text-sm leading-none text-white">AgentScope</h1>
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold">
                Observability
              </span>
            </div>
          </div>
          <button
            onClick={fetchSessionsList}
            className="p-1.5 hover:bg-secondary rounded-lg transition-colors text-muted-foreground hover:text-white"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>

        {/* Search */}
        <div className="p-3 border-b border-border">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-2.5 top-2.5 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search sessions..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-secondary/60 text-xs pl-8 pr-3 py-2 rounded-lg border border-border focus:outline-none focus:border-purple-500/50"
            />
          </div>
        </div>

        {/* Session Card List */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {filteredSessions.map((session) => {
            const isActive = activeSession?.session_id === session.session_id;
            return (
              <div
                key={session.session_id}
                onClick={() => handleSelectSession(session)}
                className={`p-3 rounded-xl border transition-all cursor-pointer ${
                  isActive
                    ? "bg-purple-600/10 border-purple-500/60 shadow-lg shadow-purple-950/20"
                    : "bg-secondary/20 border-border hover:bg-secondary/40"
                }`}
              >
                <div className="flex items-start justify-between gap-2 mb-1">
                  <h3 className="font-bold text-xs text-white truncate max-w-[140px]">
                    {session.name}
                  </h3>
                  {getStatusBadge(session.status)}
                </div>
                <p className="text-[10px] text-muted-foreground font-mono mb-2 truncate">
                  ID: {session.session_id}
                </p>
                <div className="grid grid-cols-2 gap-1 text-[10px] text-muted-foreground border-t border-border/50 pt-2 font-mono">
                  <div>
                    Tokens: <span className="text-white font-bold">{session.total_tokens}</span>
                  </div>
                  <div>
                    Cost:{" "}
                    <span className="text-emerald-400 font-bold">
                      ${session.total_cost_usd.toFixed(5)}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </aside>

      {/* Main Panel */}
      <main className="flex-1 flex flex-col overflow-hidden bg-background">
        {activeSession ? (
          <>
            {/* Top Stats Banner */}
            <header className="p-4 border-b border-border bg-card/60 flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold text-white mb-0.5">{activeSession.name}</h2>
                <p className="text-xs text-muted-foreground font-mono">
                  Session ID: {activeSession.session_id}
                </p>
              </div>
              <div className="flex items-center gap-3">
                {getStatusBadge(activeSession.status)}
              </div>
            </header>

            {/* Metrics cards */}
            <div className="p-4 grid grid-cols-5 gap-4">
              <div className="p-4 rounded-xl glass-panel flex items-center gap-3">
                <div className="p-2.5 rounded-lg bg-purple-500/10 text-purple-400">
                  <Cpu className="w-5 h-5" />
                </div>
                <div>
                  <div className="text-[10px] text-muted-foreground uppercase font-bold tracking-wider">
                    Total Tokens
                  </div>
                  <div className="text-lg font-extrabold text-white leading-none mt-1">
                    {statsData?.total_tokens ?? activeSession.total_tokens}
                  </div>
                </div>
              </div>

              <div className="p-4 rounded-xl glass-panel flex items-center gap-3">
                <div className="p-2.5 rounded-lg bg-emerald-500/10 text-emerald-400">
                  <DollarSign className="w-5 h-5" />
                </div>
                <div>
                  <div className="text-[10px] text-muted-foreground uppercase font-bold tracking-wider">
                    Total Cost (USD)
                  </div>
                  <div className="text-lg font-extrabold text-emerald-400 leading-none mt-1">
                    ${(statsData?.total_cost_usd ?? activeSession.total_cost_usd).toFixed(5)}
                  </div>
                </div>
              </div>

              <div className="p-4 rounded-xl glass-panel flex items-center gap-3">
                <div className="p-2.5 rounded-lg bg-sky-500/10 text-sky-400">
                  <Clock className="w-5 h-5" />
                </div>
                <div>
                  <div className="text-[10px] text-muted-foreground uppercase font-bold tracking-wider">
                    Duration (s)
                  </div>
                  <div className="text-lg font-extrabold text-white leading-none mt-1">
                    {statsData?.total_duration_ms
                      ? (statsData.total_duration_ms / 1000).toFixed(2)
                      : "0.00"}
                  </div>
                </div>
              </div>

              <div className="p-4 rounded-xl glass-panel flex items-center gap-3">
                <div className="p-2.5 rounded-lg bg-rose-500/10 text-rose-400">
                  <AlertTriangle className="w-5 h-5" />
                </div>
                <div>
                  <div className="text-[10px] text-muted-foreground uppercase font-bold tracking-wider">
                    Errors
                  </div>
                  <div className="text-lg font-extrabold text-rose-400 leading-none mt-1">
                    {statsData?.error_count ?? activeSession.error_count}
                  </div>
                </div>
              </div>

              <div className="p-4 rounded-xl glass-panel flex items-center gap-3">
                <div className="p-2.5 rounded-lg bg-amber-500/10 text-amber-400">
                  <Layers className="w-5 h-5" />
                </div>
                <div>
                  <div className="text-[10px] text-muted-foreground uppercase font-bold tracking-wider">
                    Active Agents
                  </div>
                  <div className="text-lg font-extrabold text-white leading-none mt-1">
                    {statsData?.agents?.length ?? activeSession.agent_count}
                  </div>
                </div>
              </div>
            </div>

            {/* Split Screen Workspace */}
            <div className="flex-1 flex overflow-hidden p-4 pt-0 gap-4">
              {/* Chronological Event Feed */}
              <section className="flex-1 flex flex-col overflow-hidden glass-panel rounded-2xl border border-border">
                <div className="p-4 border-b border-border bg-card/40 flex items-center justify-between">
                  <h3 className="font-bold text-xs uppercase tracking-wider text-white">
                    Live Execution Feed
                  </h3>
                  <span className="text-[10px] text-muted-foreground font-mono">
                    {events.length} Events Received
                  </span>
                </div>

                <div className="flex-1 overflow-y-auto p-4 space-y-3">
                  {events.map((event) => {
                    const isExpanded = !!expandedEvents[event.event_id];
                    return (
                      <div
                        key={event.event_id}
                        className="border border-border/80 bg-secondary/10 rounded-xl overflow-hidden"
                      >
                        <div
                          onClick={() => toggleExpandEvent(event.event_id)}
                          className="p-3 flex items-center justify-between cursor-pointer hover:bg-secondary/20 transition-colors"
                        >
                          <div className="flex items-center gap-3">
                            <div className="p-1.5 rounded-lg bg-secondary">
                              {getEventIcon(event.event_type)}
                            </div>
                            <div>
                              <div className="flex items-center gap-2">
                                <span className="font-bold text-xs text-white">
                                  {event.agent_name || "System"}
                                </span>
                                <span className="text-[10px] text-muted-foreground font-mono bg-secondary px-1.5 py-0.5 rounded">
                                  {event.event_type}
                                </span>
                              </div>
                              <span className="text-[10px] text-muted-foreground font-mono">
                                {formatTimestamp(event.timestamp)}
                              </span>
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            {getStatusBadge(event.status)}
                            {isExpanded ? (
                              <ChevronUp className="w-4 h-4 text-muted-foreground" />
                            ) : (
                              <ChevronDown className="w-4 h-4 text-muted-foreground" />
                            )}
                          </div>
                        </div>

                        {/* Expandable Details Drawer */}
                        {isExpanded && (
                          <div className="border-t border-border/50 bg-secondary/5 p-3 text-xs space-y-3 font-mono">
                            {event.payload && (
                              <div className="space-y-2">
                                {Object.entries(event.payload).map(([k, v]) => {
                                  if (v === null || v === undefined) return null;
                                  return (
                                    <div key={k} className="grid grid-cols-4 gap-2">
                                      <span className="text-muted-foreground font-bold">{k}:</span>
                                      <span className="col-span-3 text-white break-all whitespace-pre-wrap">
                                        {typeof v === "object" ? JSON.stringify(v, null, 2) : String(v)}
                                      </span>
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                  <div ref={eventFeedEndRef} />
                </div>
              </section>

              {/* Agent Call Graph Visualization */}
              <section className="w-[450px] flex flex-col overflow-hidden glass-panel rounded-2xl border border-border">
                <div className="p-4 border-b border-border bg-card/40 flex items-center justify-between">
                  <h3 className="font-bold text-xs uppercase tracking-wider text-white">
                    Agent Call Hierarchy
                  </h3>
                </div>

                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                  {graphData && graphData.nodes?.length > 0 ? (
                    graphData.nodes.map((node) => {
                      return (
                        <div
                          key={node.id}
                          className={`p-3 rounded-xl border flex items-center justify-between ${
                            node.data.status === "error"
                              ? "bg-rose-500/10 border-rose-500/30"
                              : node.data.status === "running"
                              ? "bg-purple-500/10 border-purple-500/30"
                              : "bg-secondary/20 border-border"
                          }`}
                        >
                          <div className="flex items-center gap-3">
                            <div className="w-2.5 h-2.5 rounded-full bg-purple-500" />
                            <div>
                              <div className="text-xs font-bold text-white">{node.data.agentName}</div>
                              <div className="text-[10px] text-muted-foreground font-mono">
                                Type: {node.data.eventType}
                              </div>
                            </div>
                          </div>
                          <div className="text-right text-[10px] font-mono">
                            <div className="text-white">
                              {node.data.durationMs ? `${(node.data.durationMs / 1000).toFixed(2)}s` : "0.00s"}
                            </div>
                            <div className="text-muted-foreground">
                              {node.data.tokenCount ? `${node.data.tokenCount} tokens` : ""}
                            </div>
                          </div>
                        </div>
                      );
                    })
                  ) : (
                    <div className="h-full flex flex-col items-center justify-center text-muted-foreground p-8 text-center">
                      <Layers className="w-12 h-12 text-muted-foreground/30 mb-2" />
                      <p className="text-xs">No graph nodes generated for this session yet.</p>
                    </div>
                  )}
                </div>
              </section>
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground text-center p-8">
            <Activity className="w-16 h-16 text-muted-foreground/20 mb-4 animate-pulse" />
            <h2 className="text-lg font-bold text-white mb-1">No Active Session Selected</h2>
            <p className="text-xs max-w-xs">
              Select an execution session from the left sidebar list or launch an agent pipeline to start streaming telemetry.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
