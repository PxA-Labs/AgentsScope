import { describe, expect, it } from "vitest";
import { mergeGraphUpdate, upsertEvent, useSessionStore } from "../../store/sessionStore";
import { makeEdge, makeEvent, makeGraph, makeNode, makeSession } from "../support/fixtures";

describe("upsertEvent", () => {
  it("appends an event with a new event_id", () => {
    const first = makeEvent({ event_id: "a" });
    const second = makeEvent({ event_id: "b" });
    expect(upsertEvent([first], second)).toEqual([first, second]);
  });

  it("does not mutate the input list", () => {
    const events = [makeEvent({ event_id: "a" })];
    upsertEvent(events, makeEvent({ event_id: "b" }));
    expect(events).toHaveLength(1);
  });

  it("merges a repeated event_id into the existing entry instead of duplicating it", () => {
    const start = makeEvent({
      event_id: "a",
      event_type: "llm_start",
      status: "running",
      timestamp: "2026-11-20T10:00:01Z",
      payload: { model: "gpt-4o", prompts: ["Plan the trip"], completion: null },
    });
    const end = makeEvent({
      event_id: "a",
      event_type: "llm_end",
      status: "completed",
      timestamp: "2026-11-20T10:00:05Z",
      latency_ms: 4000,
      payload: { completion: "Day 1: museums", total_tokens: 42 },
    });

    const result = upsertEvent([start], end);

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      event_type: "llm_end",
      status: "completed",
      latency_ms: 4000,
      // The feed keeps the time the event started.
      timestamp: "2026-11-20T10:00:01Z",
    });
    expect(result[0].payload).toEqual({
      model: "gpt-4o",
      prompts: ["Plan the trip"],
      completion: "Day 1: museums",
      total_tokens: 42,
    });
  });

  it("never overwrites known payload values with empty ones", () => {
    const start = makeEvent({
      event_id: "a",
      payload: { model: "gpt-4o", prompts: ["hi"], output: "kept", tags: ["x"] },
    });
    const update = makeEvent({
      event_id: "a",
      payload: { model: null, prompts: [], output: "", tags: undefined, extra: "" },
    });

    const merged = upsertEvent([start], update)[0].payload;

    expect(merged).toEqual({
      model: "gpt-4o",
      prompts: ["hi"],
      output: "kept",
      tags: ["x"],
      // Empty values are still recorded for keys we did not have yet.
      extra: "",
    });
  });

  it("only touches the matching entry", () => {
    const a = makeEvent({ event_id: "a" });
    const b = makeEvent({ event_id: "b" });
    const result = upsertEvent([a, b], makeEvent({ event_id: "b", status: "completed" }));
    expect(result[0]).toBe(a);
    expect(result[1].status).toBe("completed");
  });
});

describe("mergeGraphUpdate", () => {
  it("starts a graph from the first delta", () => {
    const node = makeNode("root");
    expect(mergeGraphUpdate(null, node, null)).toEqual({ nodes: [node], edges: [] });

    const edge = makeEdge("x", "root");
    expect(mergeGraphUpdate(null, node, edge)).toEqual({ nodes: [node], edges: [edge] });
  });

  it("refreshes the data of a known node but keeps its laid-out position", () => {
    const laidOut = makeNode("n1", { position: { x: 400, y: 200 } });
    const prev = makeGraph([laidOut]);
    const update = makeNode("n1", {
      position: { x: 0, y: 0 },
      data: { ...laidOut.data, status: "completed", durationMs: 1500, tokenCount: 30 },
    });

    const next = mergeGraphUpdate(prev, update, null);

    expect(next.nodes).toHaveLength(1);
    expect(next.nodes[0].position).toEqual({ x: 400, y: 200 });
    expect(next.nodes[0].data).toMatchObject({ status: "completed", durationMs: 1500, tokenCount: 30 });
  });

  it("places a new child below its parent, shifted right per existing sibling", () => {
    const parent = makeNode("p", { position: { x: 100, y: 50 } });
    const first = makeNode("c1", { position: { x: 100, y: 230 } });
    const prev = makeGraph([parent, first], [makeEdge("p", "c1")]);

    const next = mergeGraphUpdate(prev, makeNode("c2", { position: { x: 9, y: 9 } }), makeEdge("p", "c2"));

    const placed = next.nodes.find((n) => n.id === "c2");
    expect(placed?.position).toEqual({ x: 100 + 1 * 280, y: 50 + 180 });
    expect(next.edges.map((e) => e.id)).toEqual(["p->c1", "p->c2"]);
  });

  it("keeps the server position for a new node whose parent is unknown", () => {
    const prev = makeGraph([makeNode("a")]);
    const orphan = makeNode("b", { position: { x: 7, y: 8 } });

    const viaUnknownParent = mergeGraphUpdate(prev, orphan, makeEdge("missing", "b"));
    expect(viaUnknownParent.nodes[1].position).toEqual({ x: 7, y: 8 });

    const withoutEdge = mergeGraphUpdate(prev, orphan, null);
    expect(withoutEdge.nodes[1].position).toEqual({ x: 7, y: 8 });
  });

  it("does not add the same edge twice", () => {
    const prev = makeGraph([makeNode("p"), makeNode("c")], [makeEdge("p", "c")]);
    const next = mergeGraphUpdate(prev, makeNode("c"), makeEdge("p", "c"));
    expect(next.edges).toHaveLength(1);
  });
});

