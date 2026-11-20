import React from "react";
import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthBanner } from "../../components/AuthBanner";
import { SESSIONS_POLL_INTERVAL_MS, useSessions } from "../../hooks/useSessions";
import { notifyUnauthorized } from "../../lib/api";
import { useSessionStore } from "../../store/sessionStore";
import { makeSession } from "../support/fixtures";
import { API, server } from "../support/server";

function countSessionRequests(status = 200) {
  const calls = { count: 0 };
  server.use(
    http.get(`${API}/api/sessions`, () => {
      calls.count += 1;
      return status === 200
        ? HttpResponse.json({ sessions: [makeSession({ session_id: "s1" })] })
        : new HttpResponse(null, { status });
    })
  );
  return calls;
}

describe("useSessions polling", () => {
  beforeEach(() => {
    // Only the polling interval is faked; fetch (msw) keeps real timers.
    // vi.waitFor is used below because RTL's waitFor polls with setInterval.
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("loads sessions now and every 4s, auto-selecting the newest one", async () => {
    const calls = countSessionRequests();
    const selectSession = vi.fn((s) => useSessionStore.getState().setActiveSession(s));

    renderHook(() => useSessions(selectSession));

    await vi.waitFor(() => expect(useSessionStore.getState().sessions).toHaveLength(1));
    expect(selectSession).toHaveBeenCalledWith(expect.objectContaining({ session_id: "s1" }));
    // Selecting a session restarts polling with an immediate refetch.
    await vi.waitFor(() => expect(calls.count).toBe(2));

    act(() => vi.advanceTimersByTime(SESSIONS_POLL_INTERVAL_MS));
    await vi.waitFor(() => expect(calls.count).toBe(3));
    expect(selectSession).toHaveBeenCalledTimes(1);
  });

  it("stops polling after a 401 until the page is reloaded", async () => {
    const calls = countSessionRequests(401);
    renderHook(() => useSessions(vi.fn()));

    await vi.waitFor(() => expect(calls.count).toBe(1));
    // Let React commit the unauthorized state raised by apiFetch.
    await act(() => new Promise((r) => setTimeout(r, 20)));
    act(() => vi.advanceTimersByTime(SESSIONS_POLL_INTERVAL_MS * 5));
    // Give any (unexpected) request a chance to land.
    await new Promise((r) => setTimeout(r, 50));
    expect(calls.count).toBe(1);
  });

  it("stops polling when the WebSocket reports rejected credentials (4401)", async () => {
    const calls = countSessionRequests();
    renderHook(() => useSessions(vi.fn()));
    await vi.waitFor(() => expect(calls.count).toBe(1));

    // useLiveEvents calls notifyUnauthorized() on close code 4401.
    act(() => notifyUnauthorized());
    act(() => vi.advanceTimersByTime(SESSIONS_POLL_INTERVAL_MS * 3));
    await new Promise((r) => setTimeout(r, 50));
    expect(calls.count).toBe(1);
  });

  it("logs and keeps polling when the server is unreachable", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    server.use(http.get(`${API}/api/sessions`, () => HttpResponse.error()));
    renderHook(() => useSessions(vi.fn()));
    await vi.waitFor(() =>
      expect(warn).toHaveBeenCalledWith("Failed to fetch sessions list", expect.anything())
    );

    const calls = countSessionRequests();
    act(() => vi.advanceTimersByTime(SESSIONS_POLL_INTERVAL_MS));
    await vi.waitFor(() => expect(calls.count).toBe(1));
  });
});

describe("AuthBanner", () => {
  it("stays hidden until the server rejects the credentials", () => {
    render(<AuthBanner />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    act(() => notifyUnauthorized());
    expect(screen.getByRole("alert")).toHaveTextContent("This AgentScope server requires an API key.");
  });

  it("says the saved key was rejected and saves a new one", async () => {
    window.localStorage.setItem("agentscope.apiKey", "old");
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    render(<AuthBanner />);
    act(() => notifyUnauthorized());

    expect(screen.getByRole("alert")).toHaveTextContent("rejected the saved API key");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("API key"), "  new-key  ");
    await user.click(screen.getByRole("button", { name: "Save & reload" }));

    expect(window.localStorage.getItem("agentscope.apiKey")).toBe("new-key");
    expect(reload).toHaveBeenCalled();
  });
});
