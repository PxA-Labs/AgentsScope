/**
 * Shared API access for the dashboard: base URLs, optional API-key auth for
 * REST (Authorization: Bearer) and WebSockets (Sec-WebSocket-Protocol).
 *
 * The key is read from localStorage (entered by the user in the dashboard) and
 * falls back to NEXT_PUBLIC_AGENTSCOPE_API_KEY. Note that NEXT_PUBLIC_* values
 * are inlined into the JavaScript bundle at build time, so the env fallback is
 * only appropriate for private deployments.
 */

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
