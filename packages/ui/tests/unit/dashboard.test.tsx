import React from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Dashboard from "../../app/page";
import type { MemoryItem } from "../../types";
import { FakeWebSocket } from "../support/fakeWebSocket";
import { makeEdge, makeEvent, makeNode, makeSession } from "../support/fixtures";
import { API, server } from "../support/server";

const S1 = "11111111-aaaa-bbbb-cccc-000000000001";
const S2 = "22222222-aaaa-bbbb-cccc-000000000002";
const newest = makeSession({ session_id: S1, name: "Research Crew", total_tokens: 120 });
const older = makeSession({ session_id: S2, name: "Old Pipeline", status: "completed" });

function serveDashboard() {
  server.use(
    http.get(`${API}/api/sessions`, () => HttpResponse.json({ sessions: [newest, older] })),
    http.get(`${API}/api/sessions/${S1}/events`, () =>
      HttpResponse.json({
        events: [
          makeEvent({ event_id: "e1", session_id: S1, agent_name: "planner", event_type: "chain_start", agent_type: "chain", payload: { chain_type: "crew", inputs: { topic: "rain" } } }),
        ],
      })
    ),
    http.get(`${API}/api/sessions/${S1}/graph`, () =>
      HttpResponse.json({ nodes: [makeNode("e1", { data: { ...makeNode("e1").data, agentName: "planner", eventType: "chain_start" } })], edges: [] })
    ),
    http.get(`${API}/api/sessions/${S1}/stats`, () =>
      HttpResponse.json({ total_tokens: 321, total_cost_usd: 0.5, total_duration_ms: 2500, event_count: 1, error_count: 1, agents: [{}, {}, {}], token_timeline: [] })
    ),
    http.get(`${API}/api/sessions/${S2}/events`, () => HttpResponse.json({ events: [] })),
    http.get(`${API}/api/sessions/${S2}/graph`, () => HttpResponse.json({ nodes: [], edges: [] })),
    http.get(`${API}/api/sessions/${S2}/stats`, () => new HttpResponse(null, { status: 500 }))
  );
}

beforeEach(() => {
  FakeWebSocket.reset();
  vi.stubGlobal("WebSocket", FakeWebSocket);
  // jsdom has no layout; the feed auto-scrolls with scrollIntoView.
  Element.prototype.scrollIntoView = vi.fn();
});

describe("Dashboard", () => {
  it("shows the empty state until a session exists", async () => {
    server.use(http.get(`${API}/api/sessions`, () => HttpResponse.json({ sessions: [] })));
    render(<Dashboard />);
    expect(screen.getByText("No Active Session Selected")).toBeInTheDocument();
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(0));
  });

  it("auto-selects the newest session and renders its header, stats, feed and graph", async () => {
    serveDashboard();
    render(<Dashboard />);

    expect(await screen.findByRole("heading", { level: 2, name: "Research Crew" })).toBeInTheDocument();
    expect(screen.getByText(`Session ID: ${S1}`)).toBeInTheDocument();
    expect(await screen.findByText("321")).toBeInTheDocument();
    expect(screen.getByText("$0.50000")).toBeInTheDocument();
    expect(screen.getByText("2.50")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(await screen.findByText("1 Events Received")).toBeInTheDocument();
    expect(await screen.findByText("1 agents, 0 calls")).toBeInTheDocument();
    expect(FakeWebSocket.latest().url).toContain(`session_id=${S1}`);

    // Live connection indicator follows the socket.
    expect(screen.getByTitle(/Connecting or reconnecting/)).toBeInTheDocument();
    act(() => FakeWebSocket.latest().open());
    expect(screen.getByTitle(/telemetry connection established/)).toBeInTheDocument();
  });

  it("streams live events and DAG nodes into the open session", async () => {
    serveDashboard();
    render(<Dashboard />);
    await screen.findByText("1 Events Received");
    await screen.findByText("1 agents, 0 calls");
    act(() => FakeWebSocket.latest().open());

    act(() => {
      FakeWebSocket.latest().message({
        type: "event",
        session_id: S1,
        event: makeEvent({ event_id: "e2", session_id: S1, agent_name: "researcher", event_type: "tool_start", agent_type: "tool", payload: { tool_name: "search" } }),
      });
      FakeWebSocket.latest().message({
        type: "graph_update",
        session_id: S1,
        node: makeNode("e2", { data: { ...makeNode("e2").data, agentName: "researcher", eventType: "tool_start" } }),
        edge: makeEdge("e1", "e2"),
      });
    });

    expect(screen.getByText("2 Events Received")).toBeInTheDocument();
    expect(screen.getByText("2 agents, 1 calls")).toBeInTheDocument();
    expect(screen.getAllByText("researcher").length).toBeGreaterThan(0);
  });

  it("expands an event and keeps it expanded across tab switches", async () => {
    serveDashboard();
    server.use(http.get(`${API}/api/sessions/${S1}/memories`, () => HttpResponse.json({ results: [] })));
    const user = userEvent.setup();
    render(<Dashboard />);

    await user.click(await screen.findByText("chain_start", { selector: "span.font-mono" }));
    expect(screen.getByText("chain_type:")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Mem0 Memories/ }));
    expect(await screen.findByText("No Memories Found")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Execution Flow" }));
    expect(screen.getByText("chain_type:")).toBeInTheDocument();
  });

  it("switches sessions from the sidebar", async () => {
    serveDashboard();
    const user = userEvent.setup();
    render(<Dashboard />);
    await screen.findByText("1 Events Received");

    await user.click(screen.getByText("Old Pipeline"));

    expect(await screen.findByRole("heading", { level: 2, name: "Old Pipeline" })).toBeInTheDocument();
    expect(await screen.findByText("0 Events Received")).toBeInTheDocument();
    expect(screen.getByText("No call hierarchy data for this session yet.")).toBeInTheDocument();
    await waitFor(() => expect(FakeWebSocket.latest().url).toContain(`session_id=${S2}`));
  });
});

