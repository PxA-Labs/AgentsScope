import React from "react";
import { act, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectionStatus } from "../../components/ConnectionStatus";
import {
  useLiveEvents,
  WS_INITIAL_RECONNECT_DELAY_MS,
  WS_MAX_RECONNECT_DELAY_MS,
  type WsStatus,
} from "../../hooks/useLiveEvents";
import { UNAUTHORIZED_EVENT } from "../../lib/api";
import { useSessionStore } from "../../store/sessionStore";
import { FakeWebSocket } from "../support/fakeWebSocket";
import { makeEdge, makeEvent, makeGraph, makeNode, makeSession } from "../support/fixtures";

const session = makeSession({ session_id: "s1" });

/** Renders the hook and the real status indicator, as the header does. */
function LiveStatus({ onRefresh }: { onRefresh: (id: string) => void }) {
  const status = useLiveEvents(onRefresh);
  return <ConnectionStatus status={status} />;
}

function statusText(): string {
  return screen.getByTitle(/WebSocket/).textContent ?? "";
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeWebSocket.reset();
  vi.stubGlobal("WebSocket", FakeWebSocket);
  useSessionStore.getState().setActiveSession(session);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useLiveEvents connection lifecycle", () => {
  it("does not connect while no session is active", () => {
    useSessionStore.getState().setActiveSession(null);
    renderHook(() => useLiveEvents(vi.fn()));
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("subscribes to the active session and shows Reconnecting... then Live Connected", () => {
    render(<LiveStatus onRefresh={vi.fn()} />);

    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.latest().url).toBe(
      "ws://127.0.0.1:8765/ws?client_type=ui&session_id=s1"
    );
    expect(statusText()).toBe("Reconnecting...");

    act(() => FakeWebSocket.latest().open());
    expect(statusText()).toBe("Live Connected");
  });

  it("offers the API key as a WebSocket subprotocol, never in the URL", () => {
    window.localStorage.setItem("agentscope.apiKey", "secret-key");
    renderHook(() => useLiveEvents(vi.fn()));

    const ws = FakeWebSocket.latest();
    expect(ws.url).not.toContain("secret-key");
    expect(ws.protocols).toEqual(["agentscope", "agentscope.auth.c2VjcmV0LWtleQ"]);
  });

  it("reconnects with exponential backoff capped at 30s", () => {
    render(<LiveStatus onRefresh={vi.fn()} />);

    const expectedDelays = [2000, 4000, 8000, 16000, 30000, 30000];
    expectedDelays.forEach((delay, attempt) => {
      act(() => FakeWebSocket.latest().serverClose());
      expect(statusText()).toBe("Reconnecting...");
      expect(FakeWebSocket.instances).toHaveLength(attempt + 1);

      act(() => vi.advanceTimersByTime(delay - 1));
      expect(FakeWebSocket.instances).toHaveLength(attempt + 1);

      act(() => vi.advanceTimersByTime(1));
      expect(FakeWebSocket.instances).toHaveLength(attempt + 2);
    });
    expect(WS_INITIAL_RECONNECT_DELAY_MS).toBe(2000);
    expect(WS_MAX_RECONNECT_DELAY_MS).toBe(30000);
  });

  it("resets the backoff after a successful connection", () => {
    renderHook(() => useLiveEvents(vi.fn()));

    act(() => FakeWebSocket.latest().serverClose());
    act(() => vi.advanceTimersByTime(2000));
    act(() => FakeWebSocket.latest().serverClose());
    act(() => vi.advanceTimersByTime(4000));
    expect(FakeWebSocket.instances).toHaveLength(3);

    act(() => FakeWebSocket.latest().open());
    act(() => FakeWebSocket.latest().serverClose());
    act(() => vi.advanceTimersByTime(2000));
    expect(FakeWebSocket.instances).toHaveLength(4);
  });

  it("shows Offline on a socket error", () => {
    render(<LiveStatus onRefresh={vi.fn()} />);
    act(() => FakeWebSocket.latest().open());
    act(() => FakeWebSocket.latest().fail());
    expect(statusText()).toBe("Offline");
  });

  it("goes Offline and retries when the WebSocket constructor throws", () => {
    let calls = 0;
    class ThrowingOnce extends FakeWebSocket {
      constructor(url: string, protocols?: string | string[]) {
        calls += 1;
        if (calls === 1) throw new Error("blocked");
        super(url, protocols);
      }
    }
    vi.stubGlobal("WebSocket", ThrowingOnce);

    render(<LiveStatus onRefresh={vi.fn()} />);
    expect(statusText()).toBe("Offline");
    expect(FakeWebSocket.instances).toHaveLength(0);

    act(() => vi.advanceTimersByTime(2000));
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(statusText()).toBe("Reconnecting...");
  });

  it("stops reconnecting on close code 4401 and reports the rejected credentials", () => {
    const onUnauthorized = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    try {
      render(<LiveStatus onRefresh={vi.fn()} />);
      act(() => FakeWebSocket.latest().serverClose(4401));

      expect(statusText()).toBe("Offline");
      expect(onUnauthorized).toHaveBeenCalledTimes(1);

      act(() => vi.advanceTimersByTime(60_000));
      expect(FakeWebSocket.instances).toHaveLength(1);
    } finally {
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    }
  });

  it("closes the socket and cancels a pending reconnect on unmount", () => {
    const { unmount } = renderHook(() => useLiveEvents(vi.fn()));
    act(() => FakeWebSocket.latest().serverClose());
    act(() => vi.advanceTimersByTime(2000));
    const ws = FakeWebSocket.latest();
    act(() => ws.serverClose());

    unmount();
    expect(ws.closed).toBe(true);
    act(() => vi.advanceTimersByTime(60_000));
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("opens a new socket when another session becomes active", () => {
    renderHook(() => useLiveEvents(vi.fn()));
    const first = FakeWebSocket.latest();

    act(() => useSessionStore.getState().setActiveSession(makeSession({ session_id: "s2" })));

    expect(first.closed).toBe(true);
    expect(FakeWebSocket.latest().url).toContain("session_id=s2");
  });
});

describe("useLiveEvents messages", () => {
  function connect(onRefresh = vi.fn()) {
    renderHook(() => useLiveEvents(onRefresh));
    act(() => FakeWebSocket.latest().open());
    return onRefresh;
  }

  it("appends events of the active session and refreshes graph and stats on terminal events", () => {
    const onRefresh = connect();
    const ws = FakeWebSocket.latest();

    act(() => ws.message({ type: "event", session_id: "s1", event: makeEvent({ event_id: "a", session_id: "s1" }) }));
    expect(useSessionStore.getState().events.map((e) => e.event_id)).toEqual(["a"]);
    expect(onRefresh).not.toHaveBeenCalled();

    act(() =>
      ws.message({
        type: "event",
        session_id: "s1",
        event: makeEvent({ event_id: "a", session_id: "s1", event_type: "llm_end", status: "completed" }),
      })
    );
    expect(useSessionStore.getState().events).toHaveLength(1);
    expect(onRefresh).toHaveBeenCalledWith("s1");

    act(() =>
      ws.message({
        type: "event",
        session_id: "s1",
        event: makeEvent({ event_id: "b", session_id: "s1", event_type: "tool_error", status: "error" }),
      })
    );
    expect(onRefresh).toHaveBeenCalledTimes(2);
  });

  it("ignores messages for other sessions", () => {
    const onRefresh = connect();
    const ws = FakeWebSocket.latest();

    act(() => {
      ws.message({ type: "event", session_id: "s2", event: makeEvent({ session_id: "s2", event_type: "llm_end" }) });
      ws.message({ type: "graph_update", session_id: "s2", node: makeNode("x"), edge: null });
      ws.message({ type: "session_update", session_id: "s2", session: { total_tokens: 7 } });
    });

    const state = useSessionStore.getState();
    expect(state.events).toEqual([]);
    expect(state.graph).toBeNull();
    expect(state.activeSession).toBe(session);
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it("merges live DAG deltas into the graph", () => {
    connect();
    useSessionStore.getState().setGraph(makeGraph([makeNode("p", { position: { x: 10, y: 10 } })]));

    act(() =>
      FakeWebSocket.latest().message({
        type: "graph_update",
        session_id: "s1",
        node: makeNode("c"),
        edge: makeEdge("p", "c"),
      })
    );
    act(() =>
      FakeWebSocket.latest().message({ type: "graph_update", session_id: "s1", node: null, edge: null })
    );

    const { graph } = useSessionStore.getState();
    expect(graph?.nodes.map((n) => n.id)).toEqual(["p", "c"]);
    expect(graph?.nodes[1].position).toEqual({ x: 10, y: 190 });
  });

  it("applies session_update aggregates", () => {
    useSessionStore.getState().setSessions([session]);
    connect();

    act(() =>
      FakeWebSocket.latest().message({
        type: "session_update",
        session_id: "s1",
        session: { total_tokens: 500, status: "completed" },
      })
    );

    const state = useSessionStore.getState();
    expect(state.activeSession).toMatchObject({ total_tokens: 500, status: "completed" });
    expect(state.sessions[0]).toMatchObject({ total_tokens: 500 });
  });

  it("keeps the same socket when session_update replaces the active session object", () => {
    connect();
    const ws = FakeWebSocket.latest();

    act(() => ws.message({ type: "session_update", session_id: "s1", session: { total_tokens: 1 } }));
    act(() => ws.message({ type: "event", session_id: "s1", event: makeEvent({ event_id: "late", session_id: "s1" }) }));

    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(ws.closed).toBe(false);
    expect(useSessionStore.getState().events.map((e) => e.event_id)).toEqual(["late"]);
  });

  it("logs and survives malformed payloads", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    connect();
    act(() => {
      FakeWebSocket.latest().onmessage?.(new MessageEvent("message", { data: "not json" }));
    });
    expect(error).toHaveBeenCalledWith("Error processing websocket payload:", expect.any(SyntaxError));
  });
});

describe("ConnectionStatus", () => {
  it.each<[WsStatus, string, string]>([
    ["connected", "Live Connected", "Live WebSocket telemetry connection established"],
    ["connecting", "Reconnecting...", "Connecting or reconnecting to WebSocket server..."],
    ["disconnected", "Offline", "WebSocket connection disconnected or server offline"],
  ])("renders %s", (status, label, title) => {
    render(<ConnectionStatus status={status} />);
    expect(screen.getByTitle(title)).toHaveTextContent(label);
  });
});
