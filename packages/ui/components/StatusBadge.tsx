import React from "react";
import { Activity, CheckCircle, HelpCircle, XCircle } from "lucide-react";

/** Pill for a session status ("running" | "completed" | "failed") or event status. */
export function StatusBadge({ status }: { status: string }) {
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
}
