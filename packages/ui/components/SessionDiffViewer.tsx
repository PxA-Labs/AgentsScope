"use client";

import React, { useState, useEffect, useMemo } from "react";
import ReactDiffViewer, { DiffMethod } from "react-diff-viewer-continued";
import { Session, AgentEvent, LLMPayload } from "../types";
import {
  ArrowRightLeft,
  GitCompare,
  Clock,
  DollarSign,
  AlertTriangle,
  Layers,
  Columns2,
  Rows2,
  CheckCircle,
  XCircle,
  Search,
  RefreshCw,
  Cpu,
  Wrench,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
} from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8765";

function getApiUrl(path: string) {
  return `${API_BASE}${path}`;
}

const diffStyles = {
  variables: {
    dark: {
      diffViewerBackground: "rgba(15, 15, 23, 0.8)",
      diffViewerColor: "#e2e8f0",
      addedBackground: "rgba(34, 197, 94, 0.12)",
      addedColor: "#86efac",
      removedBackground: "rgba(239, 68, 68, 0.12)",
      removedColor: "#fca5a5",
      wordAddedBackground: "rgba(34, 197, 94, 0.25)",
      wordRemovedBackground: "rgba(239, 68, 68, 0.25)",
      addedGutterBackground: "rgba(34, 197, 94, 0.08)",
      removedGutterBackground: "rgba(239, 68, 68, 0.08)",
      gutterBackground: "rgba(15, 15, 23, 0.6)",
      gutterBackgroundDark: "rgba(10, 10, 16, 0.6)",
      highlightBackground: "rgba(147, 51, 234, 0.1)",
      highlightGutterBackground: "rgba(147, 51, 234, 0.15)",
      codeFoldGutterBackground: "rgba(15, 15, 23, 0.4)",
      codeFoldBackground: "rgba(15, 15, 23, 0.4)",
      emptyLineBackground: "rgba(15, 15, 23, 0.3)",
      gutterColor: "#6b7280",
      addedGutterColor: "#86efac",
      removedGutterColor: "#fca5a5",
      codeFoldContentColor: "#9ca3af",
    },
  },
  line: {
    padding: "2px 8px",
    fontSize: "12px",
    lineHeight: "18px",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
  },
};

function extractPrompt(event?: AgentEvent): string {
  if (!event || !event.payload) return "";
  const payload = event.payload as LLMPayload;
  if (Array.isArray(payload.prompts) && payload.prompts.length > 0) {
    return payload.prompts.join("\n\n---\n\n");
  }
  if ((payload as any).prompt) return String((payload as any).prompt);
  return "";
}

function extractCompletion(event?: AgentEvent): string {
  if (!event || !event.payload) return "";
  const payload = event.payload as LLMPayload;
  return payload.completion || "";
}

