import React from "react";
import { Activity, Cpu, Database, Layers, Wrench } from "lucide-react";

/** Icon for an event type, coloured by agent kind (chain, LLM, tool, retriever). */
export function EventIcon({ type }: { type: string }) {
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
}