describe("useSessionStore", () => {
  it("addEvent ignores events of sessions other than the active one", () => {
    const store = useSessionStore.getState();
    store.setActiveSession(makeSession({ session_id: "s1" }));

    store.addEvent(makeEvent({ event_id: "mine", session_id: "s1" }));
    store.addEvent(makeEvent({ event_id: "other", session_id: "s2" }));

    expect(useSessionStore.getState().events.map((e) => e.event_id)).toEqual(["mine"]);
  });

  it("addEvent ignores events while no session is active", () => {
    useSessionStore.getState().addEvent(makeEvent());
    expect(useSessionStore.getState().events).toEqual([]);
  });

  it("addEvent upserts by event_id", () => {
    const store = useSessionStore.getState();
    store.setActiveSession(makeSession());
    store.addEvent(makeEvent({ event_id: "a", status: "running" }));
    store.addEvent(makeEvent({ event_id: "a", status: "completed" }));

    const { events } = useSessionStore.getState();
    expect(events).toHaveLength(1);
    expect(events[0].status).toBe("completed");
  });

  it("updateSessionMeta updates the list entry and the active session", () => {
    const s1 = makeSession({ session_id: "s1", total_tokens: 1 });
    const s2 = makeSession({ session_id: "s2", total_tokens: 2 });
    const store = useSessionStore.getState();
    store.setSessions([s1, s2]);
    store.setActiveSession(s1);

    store.updateSessionMeta("s1", { total_tokens: 99, status: "completed" });

    const state = useSessionStore.getState();
    expect(state.sessions[0]).toMatchObject({ total_tokens: 99, status: "completed" });
    expect(state.sessions[1]).toBe(s2);
    expect(state.activeSession).toMatchObject({ session_id: "s1", total_tokens: 99 });
  });

  it("updateSessionMeta leaves a different active session alone", () => {
    const active = makeSession({ session_id: "s1" });
    const store = useSessionStore.getState();
    store.setSessions([active, makeSession({ session_id: "s2" })]);
    store.setActiveSession(active);

    store.updateSessionMeta("s2", { total_tokens: 5 });

    expect(useSessionStore.getState().activeSession).toBe(active);
  });

  it("applyGraphUpdate merges deltas into the stored graph", () => {
    const store = useSessionStore.getState();
    store.setGraph(makeGraph([makeNode("p", { position: { x: 0, y: 0 } })]));

    store.applyGraphUpdate(makeNode("c"), makeEdge("p", "c"));

    const { graph } = useSessionStore.getState();
    expect(graph?.nodes.map((n) => n.id)).toEqual(["p", "c"]);
    expect(graph?.nodes[1].position).toEqual({ x: 0, y: 180 });
    expect(graph?.edges).toHaveLength(1);
  });
});
