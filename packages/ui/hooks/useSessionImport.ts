"use client";

import React, { useRef, useState } from "react";
import { importSession } from "../lib/api";
import type { Session } from "../types";

export interface ImportMessage {
  text: string;
  type: "success" | "error";
}

/** How long the import result banner stays up. */
export const IMPORT_SUCCESS_MESSAGE_MS = 4000;
export const IMPORT_ERROR_MESSAGE_MS = 5000;

/**
 * Importing a session export (JSON) picked through a hidden file input.
 * `onImported` runs after the server accepts the file, before the success
 * banner is shown.
 */
export function useSessionImport(onImported: (session: Session) => Promise<void> | void) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [importMessage, setImportMessage] = useState<ImportMessage | null>(null);

  const handleImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      setIsImporting(true);
      setImportMessage(null);
      const importedSession = await importSession(await file.text());
      await onImported(importedSession);
      setImportMessage({
        text: `Imported "${importedSession.name}" successfully!`,
        type: "success",
      });
      setTimeout(() => setImportMessage(null), IMPORT_SUCCESS_MESSAGE_MS);
    } catch (err: unknown) {
      console.error("Import error:", err);
      setImportMessage({
        text: (err instanceof Error && err.message) || "Failed to import session",
        type: "error",
      });
      setTimeout(() => setImportMessage(null), IMPORT_ERROR_MESSAGE_MS);
    } finally {
      setIsImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return { fileInputRef, isImporting, importMessage, handleImportFile };
}
