import { setupServer } from "msw/node";

/** msw server for unit tests; each test registers its handlers with server.use(). */
export const server = setupServer();

/** Base URL the dashboard talks to (lib/api.ts default). */
export const API = "http://127.0.0.1:8765";
