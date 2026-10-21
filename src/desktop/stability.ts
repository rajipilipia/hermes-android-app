// Connection stability diagnostics for phone rounds (NG-4, 2026-10-20). Observe only: nothing
// here changes when or how the renderer connects. Lines go through diag() (logcat HermesDiag)
// and carry counts, codes and milliseconds only, never the URL, ticket or close reason text.
import { diag } from "./diag";

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
