import React from "react";
import Link from "next/link";
import { Brain, GitCompare } from "lucide-react";
import type { WsStatus } from "../hooks/useLiveEvents";
import type { Session } from "../types";
import { ConnectionStatus } from "./ConnectionStatus";
import { ExportControls } from "./ExportImportControls";
import { StatusBadge } from "./StatusBadge";

export type DashboardTab = "execution" | "memories";

interface SessionHeaderProps {
  session: Session;
  wsStatus: WsStatus;
  activeTab: DashboardTab;
  onTabChange: (tab: DashboardTab) => void;
}

/** Top bar of the selected session: name, live status, export, compare and tabs. */
export function SessionHeader({ session, wsStatus, activeTab, onTabChange }: SessionHeaderProps) {
  return (
    <header className="p-4 border-b border-border bg-card/60 flex items-center justify-between">
      <div>
        <h2 className="text-base font-bold text-white mb-0.5">{session.name}</h2>
        <p className="text-xs text-muted-foreground font-mono">
          Session ID: {session.session_id}
        </p>
      </div>
      <div className="flex items-center gap-3">
        <ConnectionStatus status={wsStatus} />
        <ExportControls session={session} />
        <Link
          href="/diff"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                     text-purple-300 bg-purple-500/10 border border-purple-500/30 hover:bg-purple-500/20
                     transition-colors"
          title="Compare sessions side-by-side"
        >
          <GitCompare className="w-3.5 h-3.5" />
          Compare
        </Link>
        <div className="flex bg-secondary/60 p-0.5 rounded-lg border border-border">
          <button
            onClick={() => onTabChange("execution")}
            className={`px-3 py-1.5 rounded-md text-xs font-bold transition-all ${
              activeTab === "execution"
                ? "bg-purple-600 text-white shadow-xs"
                : "text-muted-foreground hover:text-white"
            }`}
          >
            Execution Flow
          </button>
          <button
            onClick={() => onTabChange("memories")}
            className={`px-3 py-1.5 rounded-md text-xs font-bold transition-all flex items-center gap-1.5 ${
              activeTab === "memories"
                ? "bg-purple-600 text-white shadow-xs"
                : "text-muted-foreground hover:text-white"
            }`}
          >
            <Brain className="w-3.5 h-3.5" /> Mem0 Memories
          </button>
        </div>
        <StatusBadge status={session.status} />
      </div>
    </header>
  );
}
