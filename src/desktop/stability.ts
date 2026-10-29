// Connection stability diagnostics for phone rounds (NG-4, 2026-10-20). Observe only: nothing
// here changes when or how the renderer connects. Lines go through diag() (logcat HermesDiag)
// and carry counts, codes and milliseconds only, never the URL, ticket or close reason text.
import { diag, full } from "./diag";

const GATEWAY_PATH = "/api/ws";
const SUMMARY_MS = 5 * 60_000;

export type StabilityCounters = { opens: number; closes: number; abnormal: number; errors: number; open: number };

/** Wraps WebSocket so each Hermes gateway socket logs open, close and error with timings. */
export function installSocketDiag(win: Window & typeof globalThis = window, now: () => number = () => Date.now()) {
  const Native = win.WebSocket;
  const counters: StabilityCounters = { opens: 0, closes: 0, abnormal: 0, errors: 0, open: 0 };
  let next = 0;
  let lastClose: number | undefined;
  const gateway = (url: string | URL) => {
    try {
      return new URL(String(url), win.location.href).pathname === GATEWAY_PATH;
    } catch {
      return false;
    }
  };
  const track = (socket: WebSocket) => {
    const id = ++next;
    const started = now();
    let opened: number | undefined;
    trackRpc(socket, id, now);
    socket.addEventListener("open", () => {
      opened = now();
      counters.opens++;
      counters.open++;
      diag("ws_open", { id, connect_ms: opened - started, since_close_ms: lastClose === undefined ? undefined : opened - lastClose, opens: counters.opens });
    });
    socket.addEventListener("error", () => {
      counters.errors++;
      diag("ws_error", { id, opened: opened !== undefined });
    });
    socket.addEventListener("close", event => {
      const at = now();
      counters.closes++;
      if (opened !== undefined) counters.open--;
      // 1000 is a normal close (app or server chose to end it); everything else is a drop.
      if (event.code !== 1000) counters.abnormal++;
      lastClose = at;
      diag("ws_close", { id, code: event.code, clean: event.wasClean, up_ms: opened === undefined ? undefined : at - opened, never_opened: opened === undefined, abnormal: counters.abnormal });
    });
  };
  class ObservedWebSocket extends Native {
    constructor(url: string | URL, protocols?: string | string[]) {
      super(url, protocols);
      if (gateway(url)) track(this);
    }
  }
  win.WebSocket = ObservedWebSocket as typeof WebSocket;
  const onNetwork = () => diag("network", { online: win.navigator.onLine });
  const onVisibility = () => diag("visibility", { state: win.document.visibilityState, open: counters.open });
  win.addEventListener("online", onNetwork);
  win.addEventListener("offline", onNetwork);
  win.document.addEventListener("visibilitychange", onVisibility);
  const summary = win.setInterval(() => diag("ws_summary", { ...counters }), SUMMARY_MS);
  return {
    counters,
    dispose() {
      win.WebSocket = Native;
      win.removeEventListener("online", onNetwork);
      win.removeEventListener("offline", onNetwork);
      win.document.removeEventListener("visibilitychange", onVisibility);
      win.clearInterval(summary);
    },
  };
}

const RPC_SUMMARY_MS = 10_000;
// Frame head only: ids, method names, error codes and event types sit near the start.
const HEAD = 400;
const pick = (head: string, pattern: RegExp) => pattern.exec(head)?.[1];

/** Verbose RPC log for one gateway socket: each request as "rpc method ms ok|error code", each
 *  event type as a 10 s count summary. Reads the frame head with patterns instead of parsing it
 *  again. DEV PHONE: every frame is also logged in full ("[hermes-full] ws_out/ws_in", secrets
 *  masked, cut to one logcat entry); the app's file log saves it on the phone. */
export function trackRpc(socket: WebSocket, ws: number, now: () => number = () => Date.now()) {
  const pending = new Map<string, { method: string; at: number }>();
  let events: Record<string, number> = {};
  if (typeof socket.send !== "function") return;
  const send = socket.send.bind(socket);
  socket.send = (data: Parameters<WebSocket["send"]>[0]) => {
    if (typeof data === "string") {
      full(`ws_out ws=${ws}`, data);
      const head = data.slice(0, HEAD);
      const rid = pick(head, /"id"\s*:\s*"?([\w-]{1,64})"?/);
      const method = pick(head, /"method"\s*:\s*"([\w.\-/]{1,64})"/);
      if (rid && method) pending.set(rid, { method, at: now() });
    }
    send(data);
  };
  socket.addEventListener("message", (event: MessageEvent) => {
    if (typeof event.data !== "string") return;
    full(`ws_in ws=${ws}`, event.data);
    const head = event.data.slice(0, HEAD);
    const method = pick(head, /"method"\s*:\s*"([\w.\-/]{1,64})"/);
    if (method) {
      const type = method === "event" ? pick(head, /"type"\s*:\s*"([\w.\-]{1,64})"/) ?? "unknown" : method;
      events[type] = (events[type] ?? 0) + 1;
      return;
    }
    const rid = pick(head, /"id"\s*:\s*"?([\w-]{1,64})"?/);
    const request = rid === undefined ? undefined : pending.get(rid);
    if (!request || rid === undefined) return;
    pending.delete(rid);
    // A top-level "error" comes before any "result"; a nested "error" inside a result is data.
    const errorAt = head.indexOf('"error"');
    const resultAt = head.indexOf('"result"');
    const failed = errorAt >= 0 && (resultAt < 0 || errorAt < resultAt);
    const code = failed ? pick(head.slice(errorAt, errorAt + 80), /"code"\s*:\s*(-?\d{1,6})/) ?? "?" : undefined;
    diag("rpc", { ws, method: request.method, ms: now() - request.at, ok: code === undefined, code });
  });
  const flush = () => {
    const entries = Object.entries(events);
    if (!entries.length) return;
    diag("rpc_events", { ws, ...Object.fromEntries(entries.slice(0, 20)), types: entries.length });
    events = {};
  };
  const timer = setInterval(flush, RPC_SUMMARY_MS);
  socket.addEventListener("close", () => {
    flush();
    clearInterval(timer);
    if (pending.size) diag("rpc_unanswered", { ws, count: pending.size, methods: [...new Set([...pending.values()].map(p => p.method))].slice(0, 5).join(",") });
    pending.clear();
  });
}

type Readable<T> = { get(): T; listen(listener: (value: T) => void): () => void };

/** Logs each change of Desktop's gateway connection state (the status bar's Backend item). */
export function watchGatewayState(store: Readable<string>, now: () => number = () => Date.now()): () => void {
  let state = store.get();
  let since = now();
  diag("gateway_state", { state });
  return store.listen(value => {
    if (value === state) return;
    const at = now();
    diag("gateway_state", { state: value, from: state, after_ms: at - since });
    state = value;
    since = at;
  });
}
