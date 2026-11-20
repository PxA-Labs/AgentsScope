import React from "react";
import type { AgentEvent } from "../types";
import { PromptDiffViewer } from "./PromptDiffViewer";

/**
 * Expanded drawer of an event in the feed: every non-null payload field, plus
 * the prompt diff tool for LLM events.
 */
export function EventInspector({ event, allEvents }: { event: AgentEvent; allEvents: AgentEvent[] }) {
  return (
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
      {event.agent_type === "llm" && <PromptDiffViewer currentEvent={event} allEvents={allEvents} />}
    </div>
  );
}
