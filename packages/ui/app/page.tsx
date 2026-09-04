"use client";

import React, { useEffect, useState, useRef } from "react";
import { PromptDiffViewer } from "../components/PromptDiffViewer";
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
  Trash2,
  Brain,
  Download,
  Upload,
  Tag,
} from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8765";
const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://127.0.0.1:8765";

function getApiUrl(path: string) {
  return `${API_BASE}${path}`;
}

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
  const [activeTab, setActiveTab] = useState<"execution" | "memories">("execution");
  const [memories, setMemories] = useState<any[]>([]);
  const [memoryQuery, setMemoryQuery] = useState("");
  const [isSearchingMemories, setIsSearchingMemories] = useState(false);
  const [newMemoryText, setNewMemoryText] = useState("");
  const [newMemoryCategories, setNewMemoryCategories] = useState("");
  const [isAddingMemory, setIsAddingMemory] = useState(false);
  const [mem0Error, setMem0Error] = useState<string | null>(null);

  const [isExporting, setIsExporting] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [importMessage, setImportMessage] = useState<{
    text: string;
    type: "success" | "error";
  } | null>(null);
  const [wsStatus, setWsStatus] = useState<"connected" | "connecting" | "disconnected">("connecting");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const eventFeedEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll event feed to bottom
  useEffect(() => {
    eventFeedEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  // Fetch Session list
  const fetchSessionsList = async () => {
    try {
      const res = await fetch(getApiUrl("/api/sessions"));
      if (res.ok) {
        const data = await res.json();
        setSessions(data.sessions);

        // Auto-select first session if none selected
        if (data.sessions.length > 0 && !activeSession) {
          handleSelectSession(data.sessions[0]);
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
        getApiUrl(`/api/sessions/${session.session_id}/events`)
      );
      if (resEvents.ok) {
        const eventsData = await resEvents.json();
        setEvents(eventsData.events);
      }
    } catch (e) {
      console.warn("Failed to fetch session events", e);
    }

    // Fetch graph
    try {
      const resGraph = await fetch(
        getApiUrl(`/api/sessions/${session.session_id}/graph`)
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
        getApiUrl(`/api/sessions/${session.session_id}/stats`)
      );
      if (resStats.ok) {
        const stats = await resStats.json();
        setStatsData(stats);
      }
    } catch (e) {
      console.warn("Failed to fetch session stats", e);
    }
  };

  // WebSocket event stream with exponential backoff
  useEffect(() => {
    if (!activeSession) return;

    let ws: WebSocket | null = null;
    let reconnectTimeout: NodeJS.Timeout | null = null;
    let isCancelled = false;
    let currentDelay = 2000;
    const maxDelay = 30000;

    const connectWS = () => {
      if (isCancelled) return;
      setWsStatus("connecting");
      try {
        ws = new WebSocket(`${WS_BASE}/ws?client_type=ui`);

        ws.onopen = () => {
          if (isCancelled) return;
          setWsStatus("connected");
          currentDelay = 2000; // Reset backoff delay upon successful connection
        };

        ws.onmessage = (event) => {
          if (isCancelled) return;
          try {
            const message = JSON.parse(event.data);
            if (message.type === "event" && message.session_id === activeSession.session_id) {
              addEvent(message.event);
              // Refresh graph & stats when new terminal event lands
              if (message.event.event_type.endsWith("_end") || message.event.event_type.endsWith("_error")) {
                fetchGraphAndStats(activeSession.session_id);
              }
            } else if (message.type === "session_update" && message.session_id === activeSession.session_id) {
              updateSessionMeta(message.session_id, message.session);
            }
          } catch (err) {
            console.error("Error processing websocket payload:", err);
          }
        };

        ws.onerror = (err) => {
          if (isCancelled) return;
          console.warn("WebSocket encountered error:", err);
          setWsStatus("disconnected");
        };

        ws.onclose = () => {
          if (isCancelled) return;
          setWsStatus("connecting");
          const nextDelay = currentDelay;
          currentDelay = Math.min(currentDelay * 2, maxDelay);
          reconnectTimeout = setTimeout(connectWS, nextDelay);
        };
      } catch (err) {
        if (isCancelled) return;
        setWsStatus("disconnected");
        const nextDelay = currentDelay;
        currentDelay = Math.min(currentDelay * 2, maxDelay);
        reconnectTimeout = setTimeout(connectWS, nextDelay);
      }
    };

    connectWS();
    return () => {
      isCancelled = true;
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (ws) ws.close();
    };
  }, [activeSession]);

  const fetchGraphAndStats = async (sessionId: string) => {
    try {
      const resGraph = await fetch(getApiUrl(`/api/sessions/${sessionId}/graph`));
      if (resGraph.ok) setGraphData(await resGraph.json());

      const resStats = await fetch(getApiUrl(`/api/sessions/${sessionId}/stats`));
      if (resStats.ok) setStatsData(await resStats.json());
    } catch (e) {
      console.warn("Refresh stats failed", e);
    }
  };

  const fetchMemories = async () => {
    if (!activeSession) return;
    try {
      setMem0Error(null);
      const res = await fetch(getApiUrl(`/api/sessions/${activeSession.session_id}/memories`));
      if (res.ok) {
        const data = await res.json();
        setMemories(data.results || []);
      } else {
        const errData = await res.json();
        setMem0Error(errData.detail || "Failed to load memories");
      }
    } catch (e) {
      console.warn("Failed to fetch memories", e);
      setMem0Error("Could not connect to memories endpoint.");
    }
  };

  const handleSearchMemories = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!activeSession) return;
    if (!memoryQuery.trim()) {
      fetchMemories();
      return;
    }
    try {
      setIsSearchingMemories(true);
      setMem0Error(null);
      const res = await fetch(
        getApiUrl(`/api/sessions/${activeSession.session_id}/memories/search`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: memoryQuery }),
        }
      );
      if (res.ok) {
        const data = await res.json();
        setMemories(data.results || []);
      } else {
        const errData = await res.json();
        setMem0Error(errData.detail || "Failed to search memories");
      }
    } catch (e) {
      console.warn("Failed to search memories", e);
      setMem0Error("Could not connect to memories search endpoint.");
    } finally {
      setIsSearchingMemories(false);
    }
  };

  const handleAddMemory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeSession || !newMemoryText.trim()) return;
    try {
      setIsAddingMemory(true);
      setMem0Error(null);
      const parsedCategories = newMemoryCategories
        .split(",")
        .map((c) => c.trim())
        .filter(Boolean);
      const payload: { text: string; categories?: string[] } = {
        text: newMemoryText,
      };
      if (parsedCategories.length > 0) {
        payload.categories = parsedCategories;
      }
      const res = await fetch(
        getApiUrl(`/api/sessions/${activeSession.session_id}/memories`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }
      );
      if (res.ok) {
        setNewMemoryText("");
        setNewMemoryCategories("");
        setTimeout(fetchMemories, 1000);
      } else {
        const errData = await res.json();
        setMem0Error(errData.detail || "Failed to add memory");
      }
    } catch (e) {
      console.warn("Failed to add memory", e);
      setMem0Error("Could not connect to memories creation endpoint.");
    } finally {
      setIsAddingMemory(false);
    }
  };

  const handleDeleteMemory = async (memoryId: string) => {
    if (!activeSession) return;
    try {
      const res = await fetch(
        getApiUrl(`/api/sessions/${activeSession.session_id}/memories/${memoryId}`),
        {
          method: "DELETE",
        }
      );
      if (res.ok) {
        setMemories((prev) => prev.filter((m) => m.id !== memoryId));
      } else {
        const errData = await res.json();
        setMem0Error(errData.detail || "Failed to delete memory");
      }
    } catch (e) {
      console.warn("Failed to delete memory", e);
      setMem0Error("Could not connect to memories deletion endpoint.");
    }
  };

  const handleExportSession = async () => {
    if (!activeSession) return;
    try {
      setIsExporting(true);
      const res = await fetch(getApiUrl(`/api/sessions/${activeSession.session_id}/export`));
      if (!res.ok) throw new Error("Failed to export session");
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const safeName = (activeSession.name || "session").replace(/[^a-zA-Z0-9_-]/g, "_");
      link.download = `${safeName}_${activeSession.session_id.slice(0, 8)}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err: any) {
      console.error("Export error:", err);
      alert("Failed to export session telemetry data.");
    } finally {
      setIsExporting(false);
    }
  };

  const handleImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      setIsImporting(true);
      setImportMessage(null);
      const text = await file.text();
      let jsonPayload: any;
      try {
        jsonPayload = JSON.parse(text);
      } catch {
        throw new Error("Invalid JSON file format");
      }

      if (!jsonPayload.session || !Array.isArray(jsonPayload.events)) {
        throw new Error("Invalid session export structure: missing session or events");
      }

      const res = await fetch(getApiUrl("/api/sessions/import"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(jsonPayload),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to import session");
      }

      const importedSession = await res.json();
      await fetchSessionsList();
      handleSelectSession(importedSession);
      setImportMessage({
        text: `Imported "${importedSession.name}" successfully!`,
        type: "success",
      });
      setTimeout(() => setImportMessage(null), 4000);
    } catch (err: any) {
      console.error("Import error:", err);
      setImportMessage({
        text: err.message || "Failed to import session",
        type: "error",
      });
      setTimeout(() => setImportMessage(null), 5000);
    } finally {
      setIsImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  useEffect(() => {
    if (activeTab === "memories" && activeSession) {
      fetchMemories();
    }
  }, [activeTab, activeSession]);

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

  const getWsStatusBadge = (status: "connected" | "connecting" | "disconnected") => {
    switch (status) {
      case "connected":
        return (
          <span
            className="flex items-center gap-1.5 text-xs text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1 rounded-full font-medium"
            title="Live WebSocket telemetry connection established"
          >
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            Live Connected
          </span>
        );
      case "connecting":
        return (
          <span
            className="flex items-center gap-1.5 text-xs text-amber-400 bg-amber-500/10 border border-amber-500/20 px-2.5 py-1 rounded-full font-medium"
            title="Connecting or reconnecting to WebSocket server..."
          >
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500"></span>
            </span>
            Reconnecting...
          </span>
        );
      case "disconnected":
        return (
          <span
            className="flex items-center gap-1.5 text-xs text-rose-400 bg-rose-500/10 border border-rose-500/20 px-2.5 py-1 rounded-full font-medium"
            title="WebSocket connection disconnected or server offline"
          >
            <span className="h-2 w-2 rounded-full bg-rose-500"></span>
            Offline
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
          <div className="flex items-center gap-1">
            <input
              ref={fileInputRef}
              type="file"
              accept=".json,application/json"
              onChange={handleImportFile}
              className="hidden"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isImporting}
              className="p-1.5 hover:bg-secondary rounded-lg transition-colors text-muted-foreground hover:text-white"
              title="Import Session JSON"
            >
              <Upload className={`w-4 h-4 ${isImporting ? "animate-spin text-purple-400" : ""}`} />
            </button>
            <button
              onClick={fetchSessionsList}
              className="p-1.5 hover:bg-secondary rounded-lg transition-colors text-muted-foreground hover:text-white"
              title="Refresh Sessions"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Import Notification Banner */}
        {importMessage && (
          <div
            className={`mx-3 mt-2 px-3 py-2 rounded-lg text-xs font-semibold border ${
              importMessage.type === "success"
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                : "bg-rose-500/10 border-rose-500/30 text-rose-300"
            }`}
          >
            {importMessage.text}
          </div>
        )}

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
                {getWsStatusBadge(wsStatus)}
                <button
                  onClick={handleExportSession}
                  disabled={isExporting}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                             text-purple-300 bg-purple-500/10 border border-purple-500/30 hover:bg-purple-500/20
                             transition-colors disabled:opacity-50"
                  title="Export session and telemetry events as JSON"
                >
                  <Download className={`w-3.5 h-3.5 ${isExporting ? "animate-bounce" : ""}`} />
                  {isExporting ? "Exporting..." : "Export JSON"}
                </button>
                <div className="flex bg-secondary/60 p-0.5 rounded-lg border border-border">
                  <button
                    onClick={() => setActiveTab("execution")}
                    className={`px-3 py-1.5 rounded-md text-xs font-bold transition-all ${
                      activeTab === "execution"
                        ? "bg-purple-600 text-white shadow-sm"
                        : "text-muted-foreground hover:text-white"
                    }`}
                  >
                    Execution Flow
                  </button>
                  <button
                    onClick={() => setActiveTab("memories")}
                    className={`px-3 py-1.5 rounded-md text-xs font-bold transition-all flex items-center gap-1.5 ${
                      activeTab === "memories"
                        ? "bg-purple-600 text-white shadow-sm"
                        : "text-muted-foreground hover:text-white"
                    }`}
                  >
                    <Brain className="w-3.5 h-3.5" /> Mem0 Memories
                  </button>
                </div>
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

            {activeTab === "execution" ? (
              /* Split Screen Workspace */
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

                              {/* Prompt Diff Viewer — only for LLM events */}
                              {event.agent_type === "llm" && (
                                <PromptDiffViewer
                                  currentEvent={event}
                                  allEvents={events}
                                />
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

                  <div className="flex-1 overflow-y-auto p-4 space-y-3">
                    {graphData && graphData.nodes?.length > 0 ? (
                      <>
                        <div className="text-[10px] text-muted-foreground mb-2">
                          {graphData.nodes.length} agents, {graphData.edges?.length ?? 0} calls
                        </div>
                        {graphData.nodes.map((node) => {
                          const childEdges = graphData.edges?.filter(
                            (e) => e.source === node.id
                          ) ?? [];
                          return (
                            <div key={node.id}>
                              <div
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
                              {childEdges.length > 0 && (
                                <div className="ml-6 border-l-2 border-purple-500/20 pl-4 mt-1 space-y-1">
                                  {childEdges.map((edge) => {
                                    const child = graphData.nodes.find(
                                      (n) => n.id === edge.target
                                    );
                                    if (!child) return null;
                                    return (
                                      <div
                                        key={edge.id}
                                        className="flex items-center gap-2 text-[10px] font-mono text-muted-foreground py-1"
                                      >
                                        <div className="w-1.5 h-1.5 rounded-full bg-purple-400/50" />
                                        <span className="text-white">{child.data.agentName}</span>
                                        <span className="text-[9px] opacity-60">
                                          {child.data.eventType ?? ""}
                                        </span>
                                      </div>
                                    );
                                  })}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </>
                    ) : (
                      <div className="h-full flex flex-col items-center justify-center text-muted-foreground p-8 text-center">
                        <Layers className="w-12 h-12 text-muted-foreground/30 mb-2" />
                        <p className="text-xs">No call hierarchy data for this session yet.</p>
                        <p className="text-[10px] mt-1 opacity-60">
                          Run an agent pipeline to populate the call graph.
                        </p>
                      </div>
                    )}
                  </div>
                </section>
              </div>
            ) : (
              /* Memories Workspace */
              <div className="flex-1 flex flex-col overflow-hidden p-4 pt-0 gap-4">
                {/* Search & Add Controls */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 flex-shrink-0">
                  {/* Search Memories */}
                  <form onSubmit={handleSearchMemories} className="glass-panel p-4 rounded-2xl border border-border flex items-center gap-3 bg-card/40">
                    <div className="relative flex-1">
                      <Search className="w-4 h-4 absolute left-3 top-3 text-muted-foreground" />
                      <input
                        type="text"
                        placeholder="Semantic search memories..."
                        value={memoryQuery}
                        onChange={(e) => setMemoryQuery(e.target.value)}
                        className="w-full bg-secondary/40 text-xs pl-9 pr-3 py-2 rounded-xl border border-border focus:outline-none focus:border-purple-500/50 text-white"
                      />
                    </div>
                    <button
                      type="submit"
                      disabled={isSearchingMemories}
                      className="px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 font-bold text-xs text-white transition-all duration-200 disabled:opacity-50"
                    >
                      {isSearchingMemories ? "Searching..." : "Search"}
                    </button>
                    {memoryQuery && (
                      <button
                        type="button"
                        onClick={() => {
                          setMemoryQuery("");
                          fetchMemories();
                        }}
                        className="text-xs text-muted-foreground hover:text-white underline"
                      >
                        Reset
                      </button>
                    )}
                  </form>

                  {/* Add Memory */}
                  <form onSubmit={handleAddMemory} className="glass-panel p-4 rounded-2xl border border-border flex flex-col sm:flex-row items-center gap-3 bg-card/40">
                    <input
                      type="text"
                      placeholder="Add a new custom memory..."
                      value={newMemoryText}
                      onChange={(e) => setNewMemoryText(e.target.value)}
                      className="flex-1 w-full bg-secondary/40 text-xs px-3 py-2 rounded-xl border border-border focus:outline-none focus:border-purple-500/50 text-white"
                    />
                    <input
                      type="text"
                      placeholder="Categories (e.g. preferences, facts)..."
                      value={newMemoryCategories}
                      onChange={(e) => setNewMemoryCategories(e.target.value)}
                      className="w-full sm:w-60 bg-secondary/40 text-xs px-3 py-2 rounded-xl border border-border focus:outline-none focus:border-purple-500/50 text-white"
                    />
                    <button
                      type="submit"
                      disabled={isAddingMemory || !newMemoryText.trim()}
                      className="w-full sm:w-auto px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 font-bold text-xs text-white transition-all duration-200 disabled:opacity-50 whitespace-nowrap"
                    >
                      {isAddingMemory ? "Adding..." : "Add Memory"}
                    </button>
                  </form>
                </div>

                {/* Memories Display Panel */}
                <section className="flex-1 flex flex-col overflow-hidden glass-panel rounded-2xl border border-border">
                  <div className="p-4 border-b border-border bg-card/40 flex items-center justify-between">
                    <h3 className="font-bold text-xs uppercase tracking-wider text-white flex items-center gap-2">
                      <Brain className="w-4 h-4 text-purple-400" /> Extracted Session Memories
                    </h3>
                    <span className="text-[10px] text-muted-foreground font-mono">
                      {memories.length} Memories Stored
                    </span>
                  </div>

                  <div className="flex-1 overflow-y-auto p-4">
                    {mem0Error && (
                      <div className="mb-4 p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-center gap-3">
                        <AlertTriangle className="w-5 h-5 flex-shrink-0" />
                        <div>
                          <p className="font-bold mb-1">Configuration Warning</p>
                          <p>{mem0Error}</p>
                        </div>
                      </div>
                    )}

                    {memories.length > 0 ? (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {memories.map((m) => {
                          const dateStr = m.created_at ? new Date(m.created_at).toLocaleString() : "";
                          const agentName = m.metadata?.agent_name || m.metadata?.agent;
                          return (
                            <div
                              key={m.id}
                              className="p-4 rounded-xl border border-border bg-secondary/10 hover:bg-secondary/20 transition-all duration-200 flex flex-col justify-between gap-3 group relative"
                            >
                              <div className="pr-8">
                                <p className="text-xs font-medium text-white leading-relaxed whitespace-pre-wrap">
                                  {m.memory}
                                </p>
                              </div>
                              <div className="flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground font-mono mt-2 pt-2 border-t border-border/30">
                                {dateStr && (
                                  <span className="bg-secondary px-2 py-0.5 rounded-md">
                                    {dateStr}
                                  </span>
                                )}
                                {agentName && (
                                  <span className="bg-purple-900/30 text-purple-300 border border-purple-500/20 px-2 py-0.5 rounded-md">
                                    Agent: {agentName}
                                  </span>
                                )}
                                {((m.categories && m.categories.length > 0) ||
                                  (m.metadata?.categories && m.metadata.categories.length > 0)) && (
                                  <div className="flex flex-wrap items-center gap-1">
                                    {(m.categories || m.metadata?.categories).map(
                                      (cat: string, idx: number) => (
                                        <span
                                          key={idx}
                                          className="bg-blue-900/30 text-blue-300 border border-blue-500/20 px-2 py-0.5 rounded-md flex items-center gap-1"
                                        >
                                          <Tag className="w-2.5 h-2.5" />
                                          {cat}
                                        </span>
                                      )
                                    )}
                                  </div>
                                )}
                              </div>
                              <button
                                onClick={() => handleDeleteMemory(m.id)}
                                className="absolute top-4 right-4 p-1.5 rounded-lg bg-transparent hover:bg-rose-500/10 text-muted-foreground hover:text-rose-400 opacity-0 group-hover:opacity-100 transition-all duration-200"
                                title="Delete memory"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="h-full flex flex-col items-center justify-center text-muted-foreground p-8 text-center">
                        <Brain className="w-12 h-12 text-muted-foreground/30 mb-2 animate-pulse" />
                        <p className="text-xs font-bold text-white mb-1">No Memories Found</p>
                        <p className="text-[10px] max-w-sm leading-relaxed opacity-60">
                          Memories are automatically extracted from agent LLM conversations in real-time when <code>llm_end</code> events are logged.
                        </p>
                        <p className="text-[10px] max-w-sm mt-1 leading-relaxed opacity-60">
                          You can also inject memories manually using the inputs above.
                        </p>
                      </div>
                    )}
                  </div>
                </section>
              </div>
            )}
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
