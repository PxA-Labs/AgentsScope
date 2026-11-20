/**
 * Minimal stand-in for the browser WebSocket, installed with
 * vi.stubGlobal("WebSocket", FakeWebSocket). Tests drive the lifecycle
 * through open() / message() / fail() / serverClose().
 */
export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  static reset(): void {
    FakeWebSocket.instances = [];
  }

  static latest(): FakeWebSocket {
    const ws = FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
    if (!ws) throw new Error("no WebSocket has been opened");
    return ws;
  }

  url: string;
  protocols?: string | string[];
  closed = false;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;

  constructor(url: string, protocols?: string | string[]) {
    this.url = url;
    this.protocols = protocols;
    FakeWebSocket.instances.push(this);
  }

  open(): void {
    this.onopen?.(new Event("open"));
  }

  message(data: unknown): void {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) }));
  }

  fail(): void {
    this.onerror?.(new Event("error"));
  }

  serverClose(code = 1006): void {
    this.closed = true;
    this.onclose?.(new CloseEvent("close", { code }));
  }

  /** Called by the hook on cleanup; like a real socket, no onclose here. */
  close(): void {
    this.closed = true;
  }
}
