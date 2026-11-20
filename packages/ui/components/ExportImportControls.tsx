"use client";

import React, { useState } from "react";
import { Download, Upload } from "lucide-react";
import { downloadBlob, exportSession, type ExportFormat } from "../lib/api";
import type { ImportMessage } from "../hooks/useSessionImport";
import type { Session } from "../types";

/**
 * "Export | JSON | CSV" button group. Downloads use the server's
 * Content-Disposition filename when present (CSV), otherwise a name built
 * from the session (JSON).
 */
export function ExportControls({ session }: { session: Session }) {
  const [isExporting, setIsExporting] = useState(false);

  const handleExport = async (format: ExportFormat) => {
    try {
      setIsExporting(true);
      const { blob, filename } = await exportSession(session, format);
      downloadBlob(blob, filename);
    } catch (err: unknown) {
      console.error("Export error:", err);
      alert(`Failed to export session telemetry data as ${format.toUpperCase()}.`);
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div
      role="group"
      aria-label="Export session"
      className="flex items-center rounded-lg text-xs font-semibold text-purple-300
                 bg-purple-500/10 border border-purple-500/30 overflow-hidden"
    >
      <span className="flex items-center gap-1.5 pl-3 pr-2 py-1.5">
        <Download className={`w-3.5 h-3.5 ${isExporting ? "animate-bounce" : ""}`} />
        {isExporting ? "Exporting..." : "Export"}
      </span>
      <button
        onClick={() => handleExport("json")}
        disabled={isExporting}
        className="px-2.5 py-1.5 border-l border-purple-500/30 hover:bg-purple-500/20
                   transition-colors disabled:opacity-50"
        title="Export session and events as JSON (can be re-imported)"
      >
        JSON
      </button>
      <button
        onClick={() => handleExport("csv")}
        disabled={isExporting}
        className="px-2.5 py-1.5 border-l border-purple-500/30 hover:bg-purple-500/20
                   transition-colors disabled:opacity-50"
        title="Export events as CSV (one row per event, for spreadsheets and pandas)"
      >
        CSV
      </button>
    </div>
  );
}

interface ImportButtonProps {
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  isImporting: boolean;
  onFileChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

/** Sidebar icon button that opens a file picker for a session JSON export. */
export function ImportButton({ fileInputRef, isImporting, onFileChange }: ImportButtonProps) {
  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept=".json,application/json"
        onChange={onFileChange}
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
    </>
  );
}

/** Success / error banner shown below the sidebar header after an import. */
export function ImportBanner({ message }: { message: ImportMessage | null }) {
  if (!message) return null;
  return (
    <div
      className={`mx-3 mt-2 px-3 py-2 rounded-lg text-xs font-semibold border ${
        message.type === "success"
          ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
          : "bg-rose-500/10 border-rose-500/30 text-rose-300"
      }`}
    >
      {message.text}
    </div>
  );
}
