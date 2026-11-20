import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext } from "@playwright/test";

const API_URL = process.env.E2E_API_URL!;
const WS_URL = process.env.E2E_WS_URL!;

async function createSession(request: APIRequestContext, name: string): Promise<string> {
  const sessionId = randomUUID();
  const res = await request.post(`${API_URL}/api/sessions`, {
    data: { session_id: sessionId, name },
  });
  expect(res.status()).toBe(201);
  return sessionId;
}

/**
 * Send events the way the Python SDK does: over the SDK WebSocket
 * (`/ws?client_type=sdk`) as {"type": "event", "session_id", "event"}.
 */
async function emitEvents(sessionId: string, events: Record<string, unknown>[]): Promise<void> {
  const ws = new WebSocket(`${WS_URL}/ws?client_type=sdk`);
  await new Promise<void>((resolve, reject) => {
    ws.onopen = () => resolve();
    ws.onerror = () => reject(new Error("SDK WebSocket failed to open"));
  });
  for (const event of events) {
    ws.send(JSON.stringify({ type: "event", session_id: sessionId, event }));
  }
  // The server processes messages in order; give it a moment before closing.
  await new Promise((r) => setTimeout(r, 500));
  ws.close();
}

function event(
  sessionId: string,
  overrides: Record<string, unknown> & { event_id: string; event_type: string }
): Record<string, unknown> {
  return {
    session_id: sessionId,
    parent_event_id: null,
    agent_name: "planner",
    agent_type: "chain",
    status: "running",
    timestamp: new Date().toISOString(),
    latency_ms: null,
    payload: {},
    ...overrides,
  };
}

test("dashboard lists a new session and streams its events live", async ({ page, request }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "AgentScope" })).toBeVisible();

  const name = `e2e-smoke-${Date.now()}`;
  const sessionId = await createSession(request, name);

  // The sidebar polls the session list every 4s.
  const card = page.getByText(name, { exact: true }).first();
  await expect(card).toBeVisible();
  await card.click();
  await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
  await expect(page.getByText(`Session ID: ${sessionId}`)).toBeVisible();
  await expect(page.getByText("0 Events Received")).toBeVisible();
  await expect(page.getByTitle("Live WebSocket telemetry connection established")).toBeVisible();

  const chainId = randomUUID();
  const toolId = randomUUID();
  await emitEvents(sessionId, [
    event(sessionId, {
      event_id: chainId,
      event_type: "chain_start",
      agent_name: "planner",
      payload: { chain_type: "crew", inputs: { topic: "e2e" } },
    }),
    event(sessionId, {
      event_id: toolId,
      parent_event_id: chainId,
      event_type: "tool_start",
      agent_name: "web_search",
      agent_type: "tool",
      payload: { tool_name: "web_search", input: "agentscope" },
    }),
    event(sessionId, {
      event_id: toolId,
      parent_event_id: chainId,
      event_type: "tool_end",
      agent_name: "web_search",
      agent_type: "tool",
      status: "completed",
      latency_ms: 42,
      payload: { tool_name: "web_search", output: "3 results" },
    }),
  ]);

  // Live feed: the tool start/end pair is merged into one entry.
  await expect(page.getByText("2 Events Received")).toBeVisible();
  const feed = page.locator("section", { hasText: "Live Execution Feed" });
  await expect(feed.getByText("tool_end")).toBeVisible();

  // Live DAG: both nodes and the call edge are rendered.
  const graph = page.locator("section", { hasText: "Agent Call Hierarchy" });
  await expect(graph.getByText("2 agents, 1 calls")).toBeVisible();
  await expect(graph.getByText("planner").first()).toBeVisible();
  await expect(graph.getByText("web_search").first()).toBeVisible();

  // Opening an event shows its payload.
  await feed.getByText("tool_end").click();
  await expect(feed.getByText("3 results")).toBeVisible();

  // After a reload the session's history comes back from the REST API.
  await page.reload();
  await page.getByText(name, { exact: true }).first().click();
  await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
  await expect(page.getByText("2 Events Received")).toBeVisible();
});
