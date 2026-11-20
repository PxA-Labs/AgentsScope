/**
 * Shared API access for the dashboard: base URLs, optional API-key auth for
 * REST (Authorization: Bearer) and WebSockets (Sec-WebSocket-Protocol).
 *
 * The key is read from localStorage (entered by the user in the dashboard) and
 * falls back to NEXT_PUBLIC_AGENTSCOPE_API_KEY. Note that NEXT_PUBLIC_* values
 * are inlined into the JavaScript bundle at build time, so the env fallback is
 * only appropriate for private deployments.
 */

import type {
  AgentEvent,
  GraphResponse,
  MemoryItem,
  Session,
  StatsResponse,
} from "../types";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8765";
export const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://127.0.0.1:8765";

/** Close code the server uses for rejected WebSocket credentials. */
export const WS_CLOSE_UNAUTHORIZED = 4401;
/** Window event dispatched whenever the server rejects our credentials. */
export const UNAUTHORIZED_EVENT = "agentscope:unauthorized";

const STORAGE_KEY = "agentscope.apiKey";
const WS_SUBPROTOCOL = "agentscope";
const WS_AUTH_PROTOCOL_PREFIX = "agentscope.auth.";

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export function getApiKey(): string | null {
  if (typeof window !== "undefined") {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored) return stored;
    } catch {
      // Storage can be unavailable (private mode, blocked site data).
    }
  }
  return process.env.NEXT_PUBLIC_AGENTSCOPE_API_KEY || null;
}

export function setApiKey(key: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (key) {
      window.localStorage.setItem(STORAGE_KEY, key);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // Ignore storage failures; the key just won't persist.
  }
}

export function notifyUnauthorized(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
}

