"use client";

import React, { useEffect, useState } from "react";
import { KeyRound } from "lucide-react";
import { getApiKey, setApiKey, UNAUTHORIZED_EVENT } from "../lib/api";

/**
 * Shown when the AgentScope server rejects the dashboard's credentials
 * (HTTP 401 or WebSocket close 4401). Lets the user enter an API key, which
 * is stored in this browser's localStorage, then reloads the dashboard.
 */
export function AuthBanner() {
  const [visible, setVisible] = useState(false);
  const [value, setValue] = useState("");
  const [hadKey, setHadKey] = useState(false);

  useEffect(() => {
    const onUnauthorized = () => {
      setHadKey(Boolean(getApiKey()));
      setVisible(true);
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  if (!visible) return null;

  const save = (e: React.FormEvent) => {
    e.preventDefault();
    const key = value.trim();
    if (!key) return;
    setApiKey(key);
    window.location.reload();
  };

  return (
    <div
      role="alert"
      className="fixed top-0 inset-x-0 z-50 border-b border-amber-500/40 bg-amber-950/95 px-4 py-3 text-amber-100 shadow-lg"
    >
      <form
        onSubmit={save}
        className="mx-auto flex max-w-4xl flex-wrap items-center gap-3 text-sm"
      >
        <KeyRound className="h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
        <span className="flex-1 min-w-[16rem]">
          {hadKey
            ? "The AgentScope server rejected the saved API key."
            : "This AgentScope server requires an API key."}{" "}
          It is stored only in this browser.
        </span>
        <label htmlFor="agentscope-api-key" className="sr-only">
          API key
        </label>
        <input
          id="agentscope-api-key"
          type="password"
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="API key"
          className="w-56 rounded-md border border-amber-500/40 bg-black/40 px-2.5 py-1.5 text-amber-50 placeholder:text-amber-200/50 focus:outline-hidden focus:ring-2 focus:ring-amber-400"
        />
        <button
          type="submit"
          disabled={!value.trim()}
          className="rounded-md bg-amber-500 px-3 py-1.5 font-semibold text-black hover:bg-amber-400 disabled:opacity-50"
        >
          Save &amp; reload
        </button>
        {hadKey && (
          <button
            type="button"
            onClick={() => {
              setApiKey(null);
              window.location.reload();
            }}
            className="rounded-md border border-amber-500/40 px-3 py-1.5 hover:bg-amber-500/10"
          >
            Clear saved key
          </button>
        )}
      </form>
    </div>
  );
}
