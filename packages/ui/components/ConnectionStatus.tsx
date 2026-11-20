import React from "react";
import type { WsStatus } from "../hooks/useLiveEvents";

/** Live WebSocket connection indicator shown in the session header. */
export function ConnectionStatus({ status }: { status: WsStatus }) {
  switch (status) {
    case "connected":
      return (
        <span
          className="flex items-center gap-1.5 text-xs text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1 rounded-full font-medium"
          title="Live WebSocket telemetry connection established"
        >
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
          Live Connected
        </span>
      );
    case "connecting":
      return (
        <span
          className="flex items-center gap-1.5 text-xs text-amber-400 bg-amber-500/10 border border-amber-500/20 px-2.5 py-1 rounded-full font-medium"
          title="Connecting or reconnecting to WebSocket server..."
        >
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500"></span>
          </span>
          Reconnecting...
        </span>
      );
    case "disconnected":
      return (
        <span
          className="flex items-center gap-1.5 text-xs text-rose-400 bg-rose-500/10 border border-rose-500/20 px-2.5 py-1 rounded-full font-medium"
          title="WebSocket connection disconnected or server offline"
        >
          <span className="h-2 w-2 rounded-full bg-rose-500"></span>
          Offline
        </span>
      );
  }
}
