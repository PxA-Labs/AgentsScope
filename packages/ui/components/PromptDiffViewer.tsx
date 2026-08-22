"use client";

import React, { useState, useMemo, useCallback, useEffect, useRef } from "react";
import ReactDiffViewer, { DiffMethod } from "react-diff-viewer-continued";
import { AgentEvent, LLMPayload } from "../types";
import {
  GitCompareArrows,
  ChevronDown,
  X,
  Columns2,
  Rows2,
} from "lucide-react";

interface PromptDiffViewerProps {
  currentEvent: AgentEvent;
  allEvents: AgentEvent[];
}

/**
 * Safely extract the joined prompt text from an LLM event's payload.
 * Handles cases where prompts may be missing, empty, or not an array.
 */
function getPromptText(event: AgentEvent): string {
  if (!event) return "";
  const payload = event.payload as LLMPayload | undefined;
  if (!payload) return "";

  // 1. Check if prompts is a single string
  if (typeof (payload as any).prompts === "string" && (payload as any).prompts.trim()) {
    return (payload as any).prompts;
  }
  // 2. Check if prompt is a single string (singular 'prompt')
  if (typeof (payload as any).prompt === "string" && (payload as any).prompt.trim()) {
    return (payload as any).prompt;
  }

  // 3. Standard array handling
  const prompts = payload.prompts;
  if (!prompts || !Array.isArray(prompts) || prompts.length === 0) return "";
  return prompts.map((p) => String(p)).join("\n\n--- prompt separator ---\n\n");
}

/**
 * Check if an event is an LLM event that has non-empty prompts.
 */
function isLLMEventWithPrompts(event: AgentEvent): boolean {
  if (!event || event.agent_type !== "llm") return false;
  const payload = event.payload as LLMPayload | undefined;
  if (!payload) return false;
  
  if (typeof (payload as any).prompts === "string" && (payload as any).prompts.trim()) {
    return true;
  }
  if (typeof (payload as any).prompt === "string" && (payload as any).prompt.trim()) {
    return true;
  }

  const prompts = payload.prompts;
  return Array.isArray(prompts) && prompts.length > 0;
}

/** Format a timestamp string for display in the dropdown */
function formatTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Custom dark theme styles for react-diff-viewer-continued */
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
    padding: "4px 8px",
    fontSize: "12px",
    lineHeight: "1.6",
    fontFamily: "ui-monospace, monospace",
  },
  gutter: {
    padding: "4px 10px",
    fontSize: "11px",
    minWidth: "36px",
  },
  contentText: {
    fontFamily: "ui-monospace, monospace",
    fontSize: "12px",
  },
};

/**
 * PromptDiffViewer — renders inside the expanded LLM event drawer.
 * Allows the user to pick another LLM event from the same session and
 * shows a side-by-side or unified diff of the two prompts.
 *
 * All comparison state is local — nothing is added to the Zustand store.
 */