describe("Memories tab", () => {
  it("shows the server's configuration error", async () => {
    serveDashboard();
    server.use(
      http.get(`${API}/api/sessions/${S1}/memories`, () =>
        HttpResponse.json({ detail: "Mem0 integration is disabled." }, { status: 400 })
      )
    );
    const user = userEvent.setup();
    render(<Dashboard />);
    await screen.findByText("1 Events Received");

    await user.click(screen.getByRole("button", { name: /Mem0 Memories/ }));

    expect(await screen.findByText("Mem0 integration is disabled.")).toBeInTheDocument();
    expect(screen.getByText("Configuration Warning")).toBeInTheDocument();
  });

  it("lists, searches, adds and deletes memories", async () => {
    serveDashboard();
    let memories: MemoryItem[] = [
      { id: "m1", memory: "Prefers window seats", categories: ["preferences"], metadata: { agent_name: "planner" } },
      { id: "m2", memory: "Allergic to nuts", metadata: { categories: ["health"] } },
    ];
    const added: unknown[] = [];
    server.use(
      http.get(`${API}/api/sessions/${S1}/memories`, () => HttpResponse.json({ results: memories })),
      http.post(`${API}/api/sessions/${S1}/memories/search`, () =>
        HttpResponse.json({ results: [memories[1]] })
      ),
      http.post(`${API}/api/sessions/${S1}/memories`, async ({ request }) => {
        added.push(await request.json());
        return HttpResponse.json({ ok: true });
      }),
      http.delete(`${API}/api/sessions/${S1}/memories/m1`, () => {
        memories = memories.filter((m) => m.id !== "m1");
        return HttpResponse.json({ ok: true });
      })
    );
    const user = userEvent.setup();
    render(<Dashboard />);
    await screen.findByText("1 Events Received");
    await user.click(screen.getByRole("button", { name: /Mem0 Memories/ }));

    expect(await screen.findByText("2 Memories Stored")).toBeInTheDocument();
    expect(screen.getByText("Agent: planner")).toBeInTheDocument();
    expect(screen.getByText("preferences")).toBeInTheDocument();
    expect(screen.getByText("health")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("Semantic search memories..."), "nuts");
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("1 Memories Stored")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reset" }));
    expect(await screen.findByText("2 Memories Stored")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("Add a new custom memory..."), "Likes tea");
    await user.type(screen.getByPlaceholderText("Categories (e.g. preferences, facts)..."), "food, , drinks");
    await user.click(screen.getByRole("button", { name: "Add Memory" }));
    await waitFor(() => expect(added).toEqual([{ text: "Likes tea", categories: ["food", "drinks"] }]));
    expect(screen.getByPlaceholderText("Add a new custom memory...")).toHaveValue("");

    const card = screen.getByText("Prefers window seats").closest("div.group") as HTMLElement;
    await user.click(within(card).getByTitle("Delete memory"));
    expect(await screen.findByText("1 Memories Stored")).toBeInTheDocument();
  });
});