export function SessionDiffViewer() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sessionAId, setSessionAId] = useState<string>("");
  const [sessionBId, setSessionBId] = useState<string>("");
  const [loadingSessions, setLoadingSessions] = useState(false);

  const [eventsA, setEventsA] = useState<AgentEvent[]>([]);
  const [eventsB, setEventsB] = useState<AgentEvent[]>([]);
  const [loadingEvents, setLoadingEvents] = useState(false);

  const [selectedEventIndex, setSelectedEventIndex] = useState<number | null>(null);
  const [splitView, setSplitView] = useState(true);
  const [diffTarget, setDiffTarget] = useState<"prompt" | "completion">("prompt");

  // Load all sessions
  const fetchSessions = async () => {
    try {
      setLoadingSessions(true);
      const res = await fetch(getApiUrl("/api/sessions"));
      if (res.ok) {
        const data = await res.json();
        const sessList: Session[] = data.sessions || [];
        setSessions(sessList);
        if (sessList.length >= 2) {
          setSessionAId(sessList[1].session_id);
          setSessionBId(sessList[0].session_id);
        } else if (sessList.length === 1) {
          setSessionAId(sessList[0].session_id);
          setSessionBId(sessList[0].session_id);
        }
      }
    } catch (err) {
      console.error("Failed to load sessions:", err);
    } finally {
      setLoadingSessions(false);
    }
  };

  useEffect(() => {
    fetchSessions();
  }, []);

  // Fetch events when session selection changes
  useEffect(() => {
    if (!sessionAId && !sessionBId) return;

    let isMounted = true;
    const loadEvents = async () => {
      setLoadingEvents(true);
      try {
        const [resA, resB] = await Promise.all([
          sessionAId ? fetch(getApiUrl(`/api/sessions/${sessionAId}/events`)) : null,
          sessionBId ? fetch(getApiUrl(`/api/sessions/${sessionBId}/events`)) : null,
        ]);

        if (isMounted) {
          if (resA && resA.ok) {
            const dataA = await resA.json();
            setEventsA(dataA.events || []);
          } else {
            setEventsA([]);
          }

          if (resB && resB.ok) {
            const dataB = await resB.json();
            setEventsB(dataB.events || []);
          } else {
            setEventsB([]);
          }
        }
      } catch (e) {
        console.error("Failed to load session events:", e);
      } finally {
        if (isMounted) setLoadingEvents(false);
      }
    };

    loadEvents();
    return () => {
      isMounted = false;
    };
  }, [sessionAId, sessionBId]);

  const sessionA = useMemo(
    () => sessions.find((s) => s.session_id === sessionAId),
    [sessions, sessionAId]
  );
  const sessionB = useMemo(
    () => sessions.find((s) => s.session_id === sessionBId),
    [sessions, sessionBId]
  );

  const swapSessions = () => {
    const temp = sessionAId;
    setSessionAId(sessionBId);
    setSessionBId(temp);
  };

  // Compute metrics comparison
  const metrics = useMemo(() => {
    const tokensA = sessionA?.total_tokens || 0;
    const tokensB = sessionB?.total_tokens || 0;
    const tokenDiff = tokensB - tokensA;

    const costA = sessionA?.total_cost_usd || 0;
    const costB = sessionB?.total_cost_usd || 0;
    const costDiff = costB - costA;

    const errorsA = sessionA?.error_count || 0;
    const errorsB = sessionB?.error_count || 0;
    const errorDiff = errorsB - errorsA;

    const eventsCountA = eventsA.length;
    const eventsCountB = eventsB.length;
    const eventDiff = eventsCountB - eventsCountA;

    return {
      tokensA,
      tokensB,
      tokenDiff,
      costA,
      costB,
      costDiff,
      errorsA,
      errorsB,
      errorDiff,
      eventsCountA,
      eventsCountB,
      eventDiff,
    };
  }, [sessionA, sessionB, eventsA, eventsB]);

  // Aligned timeline rows (max length of both session event lists)
  const maxEvents = Math.max(eventsA.length, eventsB.length);
  const alignedRows = useMemo(() => {
    const rows = [];
    for (let i = 0; i < maxEvents; i++) {
      rows.push({
        index: i,
        eventA: eventsA[i] || null,
        eventB: eventsB[i] || null,
      });
    }
    return rows;
  }, [eventsA, eventsB, maxEvents]);

  const activeRow = selectedEventIndex !== null ? alignedRows[selectedEventIndex] : null;

  return (
    <div className="flex flex-col h-full gap-4 p-6 overflow-y-auto">
      {/* Top Header Controls */}
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 p-5 rounded-2xl glass-panel border border-border bg-card/40">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400">
            <GitCompare className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base font-bold text-white tracking-wide">
              Visual Session Diffing
            </h2>
            <p className="text-xs text-muted-foreground">
              Compare two session executions side-by-side to analyze tokens, latencies, and prompts
            </p>
          </div>
        </div>

        <button
          onClick={fetchSessions}
          disabled={loadingSessions}
          className="flex items-center gap-2 px-3 py-1.5 rounded-xl border border-border bg-secondary/30 hover:bg-secondary/60 text-xs text-white transition-all duration-200"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loadingSessions ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Session Selectors */}
      <div className="grid grid-cols-1 md:grid-cols-[1fr,auto,1fr] gap-4 items-center">
        {/* Session A */}
        <div className="p-4 rounded-2xl glass-panel border border-border bg-card/30 flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-rose-400 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-rose-500" />
              Baseline (Session A)
            </span>
            {sessionA && (
              <span className="text-[10px] px-2 py-0.5 rounded-full font-mono bg-secondary border border-border text-muted-foreground">
                {sessionA.status}
              </span>
            )}
          </div>
          <select
            value={sessionAId}
            onChange={(e) => setSessionAId(e.target.value)}
            className="w-full bg-secondary/50 border border-border text-xs rounded-xl px-3 py-2 text-white focus:outline-none focus:border-rose-500/50"
          >
            <option value="">Select Session A...</option>
            {sessions.map((s) => (
              <option key={s.session_id} value={s.session_id}>
                {s.name} ({s.session_id.slice(0, 8)}) - {new Date(s.started_at).toLocaleDateString()}
              </option>
            ))}
          </select>
        </div>

        {/* Swap Button */}
        <div className="flex justify-center">
          <button
            onClick={swapSessions}
            title="Swap Sessions A & B"
            className="p-3 rounded-full bg-secondary/60 hover:bg-secondary border border-border text-muted-foreground hover:text-white transition-all duration-200 shadow-lg"
          >
            <ArrowRightLeft className="w-4 h-4" />
          </button>
        </div>

        {/* Session B */}
        <div className="p-4 rounded-2xl glass-panel border border-border bg-card/30 flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-emerald-400 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              Target (Session B)
            </span>
            {sessionB && (
              <span className="text-[10px] px-2 py-0.5 rounded-full font-mono bg-secondary border border-border text-muted-foreground">
                {sessionB.status}
              </span>
            )}
          </div>
          <select
            value={sessionBId}
            onChange={(e) => setSessionBId(e.target.value)}
            className="w-full bg-secondary/50 border border-border text-xs rounded-xl px-3 py-2 text-white focus:outline-none focus:border-emerald-500/50"
          >
            <option value="">Select Session B...</option>
            {sessions.map((s) => (
              <option key={s.session_id} value={s.session_id}>
                {s.name} ({s.session_id.slice(0, 8)}) - {new Date(s.started_at).toLocaleDateString()}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Metrics Delta Overview */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {/* Token Diff */}
        <div className="p-4 rounded-2xl glass-panel border border-border bg-card/40 flex flex-col gap-1">
          <div className="flex items-center justify-between text-muted-foreground text-xs">
            <span className="flex items-center gap-1.5">
              <Cpu className="w-3.5 h-3.5" /> Total Tokens
            </span>
            <span
              className={`flex items-center text-[10px] font-bold px-1.5 py-0.5 rounded ${
                metrics.tokenDiff > 0
                  ? "text-rose-400 bg-rose-500/10"
                  : metrics.tokenDiff < 0
                  ? "text-emerald-400 bg-emerald-500/10"
                  : "text-muted-foreground bg-secondary"
              }`}
            >
              {metrics.tokenDiff > 0 ? (
                <ArrowUpRight className="w-3 h-3" />
              ) : metrics.tokenDiff < 0 ? (
                <ArrowDownRight className="w-3 h-3" />
              ) : (
                <Minus className="w-3 h-3" />
              )}
              {metrics.tokenDiff > 0 ? `+${metrics.tokenDiff}` : metrics.tokenDiff}
            </span>
          </div>
          <div className="flex items-baseline justify-between mt-1">
            <span className="text-xs text-rose-300 font-mono">{metrics.tokensA.toLocaleString()}</span>
            <span className="text-[10px] text-muted-foreground">vs</span>
            <span className="text-xs text-emerald-300 font-mono">{metrics.tokensB.toLocaleString()}</span>
          </div>
        </div>

        {/* Cost Diff */}
        <div className="p-4 rounded-2xl glass-panel border border-border bg-card/40 flex flex-col gap-1">
          <div className="flex items-center justify-between text-muted-foreground text-xs">
            <span className="flex items-center gap-1.5">
              <DollarSign className="w-3.5 h-3.5" /> Total Cost
            </span>
            <span
              className={`flex items-center text-[10px] font-bold px-1.5 py-0.5 rounded ${
                metrics.costDiff > 0
                  ? "text-rose-400 bg-rose-500/10"
                  : metrics.costDiff < 0
                  ? "text-emerald-400 bg-emerald-500/10"
                  : "text-muted-foreground bg-secondary"
              }`}
            >
              {metrics.costDiff > 0 ? (
                <ArrowUpRight className="w-3 h-3" />
              ) : metrics.costDiff < 0 ? (
                <ArrowDownRight className="w-3 h-3" />
              ) : (
                <Minus className="w-3 h-3" />
              )}
              ${Math.abs(metrics.costDiff).toFixed(4)}
            </span>
          </div>
          <div className="flex items-baseline justify-between mt-1">
            <span className="text-xs text-rose-300 font-mono">${metrics.costA.toFixed(4)}</span>
            <span className="text-[10px] text-muted-foreground">vs</span>
            <span className="text-xs text-emerald-300 font-mono">${metrics.costB.toFixed(4)}</span>
          </div>
        </div>

        {/* Error Count Diff */}
        <div className="p-4 rounded-2xl glass-panel border border-border bg-card/40 flex flex-col gap-1">
          <div className="flex items-center justify-between text-muted-foreground text-xs">
            <span className="flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5" /> Errors
            </span>
            <span
              className={`flex items-center text-[10px] font-bold px-1.5 py-0.5 rounded ${
                metrics.errorDiff > 0
                  ? "text-rose-400 bg-rose-500/10"
                  : metrics.errorDiff < 0
                  ? "text-emerald-400 bg-emerald-500/10"
                  : "text-muted-foreground bg-secondary"
              }`}
            >
              {metrics.errorDiff > 0 ? (
                <ArrowUpRight className="w-3 h-3" />
              ) : metrics.errorDiff < 0 ? (
                <ArrowDownRight className="w-3 h-3" />
              ) : (
                <Minus className="w-3 h-3" />
              )}
              {metrics.errorDiff > 0 ? `+${metrics.errorDiff}` : metrics.errorDiff}
            </span>
          </div>
          <div className="flex items-baseline justify-between mt-1">
            <span className="text-xs text-rose-300 font-mono">{metrics.errorsA}</span>
            <span className="text-[10px] text-muted-foreground">vs</span>
            <span className="text-xs text-emerald-300 font-mono">{metrics.errorsB}</span>
          </div>
        </div>

        {/* Total Events Diff */}
        <div className="p-4 rounded-2xl glass-panel border border-border bg-card/40 flex flex-col gap-1">
          <div className="flex items-center justify-between text-muted-foreground text-xs">
            <span className="flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5" /> Total Events
            </span>
            <span
              className={`flex items-center text-[10px] font-bold px-1.5 py-0.5 rounded ${
                metrics.eventDiff > 0
                  ? "text-purple-400 bg-purple-500/10"
                  : metrics.eventDiff < 0
                  ? "text-blue-400 bg-blue-500/10"
                  : "text-muted-foreground bg-secondary"
              }`}
            >
              {metrics.eventDiff > 0 ? (
                <ArrowUpRight className="w-3 h-3" />
              ) : metrics.eventDiff < 0 ? (
                <ArrowDownRight className="w-3 h-3" />
              ) : (
                <Minus className="w-3 h-3" />
              )}
              {metrics.eventDiff > 0 ? `+${metrics.eventDiff}` : metrics.eventDiff}
            </span>
          </div>
          <div className="flex items-baseline justify-between mt-1">
            <span className="text-xs text-rose-300 font-mono">{metrics.eventsCountA}</span>
            <span className="text-[10px] text-muted-foreground">vs</span>
            <span className="text-xs text-emerald-300 font-mono">{metrics.eventsCountB}</span>
          </div>
        </div>
      </div>

      {/* Execution Flow Diff Table */}
      <div className="flex-1 flex flex-col min-h-[350px] glass-panel rounded-2xl border border-border overflow-hidden bg-card/30">
        <div className="p-4 border-b border-border bg-card/50 flex items-center justify-between">
          <h3 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2">
            <Layers className="w-4 h-4 text-purple-400" />
            Execution Flow Alignment
          </h3>
          <span className="text-[10px] text-muted-foreground font-mono">
            {alignedRows.length} Sequence Steps
          </span>
        </div>

        <div className="flex-1 overflow-y-auto">
          {loadingEvents ? (
            <div className="flex items-center justify-center p-12 text-muted-foreground text-xs">
              <RefreshCw className="w-4 h-4 animate-spin mr-2" /> Loading session events...
            </div>
          ) : alignedRows.length === 0 ? (
            <div className="flex items-center justify-center p-12 text-muted-foreground text-xs">
              Select two sessions above to compare execution traces.
            </div>
          ) : (
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-border text-[10px] uppercase text-muted-foreground font-mono bg-secondary/20">
                  <th className="p-3 w-12 text-center">#</th>
                  <th className="p-3 w-[46%] text-rose-400">Session A Event</th>
                  <th className="p-3 w-8 text-center"></th>
                  <th className="p-3 w-[46%] text-emerald-400">Session B Event</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {alignedRows.map((row) => {
                  const evA = row.eventA;
                  const evB = row.eventB;
                  const isSelected = selectedEventIndex === row.index;
                  const hasLLM =
                    (evA && evA.agent_type === "llm") || (evB && evB.agent_type === "llm");

                  return (
                    <tr
                      key={row.index}
                      onClick={() => hasLLM && setSelectedEventIndex(row.index)}
                      className={`transition-colors duration-150 ${
                        hasLLM ? "cursor-pointer hover:bg-secondary/30" : ""
                      } ${isSelected ? "bg-purple-900/20 border-l-2 border-purple-500" : ""}`}
                    >
                      <td className="p-3 text-center text-[10px] font-mono text-muted-foreground">
                        {row.index + 1}
                      </td>

                      {/* Event A */}
                      <td className="p-3">
                        {evA ? (
                          <div className="flex flex-col gap-1">
                            <div className="flex items-center gap-2">
                              <span className="font-semibold text-white">
                                {evA.agent_name || evA.event_type}
                              </span>
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-secondary font-mono text-muted-foreground">
                                {evA.event_type}
                              </span>
                              {evA.status === "error" && (
                                <XCircle className="w-3 h-3 text-rose-400" />
                              )}
                            </div>
                            <div className="flex items-center gap-3 text-[10px] text-muted-foreground font-mono">
                              {evA.latency_ms !== null && <span>{evA.latency_ms}ms</span>}
                              {(evA.payload as LLMPayload)?.model && (
                                <span>{(evA.payload as LLMPayload).model}</span>
                              )}
                              {(evA.payload as LLMPayload)?.total_tokens && (
                                <span>{(evA.payload as LLMPayload).total_tokens} toks</span>
                              )}
                            </div>
                          </div>
                        ) : (
                          <span className="text-[10px] italic text-muted-foreground/40">
                            (No corresponding event)
                          </span>
                        )}
                      </td>

                      {/* Middle indicator */}
                      <td className="p-3 text-center text-muted-foreground text-[10px]">
                        {hasLLM ? (
                          <span className="px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 font-mono">
                            DIFF
                          </span>
                        ) : (
                          <Minus className="w-3 h-3 mx-auto opacity-30" />
                        )}
                      </td>

                      {/* Event B */}
                      <td className="p-3">
                        {evB ? (
                          <div className="flex flex-col gap-1">
                            <div className="flex items-center gap-2">
                              <span className="font-semibold text-white">
                                {evB.agent_name || evB.event_type}
                              </span>
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-secondary font-mono text-muted-foreground">
                                {evB.event_type}
                              </span>
                              {evB.status === "error" && (
                                <XCircle className="w-3 h-3 text-rose-400" />
                              )}
                            </div>
                            <div className="flex items-center gap-3 text-[10px] text-muted-foreground font-mono">
                              {evB.latency_ms !== null && <span>{evB.latency_ms}ms</span>}
                              {(evB.payload as LLMPayload)?.model && (
                                <span>{(evB.payload as LLMPayload).model}</span>
                              )}
                              {(evB.payload as LLMPayload)?.total_tokens && (
                                <span>{(evB.payload as LLMPayload).total_tokens} toks</span>
                              )}
                            </div>
                          </div>
                        ) : (
                          <span className="text-[10px] italic text-muted-foreground/40">
                            (No corresponding event)
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Visual Prompt / Completion Diff Inspector */}
      {activeRow && (
        <div className="glass-panel rounded-2xl border border-border p-5 flex flex-col gap-3 bg-card/40">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
            <div className="flex items-center gap-2">
              <GitCompare className="w-4 h-4 text-purple-400" />
              <span className="text-xs font-bold text-white">
                Step #{activeRow.index + 1} Payload Diff
              </span>
              <div className="flex items-center gap-1 bg-secondary rounded-lg p-0.5 border border-border">
                <button
                  onClick={() => setDiffTarget("prompt")}
                  className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-all ${
                    diffTarget === "prompt"
                      ? "bg-purple-600 text-white"
                      : "text-muted-foreground hover:text-white"
                  }`}
                >
                  Prompt Diff
                </button>
                <button
                  onClick={() => setDiffTarget("completion")}
                  className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-all ${
                    diffTarget === "completion"
                      ? "bg-purple-600 text-white"
                      : "text-muted-foreground hover:text-white"
                  }`}
                >
                  Completion Diff
                </button>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => setSplitView(!splitView)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-border bg-secondary/40 hover:bg-secondary text-xs text-white transition-all"
              >
                {splitView ? <Columns2 className="w-3.5 h-3.5" /> : <Rows2 className="w-3.5 h-3.5" />}
                {splitView ? "Split View" : "Unified View"}
              </button>
              <button
                onClick={() => setSelectedEventIndex(null)}
                className="px-2.5 py-1.5 rounded-xl border border-border bg-secondary/40 hover:bg-secondary text-xs text-muted-foreground hover:text-white"
              >
                Close
              </button>
            </div>
          </div>

          <div className="rounded-xl overflow-hidden border border-border/80 bg-background/50">
            <ReactDiffViewer
              oldValue={
                diffTarget === "prompt"
                  ? extractPrompt(activeRow.eventA || undefined)
                  : extractCompletion(activeRow.eventA || undefined)
              }
              newValue={
                diffTarget === "prompt"
                  ? extractPrompt(activeRow.eventB || undefined)
                  : extractCompletion(activeRow.eventB || undefined)
              }
              splitView={splitView}
              useDarkTheme={true}
              compareMethod={DiffMethod.WORDS}
              styles={diffStyles}
              leftTitle={`Session A (${sessionA?.name || "Baseline"})`}
              rightTitle={`Session B (${sessionB?.name || "Target"})`}
            />
          </div>
        </div>
      )}
    </div>
  );
}