export function PromptDiffViewer({
  currentEvent,
  allEvents,
}: PromptDiffViewerProps) {
  const [showDropdown, setShowDropdown] = useState(false);
  const [compareEventId, setCompareEventId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"split" | "unified">("split");

  const dropdownRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // Close dropdown on click outside or Escape key
  useEffect(() => {
    if (!showDropdown) return;

    const handleClickOutside = (event: MouseEvent | TouchEvent) => {
      const target = event.target as Node;
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(target) &&
        triggerRef.current &&
        !triggerRef.current.contains(target)
      ) {
        setShowDropdown(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setShowDropdown(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [showDropdown]);

  // Filter to LLM events with prompts, excluding the current event, sorted reverse-chronologically (newest first)
  const comparableEvents = useMemo(() => {
    const events = (allEvents || []).filter((e) => {
      if (!e || e.event_id === currentEvent?.event_id) return false;
      return isLLMEventWithPrompts(e);
    });

    return [...events].sort((a, b) => {
      const timeA = a.timestamp ? new Date(a.timestamp).getTime() : 0;
      const timeB = b.timestamp ? new Date(b.timestamp).getTime() : 0;
      const validA = isNaN(timeA) ? 0 : timeA;
      const validB = isNaN(timeB) ? 0 : timeB;
      return validB - validA;
    });
  }, [allEvents, currentEvent?.event_id]);

  const compareEvent = useMemo(() => {
    if (!compareEventId) return null;
    return comparableEvents.find((e) => e.event_id === compareEventId) || null;
  }, [compareEventId, comparableEvents]);

  const currentPromptText = useMemo(
    () => (currentEvent ? getPromptText(currentEvent) : ""),
    [currentEvent]
  );
  const comparePromptText = useMemo(
    () => (compareEvent ? getPromptText(compareEvent) : ""),
    [compareEvent]
  );
  const isDiffVisible = compareEventId !== null && compareEvent !== null;

  const handleSelectEvent = useCallback((eventId: string) => {
    setCompareEventId(eventId);
    setShowDropdown(false);
  }, []);

  const handleClose = useCallback(() => {
    setCompareEventId(null);
    setShowDropdown(false);
  }, []);

  // If there are no other LLM events to compare with, show disabled state
  if (comparableEvents.length === 0) {
    return (
      <div className="mt-3 border-t border-border/50 pt-3">
        <button
          disabled
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold
                     bg-secondary/20 text-muted-foreground border border-border
                     cursor-not-allowed opacity-50"
          title="No other LLM events with prompts available in this session"
        >
          <GitCompareArrows className="w-3.5 h-3.5" />
          Compare Prompt
          <span className="text-[10px] font-normal ml-1">(no other LLM events)</span>
        </button>
      </div>
    );
  }

  return (
    <div className="mt-3 border-t border-border/50 pt-3">
      {/* Compare Prompt Button + Close */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          ref={triggerRef}
          id="compare-prompt-btn"
          type="button"
          aria-expanded={showDropdown}
          aria-haspopup="listbox"
          aria-controls="prompt-compare-dropdown"
          onClick={() => setShowDropdown(!showDropdown)}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold transition-all duration-200 ${
            showDropdown
              ? "bg-purple-600 text-white shadow-md shadow-purple-950/30 border border-purple-400/50"
              : isDiffVisible
              ? "bg-purple-600/20 text-purple-200 border border-purple-500/40 hover:bg-purple-600/30"
              : "bg-purple-600/15 text-purple-300 border border-purple-500/30 hover:bg-purple-600/25 hover:border-purple-500/50"
          }`}
        >
          <GitCompareArrows className="w-3.5 h-3.5" />
          {isDiffVisible ? "Change Comparison" : "Compare Prompt"}
          <ChevronDown
            className={`w-3.5 h-3.5 transition-transform duration-200 ${
              showDropdown ? "rotate-180" : ""
            }`}
          />
        </button>

        {/* Close button — visible only when diff is active */}
        {isDiffVisible && (
          <button
            type="button"
            onClick={handleClose}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                       text-rose-300 bg-rose-500/10 border border-rose-500/20 hover:bg-rose-500/20
                       transition-colors"
            title="Close diff comparison"
          >
            <X className="w-3.5 h-3.5" />
            Close Diff
          </button>
        )}
      </div>

      {/* In-flow Selection Panel: never clipped by overflow-hidden */}
      {showDropdown && (
        <div
          ref={dropdownRef}
          id="prompt-compare-dropdown"
          role="listbox"
          aria-label="Select prompt to compare with"
          className="mt-3 rounded-xl border border-purple-500/30 bg-[#0d0d16] p-2.5 shadow-xl"
        >
          <div className="px-2 py-1.5 flex items-center justify-between border-b border-border/60 mb-2">
            <span className="text-[11px] font-bold text-purple-300 uppercase tracking-wider flex items-center gap-1.5">
              <GitCompareArrows className="w-3 h-3" /> Select Prompt to Compare With:
            </span>
            <span className="text-[10px] text-muted-foreground font-mono">
              {comparableEvents.length} other LLM {comparableEvents.length === 1 ? "event" : "events"} available
            </span>
          </div>

          <div className="max-h-56 overflow-y-auto space-y-1.5 pr-1">
            {comparableEvents.map((e) => {
              const payload = e.payload as LLMPayload;
              const isSelected = e.event_id === compareEventId;
              const promptPreview = getPromptText(e);
              const previewSnippet =
                promptPreview.length > 90
                  ? promptPreview.substring(0, 90) + "..."
                  : promptPreview;

              return (
                <button
                  key={e.event_id}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => handleSelectEvent(e.event_id)}
                  className={`w-full text-left p-2.5 rounded-lg text-xs transition-all border ${
                    isSelected
                      ? "bg-purple-600/25 text-white border-purple-500/60 shadow-sm"
                      : "bg-secondary/20 hover:bg-secondary/50 text-gray-200 border-border/60 hover:border-border"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-white text-xs">
                        {e.agent_name || "LLM"}
                      </span>
                      <span className="text-[10px] text-purple-300 font-mono bg-purple-950/60 border border-purple-500/30 px-1.5 py-0.5 rounded">
                        {e.event_type}
                      </span>
                      {payload?.model && (
                        <span className="text-[10px] text-sky-400 font-mono">
                          {payload.model}
                        </span>
                      )}
                    </div>
                    <span className="text-[10px] text-muted-foreground font-mono flex-shrink-0">
                      {formatTime(e.timestamp)}
                    </span>
                  </div>

                  {previewSnippet && (
                    <p className="text-[11px] text-muted-foreground font-mono line-clamp-2 text-left opacity-80 pl-1 border-l border-purple-500/30">
                      {previewSnippet}
                    </p>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Diff Viewer Panel */}
      {isDiffVisible && (
        <div className="mt-3 rounded-xl border border-border overflow-hidden bg-[#0a0a10]">
          {/* Diff Header with labels and view mode toggle */}
          <div className="p-3 border-b border-border/50 bg-card/40 flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-3">
              <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">
                Prompt Diff
              </span>
              <span className="text-[10px] text-muted-foreground font-mono">
                <span className="text-rose-400">
                  {compareEvent!.agent_name || "LLM"} @{" "}
                  {formatTime(compareEvent!.timestamp)}
                </span>
                {" → "}
                <span className="text-emerald-400">
                  {currentEvent.agent_name || "LLM"} @{" "}
                  {formatTime(currentEvent.timestamp)}
                </span>
              </span>
            </div>
            <div className="flex items-center gap-2">
              {/* View Mode Toggle */}
              <div className="flex bg-secondary/60 p-0.5 rounded-lg border border-border">
                <button
                  onClick={() => setViewMode("split")}
                  className={`px-2 py-1 rounded-md text-[10px] font-bold transition-all flex items-center gap-1 ${
                    viewMode === "split"
                      ? "bg-purple-600 text-white shadow-sm"
                      : "text-muted-foreground hover:text-white"
                  }`}
                >
                  <Columns2 className="w-3 h-3" />
                  Side-by-side
                </button>
                <button
                  onClick={() => setViewMode("unified")}
                  className={`px-2 py-1 rounded-md text-[10px] font-bold transition-all flex items-center gap-1 ${
                    viewMode === "unified"
                      ? "bg-purple-600 text-white shadow-sm"
                      : "text-muted-foreground hover:text-white"
                  }`}
                >
                  <Rows2 className="w-3 h-3" />
                  Unified
                </button>
              </div>
            </div>
          </div>

          {/* Diff Content */}
          <div className="prompt-diff-viewer overflow-x-auto max-h-[400px] overflow-y-auto">
            <ReactDiffViewer
              oldValue={comparePromptText}
              newValue={currentPromptText}
              splitView={viewMode === "split"}
              useDarkTheme={true}
              compareMethod={DiffMethod.WORDS}
              styles={diffStyles}
              leftTitle={`${compareEvent!.agent_name || "LLM"} — ${formatTime(
                compareEvent!.timestamp
              )}`}
              rightTitle={`${
                currentEvent.agent_name || "LLM"
              } — ${formatTime(currentEvent.timestamp)}`}
            />
          </div>
        </div>
      )}
    </div>
  );
}
