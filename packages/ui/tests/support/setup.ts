import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { useSessionStore } from "../../store/sessionStore";
import { server } from "./server";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));

afterEach(() => {
  cleanup();
  server.resetHandlers();
  window.localStorage.clear();
  useSessionStore.setState(useSessionStore.getInitialState(), true);
});

afterAll(() => server.close());
