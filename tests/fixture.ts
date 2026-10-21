// TEST-ONLY wire peer; not live Hermes evidence.
import {
  JsonRpcGatewayClient,
  type WebSocketLike,
} from "../src/upstream/json-rpc-gateway";
export class Peer {
  sockets: Socket[] = [];
  calls: { method: string; params: Record<string, unknown> }[] = [];
  failPrompt = false;
  respond(method: string, params: Record<string, unknown>): unknown {
    if (method === "session.list")
      return {
        sessions: [
          {
            id: "stored-1",
            title: "Saved chat",
            preview: "hello",
            message_count: 2,
          },
        ],
      };
    if (method === "session.resume")
      return {
        session_id: "runtime-1",
        stored_session_id: "stored-1",
        messages: [
          { role: "user", text: "hello" },
          { role: "assistant", text: "Hello back" },
        ],
        message_count: 2,
        info: {},
        running: false,
      };
    if (method === "session.history")
      return {
        count: 2,
        messages: [
          { role: "user", text: "hello" },
          { role: "assistant", text: "Hello back" },
        ],
      };
    if (method === "session.create")
      return {
        session_id: "new-runtime",
        stored_session_id: "new-stored",
        messages: [],
        message_count: 0,
        info: {},
      };
    if (method === "prompt.submit") return { status: "streaming" };
    if (method === "session.events.since")
      return {
        events: [],
        count: 0,
        latest_seq: 0,
        epoch: "test",
        open_requests: [],
      };
    return {};
  }
  client() {
    return new JsonRpcGatewayClient({
      socketFactory: (url) => {
        const s = new Socket(this, url);
        this.sockets.push(s);
        queueMicrotask(() => s.open());
        return s as unknown as WebSocketLike;
      },
      heartbeatIntervalMs: 0,
      requestTimeoutMs: 1000,
    });
  }
  emit(type: string, payload: unknown = {}, session_id = "runtime-1") {
    this.sockets
      .at(-1)
      ?.frame({ method: "event", params: { type, payload, session_id } });
  }
}
class Socket extends EventTarget {
  readyState = 0;
  constructor(
    readonly peer: Peer,
    readonly url: string,
  ) {
    super();
  }
  open() {
    this.readyState = 1;
    this.dispatchEvent(new Event("open"));
  }
  send(text: string) {
    const f = JSON.parse(text);
    if (!f.method) return;
    this.peer.calls.push(f);
    if (f.method === "prompt.submit" && this.peer.failPrompt) {
      queueMicrotask(() => this.close());
      return;
    }
    queueMicrotask(() =>
      this.frame({
        jsonrpc: "2.0",
        id: f.id,
        result: this.peer.respond(f.method, f.params),
      }),
    );
  }
  frame(data: unknown) {
    this.dispatchEvent(
      new MessageEvent("message", { data: JSON.stringify(data) }),
    );
  }
  close() {
    if (this.readyState === 3) return;
    this.readyState = 3;
    this.dispatchEvent(Object.assign(new Event("close"), { code: 1006 }));
  }
}