/** fetch() against the AgentScope API with the API key attached, if any. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const key = getApiKey();
  if (key && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${key}`);
  }
  const res = await fetch(apiUrl(path), { ...init, headers });
  if (res.status === 401) notifyUnauthorized();
  return res;
}

/** RFC 4648 base64url without padding (valid as a WebSocket subprotocol token). */
export function base64UrlEncode(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/**
 * Subprotocols to offer on WebSocket connections. Browsers cannot send an
 * Authorization header on WebSockets, so the key travels as a subprotocol
 * (never in the URL, which would leak into server access logs).
 */
export function wsProtocols(key: string | null = getApiKey()): string[] | undefined {
  if (!key) return undefined;
  return [WS_SUBPROTOCOL, WS_AUTH_PROTOCOL_PREFIX + base64UrlEncode(key)];
}

export function openWebSocket(path: string): WebSocket {
  const url = `${WS_BASE}${path}`;
  const protocols = wsProtocols();
  return protocols ? new WebSocket(url, protocols) : new WebSocket(url);
}

// ---------------------------------------------------------------------------
// Typed REST endpoints
//
// Each helper mirrors how the dashboard has always treated the response:
// read endpoints resolve to `null` on a non-2xx status, network failures
// reject, and 401s are reported through apiFetch (UNAUTHORIZED_EVENT).
// ---------------------------------------------------------------------------

export interface SessionListResponse {
  sessions: Session[];
  total?: number;
  page?: number;
  limit?: number;
}

export interface SessionEventsResponse {
  events: AgentEvent[];
}

export interface MemoriesResponse {
  results?: MemoryItem[];
}

/** Outcome of a call whose error body (`{"detail": ...}`) is shown to the user. */
export type ApiResult<T> = { ok: true; data: T } | { ok: false; detail?: string };

export type ExportFormat = "json" | "csv";

async function getJson<T>(path: string): Promise<T | null> {
  const res = await apiFetch(path);
  if (!res.ok) return null;
  return (await res.json()) as T;
}

/**
 * Parse a JSON response, or its FastAPI error detail. Reading the error body
 * can itself throw (e.g. a non-JSON 502 page); that propagates to the caller.
 */
async function toResult<T>(res: Response): Promise<ApiResult<T>> {
  if (res.ok) return { ok: true, data: (await res.json()) as T };
  const err = (await res.json()) as { detail?: string };
  return { ok: false, detail: err.detail };
}

/** Reads the detail of an error response without consuming the success body. */
async function errorDetail(res: Response): Promise<ApiResult<null>> {
  if (res.ok) return { ok: true, data: null };
  const err = (await res.json()) as { detail?: string };
  return { ok: false, detail: err.detail };
}

const sessionPath = (sessionId: string) => `/api/sessions/${sessionId}`;

export function listSessions(): Promise<SessionListResponse | null> {
  return getJson<SessionListResponse>("/api/sessions");
}

export function getSessionEvents(sessionId: string): Promise<SessionEventsResponse | null> {
  return getJson<SessionEventsResponse>(`${sessionPath(sessionId)}/events`);
}

export function getSessionGraph(sessionId: string): Promise<GraphResponse | null> {
  return getJson<GraphResponse>(`${sessionPath(sessionId)}/graph`);
}

export function getSessionStats(sessionId: string): Promise<StatsResponse | null> {
  return getJson<StatsResponse>(`${sessionPath(sessionId)}/stats`);
}

export async function listMemories(sessionId: string): Promise<ApiResult<MemoriesResponse>> {
  return toResult<MemoriesResponse>(await apiFetch(`${sessionPath(sessionId)}/memories`));
}

export async function searchMemories(
  sessionId: string,
  query: string
): Promise<ApiResult<MemoriesResponse>> {
  const res = await apiFetch(`${sessionPath(sessionId)}/memories/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  return toResult<MemoriesResponse>(res);
}

export async function addMemory(
  sessionId: string,
  payload: { text: string; categories?: string[] }
): Promise<ApiResult<null>> {
  const res = await apiFetch(`${sessionPath(sessionId)}/memories`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return errorDetail(res);
}

export async function deleteMemory(sessionId: string, memoryId: string): Promise<ApiResult<null>> {
  const res = await apiFetch(`${sessionPath(sessionId)}/memories/${memoryId}`, {
    method: "DELETE",
  });
  return errorDetail(res);
}

/** Extracts `filename="..."` from a Content-Disposition header, if present. */
export function filenameFromContentDisposition(header: string | null): string | undefined {
  return header?.match(/filename="([^"]+)"/)?.[1];
}

/**
 * Download name for an export: the server's filename when it sends one (CSV
 * does), otherwise `<sanitised session name>_<first 8 id chars>.<format>`.
 */
export function exportFilename(
  session: Pick<Session, "name" | "session_id">,
  format: ExportFormat,
  serverName?: string
): string {
  const safeName = (session.name || "session").replace(/[^a-zA-Z0-9_-]/g, "_");
  return serverName || `${safeName}_${session.session_id.slice(0, 8)}.${format}`;
}

/**
 * Fetch a session export. JSON is pretty-printed for readability; CSV is kept
 * byte-for-byte (it already carries a UTF-8 BOM so spreadsheets detect the
 * encoding). Rejects on a non-2xx status.
 */
export async function exportSession(
  session: Pick<Session, "name" | "session_id">,
  format: ExportFormat
): Promise<{ blob: Blob; filename: string }> {
  const res = await apiFetch(`${sessionPath(session.session_id)}/export?format=${format}`);
  if (!res.ok) throw new Error("Failed to export session");
  const blob =
    format === "json"
      ? new Blob([JSON.stringify(await res.json(), null, 2)], { type: "application/json" })
      : new Blob([await res.arrayBuffer()], { type: "text/csv;charset=utf-8" });
  const serverName = filenameFromContentDisposition(res.headers.get("Content-Disposition"));
  return { blob, filename: exportFilename(session, format, serverName) };
}

/** Save a Blob through a temporary object URL and <a download>. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * Validate and import a session export (the JSON produced by exportSession).
 * Rejects with a user-facing message on bad input or a server error.
 */
export async function importSession(fileText: string): Promise<Session> {
  let payload: { session?: unknown; events?: unknown };
  try {
    payload = JSON.parse(fileText);
  } catch {
    throw new Error("Invalid JSON file format");
  }

  if (!payload.session || !Array.isArray(payload.events)) {
    throw new Error("Invalid session export structure: missing session or events");
  }

  const res = await apiFetch("/api/sessions/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const err = (await res.json()) as { detail?: string };
    throw new Error(err.detail || "Failed to import session");
  }

  return (await res.json()) as Session;
}
