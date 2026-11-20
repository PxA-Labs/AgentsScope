import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import {
  addMemory,
  apiFetch,
  base64UrlEncode,
  deleteMemory,
  exportFilename,
  exportSession,
  filenameFromContentDisposition,
  getApiKey,
  getSessionEvents,
  getSessionGraph,
  getSessionStats,
  importSession,
  listMemories,
  listSessions,
  searchMemories,
  setApiKey,
  UNAUTHORIZED_EVENT,
  wsProtocols,
} from "../../lib/api";
import { makeSession } from "../support/fixtures";
import { API, server } from "../support/server";

describe("API key handling", () => {
  it("stores, reads and clears the key in localStorage", () => {
    expect(getApiKey()).toBeNull();
    setApiKey("k1");
    expect(getApiKey()).toBe("k1");
    setApiKey(null);
    expect(getApiKey()).toBeNull();
  });

  it("sends the key as a bearer token", async () => {
    setApiKey("secret");
    let auth: string | null = null;
    server.use(
      http.get(`${API}/api/sessions`, ({ request }) => {
        auth = request.headers.get("Authorization");
        return HttpResponse.json({ sessions: [] });
      })
    );
    await apiFetch("/api/sessions");
    expect(auth).toBe("Bearer secret");
  });

  it("keeps an explicit Authorization header", async () => {
    setApiKey("secret");
    let auth: string | null = null;
    server.use(
      http.get(`${API}/api/sessions`, ({ request }) => {
        auth = request.headers.get("Authorization");
        return HttpResponse.json({ sessions: [] });
      })
    );
    await apiFetch("/api/sessions", { headers: { Authorization: "Bearer other" } });
    expect(auth).toBe("Bearer other");
  });

  it("raises the unauthorized event on HTTP 401 only", async () => {
    const listener = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, listener);
    try {
      server.use(
        http.get(`${API}/api/sessions`, () => new HttpResponse(null, { status: 401 })),
        http.get(`${API}/api/sessions/x/graph`, () => new HttpResponse(null, { status: 500 }))
      );
      expect((await apiFetch("/api/sessions")).status).toBe(401);
      expect(listener).toHaveBeenCalledTimes(1);
      await apiFetch("/api/sessions/x/graph");
      expect(listener).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener(UNAUTHORIZED_EVENT, listener);
    }
  });

  it("encodes the WebSocket auth subprotocol as unpadded base64url", () => {
    expect(base64UrlEncode("key?>")).toBe("a2V5Pz4");
    expect(wsProtocols(null)).toBeUndefined();
    expect(wsProtocols("ab")).toEqual(["agentscope", "agentscope.auth.YWI"]);
  });
});

describe("read endpoints", () => {
  it("return parsed JSON on success and null on an error status", async () => {
    const session = makeSession();
    server.use(
      http.get(`${API}/api/sessions`, () => HttpResponse.json({ sessions: [session], total: 1 })),
      http.get(`${API}/api/sessions/s1/events`, () => HttpResponse.json({ events: [] })),
      http.get(`${API}/api/sessions/s1/graph`, () => HttpResponse.json({ nodes: [], edges: [] })),
      http.get(`${API}/api/sessions/s1/stats`, () => new HttpResponse(null, { status: 404 }))
    );

    expect(await listSessions()).toEqual({ sessions: [session], total: 1 });
    expect(await getSessionEvents("s1")).toEqual({ events: [] });
    expect(await getSessionGraph("s1")).toEqual({ nodes: [], edges: [] });
    expect(await getSessionStats("s1")).toBeNull();
  });

  it("reject on network errors", async () => {
    server.use(http.get(`${API}/api/sessions`, () => HttpResponse.error()));
    await expect(listSessions()).rejects.toThrow();
  });
});

describe("memories endpoints", () => {
  it("return results or the server's error detail", async () => {
    server.use(
      http.get(`${API}/api/sessions/s1/memories`, () =>
        HttpResponse.json({ detail: "Mem0 integration is disabled." }, { status: 400 })
      ),
      http.post(`${API}/api/sessions/s1/memories/search`, async ({ request }) => {
        const body = (await request.json()) as { query: string };
        return HttpResponse.json({ results: [{ id: "m1", memory: body.query }] });
      }),
      http.post(`${API}/api/sessions/s1/memories`, () => HttpResponse.json({ ok: true })),
      http.delete(`${API}/api/sessions/s1/memories/m1`, () =>
        HttpResponse.json({ detail: "Memory not found in this session" }, { status: 404 })
      )
    );

    expect(await listMemories("s1")).toEqual({ ok: false, detail: "Mem0 integration is disabled." });
    expect(await searchMemories("s1", "trip")).toEqual({
      ok: true,
      data: { results: [{ id: "m1", memory: "trip" }] },
    });
    expect(await addMemory("s1", { text: "likes tea" })).toEqual({ ok: true, data: null });
    expect(await deleteMemory("s1", "m1")).toEqual({
      ok: false,
      detail: "Memory not found in this session",
    });
  });
});

