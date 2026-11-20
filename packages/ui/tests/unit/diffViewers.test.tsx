import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { PromptDiffViewer } from "../../components/PromptDiffViewer";
import { SessionDiffViewer } from "../../components/SessionDiffViewer";
import { makeEvent, makeSession } from "../support/fixtures";
import { API, server } from "../support/server";

describe("PromptDiffViewer", () => {
  const current = makeEvent({
    event_id: "now",
    agent_name: "writer",
    timestamp: "2026-11-20T10:00:05Z",
    payload: { model: "gpt-4o", prompts: ["Write a haiku about rain"] },
  });
  const earlier = makeEvent({
    event_id: "before",
    agent_name: "drafter",
    timestamp: "2026-11-20T10:00:01Z",
    payload: { model: "claude-x", prompt: "Write a poem about rain" },
  });
  const notLlm = makeEvent({ event_id: "tool", agent_type: "tool", payload: { input: "x" } });
  const noPrompt = makeEvent({ event_id: "empty", payload: { prompts: [] } });

  it("is disabled when no other LLM event has a prompt", () => {
    render(<PromptDiffViewer currentEvent={current} allEvents={[current, notLlm, noPrompt]} />);
    const button = screen.getByRole("button", { name: /Compare Prompt/ });
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent("(no other LLM events)");
  });

  it("lists comparable events and shows a diff of the chosen prompt", async () => {
    const user = userEvent.setup();
    render(<PromptDiffViewer currentEvent={current} allEvents={[earlier, current, notLlm]} />);

    await user.click(screen.getByRole("button", { name: /Compare Prompt/ }));
    const listbox = screen.getByRole("listbox", { name: "Select prompt to compare with" });
    expect(within(listbox).getByText("1 other LLM event available")).toBeInTheDocument();
    const option = within(listbox).getByRole("option");
    expect(option).toHaveTextContent("drafter");
    expect(option).toHaveTextContent("claude-x");
    expect(option).toHaveTextContent("Write a poem about rain");

    await user.click(option);

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.getByText("Prompt Diff")).toBeInTheDocument();
    expect(await screen.findAllByText(/haiku/)).not.toHaveLength(0);
    expect(screen.getAllByText(/poem/)).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: /Change Comparison/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Unified" }));
    await user.click(screen.getByRole("button", { name: /Close Diff/ }));
    expect(screen.queryByText("Prompt Diff")).not.toBeInTheDocument();
  });

  it("closes the picker on Escape", async () => {
    const user = userEvent.setup();
    render(<PromptDiffViewer currentEvent={current} allEvents={[earlier, current]} />);
    await user.click(screen.getByRole("button", { name: /Compare Prompt/ }));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});

describe("SessionDiffViewer", () => {
  const baseline = makeSession({ session_id: "aaaaaaaa-1", name: "Baseline run", total_tokens: 100, total_cost_usd: 0.01, error_count: 0 });
  const target = makeSession({ session_id: "bbbbbbbb-2", name: "Target run", total_tokens: 150, total_cost_usd: 0.004, error_count: 2 });

  function serveSessions() {
    server.use(
      // Newest first, as the API returns them: B is the newer run.
      http.get(`${API}/api/sessions`, () => HttpResponse.json({ sessions: [target, baseline] })),
      http.get(`${API}/api/sessions/aaaaaaaa-1/events`, () =>
        HttpResponse.json({
          events: [
            makeEvent({ event_id: "a1", session_id: "aaaaaaaa-1", agent_name: "planner", latency_ms: 120, payload: { model: "gpt-4o", prompts: ["Plan a trip to Rome"], completion: "Visit the Colosseum", total_tokens: 30 } }),
          ],
        })
      ),
      http.get(`${API}/api/sessions/bbbbbbbb-2/events`, () =>
        HttpResponse.json({
          events: [
            makeEvent({ event_id: "b1", session_id: "bbbbbbbb-2", agent_name: "planner", payload: { model: "gpt-4o", prompts: ["Plan a trip to Paris"], completion: "Visit the Louvre" } }),
            makeEvent({ event_id: "b2", session_id: "bbbbbbbb-2", agent_name: "search", agent_type: "tool", event_type: "tool_error", status: "error", payload: { input: "q" } }),
          ],
        })
      )
    );
  }

  it("preselects the two newest sessions and compares their metrics", async () => {
    serveSessions();
    render(<SessionDiffViewer />);

    expect(await screen.findByText("2 Sequence Steps")).toBeInTheDocument();
    const [selectA, selectB] = screen.getAllByRole("combobox") as HTMLSelectElement[];
    expect(selectA.value).toBe("aaaaaaaa-1");
    expect(selectB.value).toBe("bbbbbbbb-2");
    expect(screen.getByText("+50")).toBeInTheDocument(); // tokens
    expect(screen.getByText("+2")).toBeInTheDocument(); // errors
    expect(screen.getByText("+1")).toBeInTheDocument(); // events
    expect(screen.getByText("$0.0060")).toBeInTheDocument(); // |cost delta|
    expect(screen.getByText("(No corresponding event)")).toBeInTheDocument();
  });

  it("opens the prompt and completion diff for an aligned LLM step", async () => {
    serveSessions();
    const user = userEvent.setup();
    render(<SessionDiffViewer />);

    const diffMarkers = await screen.findAllByText("DIFF");
    await user.click(diffMarkers[0]);

    expect(screen.getByText("Step #1 Payload Diff")).toBeInTheDocument();
    expect(await screen.findAllByText(/Rome/)).not.toHaveLength(0);
    expect(screen.getAllByText(/Paris/)).not.toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Completion Diff" }));
    expect(await screen.findAllByText(/Louvre/)).not.toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByText("Step #1 Payload Diff")).not.toBeInTheDocument();
  });

  it("swaps baseline and target", async () => {
    serveSessions();
    const user = userEvent.setup();
    render(<SessionDiffViewer />);
    await screen.findByText("2 Sequence Steps");

    await user.click(screen.getByTitle("Swap Sessions A & B"));

    const [selectA, selectB] = screen.getAllByRole("combobox") as HTMLSelectElement[];
    await waitFor(() => expect(selectA.value).toBe("bbbbbbbb-2"));
    expect(selectB.value).toBe("aaaaaaaa-1");
    expect(screen.getByText("-50")).toBeInTheDocument();
  });

  it("asks for a selection when there are no sessions", async () => {
    server.use(http.get(`${API}/api/sessions`, () => HttpResponse.json({ sessions: [] })));
    render(<SessionDiffViewer />);
    expect(
      await screen.findByText("Select two sessions above to compare execution traces.")
    ).toBeInTheDocument();
  });
});
