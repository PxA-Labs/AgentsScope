import React from "react";
import { Layers } from "lucide-react";
import type { GraphResponse } from "../types";

/**
 * "Agent Call Hierarchy": the session's call graph as a list of nodes with
 * their direct children. Updated live from WebSocket graph deltas.
 */
export function AgentGraph({ graph }: { graph: GraphResponse | null }) {
  return (
    <section className="w-[450px] flex flex-col overflow-hidden glass-panel rounded-2xl border border-border">
      <div className="p-4 border-b border-border bg-card/40 flex items-center justify-between">
        <h3 className="font-bold text-xs uppercase tracking-wider text-white">
          Agent Call Hierarchy
        </h3>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {graph && graph.nodes?.length > 0 ? (
          <>
            <div className="text-[10px] text-muted-foreground mb-2">
              {graph.nodes.length} agents, {graph.edges?.length ?? 0} calls
            </div>
            {graph.nodes.map((node) => {
              const childEdges = graph.edges?.filter((e) => e.source === node.id) ?? [];
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
                        const child = graph.nodes.find((n) => n.id === edge.target);
                        if (!child) return null;
                        return (
                          <div
                            key={edge.id}
                            className="flex items-center gap-2 text-[10px] font-mono text-muted-foreground py-1"
                          >
                            <div className="w-1.5 h-1.5 rounded-full bg-purple-400/50" />
                            <span className="text-white">{child.data.agentName}</span>
                            <span className="text-[9px] opacity-60">{child.data.eventType ?? ""}</span>
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
  );
}
