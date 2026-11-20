"use client";

import React, { useState } from "react";
import Link from "next/link";
import { GitCompare, RefreshCw, Search } from "lucide-react";
import { useSessionImport } from "../hooks/useSessionImport";
import type { Session } from "../types";
import { ImportBanner, ImportButton } from "./ExportImportControls";
import { StatusBadge } from "./StatusBadge";

interface SessionListProps {
  sessions: Session[];
  activeSessionId: string | null;
  onSelect: (session: Session) => void;
  onRefresh: () => void;
  onImported: (session: Session) => Promise<void> | void;
}

/** Left sidebar: brand, import / diff / refresh actions, search and session cards. */
export function SessionList({
  sessions,
  activeSessionId,
  onSelect,
  onRefresh,
  onImported,
}: SessionListProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const { fileInputRef, isImporting, importMessage, handleImportFile } =
    useSessionImport(onImported);

  const filteredSessions = sessions.filter((s) =>
    s.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <aside className="w-80 border-r border-border bg-card flex flex-col shrink-0">
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
          <ImportButton
            fileInputRef={fileInputRef}
            isImporting={isImporting}
            onFileChange={handleImportFile}
          />
          <Link
            href="/diff"
            className="p-1.5 hover:bg-secondary rounded-lg transition-colors text-muted-foreground hover:text-white"
            title="Visual Session Diffing"
          >
            <GitCompare className="w-4 h-4 text-purple-400" />
          </Link>
          <button
            onClick={onRefresh}
            className="p-1.5 hover:bg-secondary rounded-lg transition-colors text-muted-foreground hover:text-white"
            title="Refresh Sessions"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Import Notification Banner */}
      <ImportBanner message={importMessage} />

      {/* Search */}
      <div className="p-3 border-b border-border">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-2.5 top-2.5 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search sessions..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-secondary/60 text-xs pl-8 pr-3 py-2 rounded-lg border border-border focus:outline-hidden focus:border-purple-500/50"
          />
        </div>
      </div>

      {/* Session Card List */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {filteredSessions.map((session) => {
          const isActive = activeSessionId === session.session_id;
          return (
            <div
              key={session.session_id}
              onClick={() => onSelect(session)}
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
                <StatusBadge status={session.status} />
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
  );
}
