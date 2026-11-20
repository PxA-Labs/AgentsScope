import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { ExportControls } from "../../components/ExportImportControls";
import { SessionList } from "../../components/SessionList";
import { makeSession } from "../support/fixtures";
import { API, server } from "../support/server";

const session = makeSession({ name: "Trip planner", session_id: "abcdef1234567890" });

/** Captures what the export flow hands to the browser's download mechanism. */
function captureDownloads() {
  const downloads: { name: string; href: string; blob: Blob }[] = [];
  const blobs = new Map<string, Blob>();
  let n = 0;
  // jsdom has no object URLs; install stand-ins for this test only.
  const original = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
  URL.createObjectURL = vi.fn((blob: Blob) => {
    const url = `blob:test/${++n}`;
    blobs.set(url, blob);
    return url;
  });
  URL.revokeObjectURL = vi.fn();
  onTestFinished(() => {
    URL.createObjectURL = original.create;
    URL.revokeObjectURL = original.revoke;
  });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    downloads.push({ name: this.download, href: this.href, blob: blobs.get(this.href)! });
  });
  return downloads;
}

describe("ExportControls", () => {
  let downloads: ReturnType<typeof captureDownloads>;
  beforeEach(() => {
    downloads = captureDownloads();
  });

  it("downloads CSV under the server's Content-Disposition filename", async () => {
    server.use(
      http.get(`${API}/api/sessions/abcdef1234567890/export`, () =>
        new HttpResponse("﻿event_id\r\ne1\r\n", {
          headers: {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": 'attachment; filename="trip-planner_abcdef12.csv"',
          },
        })
      )
    );
    render(<ExportControls session={session} />);

    await userEvent.click(screen.getByRole("button", { name: "CSV" }));

    await waitFor(() => expect(downloads).toHaveLength(1));
    expect(downloads[0].name).toBe("trip-planner_abcdef12.csv");
    expect(downloads[0].blob.type).toBe("text/csv;charset=utf-8");
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(downloads[0].href);
    // The temporary link is removed again.
    expect(document.querySelector("a[download]")).toBeNull();
    expect(screen.getByRole("group", { name: "Export session" })).toHaveTextContent("Export");
  });

  it("downloads JSON under a name built from the session", async () => {
    server.use(
      http.get(`${API}/api/sessions/abcdef1234567890/export`, () =>
        HttpResponse.json({ session: {}, events: [] })
      )
    );
    render(<ExportControls session={session} />);

    await userEvent.click(screen.getByRole("button", { name: "JSON" }));

    await waitFor(() => expect(downloads).toHaveLength(1));
    expect(downloads[0].name).toBe("Trip_planner_abcdef12.json");
  });

  it("disables both formats while an export is running", async () => {
    let release!: () => void;
    server.use(
      http.get(`${API}/api/sessions/abcdef1234567890/export`, async () => {
        await new Promise<void>((r) => (release = r));
        return HttpResponse.json({ session: {}, events: [] });
      })
    );
    render(<ExportControls session={session} />);

    await userEvent.click(screen.getByRole("button", { name: "JSON" }));

    expect(await screen.findByText("Exporting...")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "JSON" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "CSV" })).toBeDisabled();
    release();
    await waitFor(() => expect(screen.getByRole("button", { name: "CSV" })).toBeEnabled());
  });

  it("alerts when the export fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const alert = vi.fn();
    vi.stubGlobal("alert", alert);
    server.use(
      http.get(`${API}/api/sessions/abcdef1234567890/export`, () => new HttpResponse(null, { status: 500 }))
    );
    render(<ExportControls session={session} />);

    await userEvent.click(screen.getByRole("button", { name: "CSV" }));

    await waitFor(() =>
      expect(alert).toHaveBeenCalledWith("Failed to export session telemetry data as CSV.")
    );
    expect(downloads).toHaveLength(0);
  });
});

describe("Session import (sidebar)", () => {
  function renderList(onImported = vi.fn()) {
    const { container } = render(
      <SessionList
        sessions={[]}
        activeSessionId={null}
        onSelect={vi.fn()}
        onRefresh={vi.fn()}
        onImported={onImported}
      />
    );
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    return { input, onImported };
  }

  it("imports a session export, reports success and resets the picker", async () => {
    const imported = makeSession({ name: "Imported run" });
    server.use(http.post(`${API}/api/sessions/import`, () => HttpResponse.json(imported, { status: 201 })));
    const { input, onImported } = renderList();

    const file = new File([JSON.stringify({ session: { name: "x" }, events: [] })], "run.json", {
      type: "application/json",
    });
    await userEvent.upload(input, file);

    expect(await screen.findByText('Imported "Imported run" successfully!')).toBeInTheDocument();
    expect(onImported).toHaveBeenCalledWith(imported);
    expect(input.value).toBe("");
  });

  it("shows an error for files that are not session exports", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { input, onImported } = renderList();

    await userEvent.upload(input, new File(["{}"], "bad.json", { type: "application/json" }));

    expect(
      await screen.findByText("Invalid session export structure: missing session or events")
    ).toBeInTheDocument();
    expect(onImported).not.toHaveBeenCalled();
  });

  it("filters the session list by name", async () => {
    render(
      <SessionList
        sessions={[makeSession({ session_id: "a", name: "Alpha" }), makeSession({ session_id: "b", name: "Beta" })]}
        activeSessionId="a"
        onSelect={vi.fn()}
        onRefresh={vi.fn()}
        onImported={vi.fn()}
      />
    );
    await userEvent.type(screen.getByPlaceholderText("Search sessions..."), "bet");
    expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
  });
});