describe("export filenames", () => {
  it("reads the quoted filename from Content-Disposition", () => {
    expect(filenameFromContentDisposition('attachment; filename="run_1234abcd.csv"')).toBe(
      "run_1234abcd.csv"
    );
    expect(filenameFromContentDisposition("attachment")).toBeUndefined();
    expect(filenameFromContentDisposition(null)).toBeUndefined();
  });

  it("prefers the server's filename", () => {
    const session = makeSession({ name: "My run", session_id: "abcdef1234567890" });
    expect(exportFilename(session, "csv", "server.csv")).toBe("server.csv");
  });

  it("otherwise builds a safe name from the session name and id prefix", () => {
    const session = makeSession({ name: "My run: v2/α", session_id: "abcdef1234567890" });
    expect(exportFilename(session, "json")).toBe("My_run__v2___abcdef12.json");
    expect(exportFilename({ ...session, name: "" }, "csv")).toBe("session_abcdef12.csv");
  });
});

describe("exportSession", () => {
  const session = makeSession({ name: "Trip planner", session_id: "abcdef1234567890" });

  it("keeps CSV bytes as sent and uses the Content-Disposition filename", async () => {
    const csv = "﻿event_id,agent_name\r\ne1,planner\r\n";
    server.use(
      http.get(`${API}/api/sessions/abcdef1234567890/export`, ({ request }) => {
        expect(new URL(request.url).searchParams.get("format")).toBe("csv");
        return new HttpResponse(csv, {
          headers: {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": 'attachment; filename="trip_planner_abcdef12.csv"',
          },
        });
      })
    );

    const { blob, filename } = await exportSession(session, "csv");

    expect(filename).toBe("trip_planner_abcdef12.csv");
    expect(blob.type).toBe("text/csv;charset=utf-8");
    const bytes = new Uint8Array(await blob.arrayBuffer());
    expect(Array.from(bytes.slice(0, 3))).toEqual([0xef, 0xbb, 0xbf]);
    expect(new TextDecoder().decode(bytes)).toBe(csv.slice(1));
  });

  it("pretty-prints JSON and falls back to a local filename", async () => {
    server.use(
      http.get(`${API}/api/sessions/abcdef1234567890/export`, () =>
        HttpResponse.json({ session: { name: "Trip planner" }, events: [] })
      )
    );

    const { blob, filename } = await exportSession(session, "json");

    expect(filename).toBe("Trip_planner_abcdef12.json");
    expect(blob.type).toBe("application/json");
    expect(await blob.text()).toBe(
      JSON.stringify({ session: { name: "Trip planner" }, events: [] }, null, 2)
    );
  });

  it("rejects on an error status", async () => {
    server.use(
      http.get(`${API}/api/sessions/abcdef1234567890/export`, () => new HttpResponse(null, { status: 500 }))
    );
    await expect(exportSession(session, "csv")).rejects.toThrow("Failed to export session");
  });
});

describe("importSession", () => {
  it("rejects files that are not JSON", async () => {
    await expect(importSession("{nope")).rejects.toThrow("Invalid JSON file format");
  });

  it("rejects JSON that is not a session export", async () => {
    await expect(importSession(JSON.stringify({ session: {} }))).rejects.toThrow(
      "Invalid session export structure: missing session or events"
    );
  });

  it("posts the export and returns the imported session", async () => {
    const imported = makeSession({ name: "Imported" });
    let posted: unknown;
    server.use(
      http.post(`${API}/api/sessions/import`, async ({ request }) => {
        posted = await request.json();
        return HttpResponse.json(imported, { status: 201 });
      })
    );
    const payload = { session: { name: "x" }, events: [] };

    expect(await importSession(JSON.stringify(payload))).toEqual(imported);
    expect(posted).toEqual(payload);
  });

  it("surfaces the server's error detail", async () => {
    server.use(
      http.post(`${API}/api/sessions/import`, () =>
        HttpResponse.json({ detail: "Session already exists" }, { status: 409 })
      )
    );
    await expect(importSession(JSON.stringify({ session: {}, events: [] }))).rejects.toThrow(
      "Session already exists"
    );
  });
});
