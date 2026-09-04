"use client";

import React from "react";
import Link from "next/link";
import { ArrowLeft, GitCompare } from "lucide-react";
import { SessionDiffViewer } from "../../components/SessionDiffViewer";

export default function DiffPage() {
  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">
      {/* Top Navbar */}
      <header className="h-16 border-b border-border bg-card/50 backdrop-blur px-6 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-4">
          <Link
            href="/"
            className="flex items-center gap-2 text-xs font-semibold text-muted-foreground hover:text-white transition-colors duration-200"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Dashboard
          </Link>
          <div className="h-4 w-px bg-border" />
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-purple-500/10 border border-purple-500/20 text-purple-400">
              <GitCompare className="w-4 h-4" />
            </div>
            <span className="text-sm font-bold text-white tracking-wide">
              Session Comparison & Diffing
            </span>
          </div>
        </div>
      </header>

      {/* Main Diff Content */}
      <main className="flex-1 overflow-hidden">
        <SessionDiffViewer />
      </main>
    </div>
  );
}
