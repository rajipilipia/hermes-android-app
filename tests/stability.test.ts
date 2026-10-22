// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { installSocketDiag, watchGatewayState } from "../src/desktop/stability";

const win = window as Window & typeof globalThis;
const Original = win.WebSocket;
let clock = 1_000;
const now = () => clock;
let lines: string[];

class FakeSocket extends EventTarget {
  static OPEN = 1;
  constructor(public url: string | URL, public protocols?: string | string[]) {
    super();
  }
}

beforeEach(() => {
  clock = 1_000;
  lines = [];
  vi.spyOn(console, "info").mockImplementation((line: string) => void lines.push(line));
  win.WebSocket = FakeSocket as unknown as typeof WebSocket;
});
afterEach(() => {
  win.WebSocket = Original;
  vi.restoreAllMocks();
});

const close = (code: number, wasClean = code === 1000) =>
  Object.assign(new Event("close"), { code, wasClean });

it("logs gateway socket open, drop and reconnect with timings, never the URL or ticket", () => {
  const diag = installSocketDiag(win, now);
  try {
    const first = new win.WebSocket("wss://hermes.example/api/ws?ticket=SECRETTICKETVALUE123456789");
    expect(first).toBeInstanceOf(FakeSocket);
    expect(win.WebSocket.OPEN).toBe(1);
    clock += 250;
    first.dispatchEvent(new Event("open"));
    clock += 60_000;
    first.dispatchEvent(close(1006));
    const second = new win.WebSocket("wss://hermes.example/api/ws?ticket=OTHERTICKETVALUE12345678");
    clock += 1_500;
    second.dispatchEvent(new Event("open"));
    expect(lines).toEqual([
      "[hermes-diag] ws_open id=1 connect_ms=250 opens=1",
      "[hermes-diag] ws_close id=1 code=1006 clean=false up_ms=60000 never_opened=false abnormal=1",
      "[hermes-diag] ws_open id=2 connect_ms=1500 since_close_ms=1500 opens=2",
    ]);
    expect(diag.counters).toEqual({ opens: 2, closes: 1, abnormal: 1, errors: 0, open: 1 });
    expect(lines.join("\n")).not.toMatch(/TICKET|example/);
  } finally {
    diag.dispose();
  }
  expect(win.WebSocket).toBe(FakeSocket);
});

it("ignores sockets that are not the Hermes gateway and counts a normal close as normal", () => {
  const diag = installSocketDiag(win, now);
  try {
    const other = new win.WebSocket("wss://hermes.example/other");
    other.dispatchEvent(new Event("open"));
    const gateway = new win.WebSocket("/api/ws");
    gateway.dispatchEvent(new Event("error"));
    gateway.dispatchEvent(close(1000));
    expect(lines).toEqual([
      "[hermes-diag] ws_error id=1 opened=false",
      "[hermes-diag] ws_close id=1 code=1000 clean=true never_opened=true abnormal=0",
    ]);
    expect(diag.counters).toEqual({ opens: 0, closes: 1, abnormal: 0, errors: 1, open: 0 });
  } finally {
    diag.dispose();
  }
});

it("logs a five-minute summary and network changes", () => {
  vi.useFakeTimers();
  const diag = installSocketDiag(win, now);
  try {
    win.dispatchEvent(new Event("offline"));
    vi.advanceTimersByTime(5 * 60_000);
    expect(lines.at(-1)).toBe("[hermes-diag] ws_summary opens=0 closes=0 abnormal=0 errors=0 open=0");
    expect(lines[0]).toMatch(/^\[hermes-diag\] network online=/);
  } finally {
    diag.dispose();
    vi.useRealTimers();
  }
});

it("logs each Backend connection state change with the time spent in the previous state", () => {
  let listener: ((value: string) => void) | undefined;
  let value = "idle";
  const store = { get: () => value, listen: (next: (value: string) => void) => ((listener = next), () => (listener = undefined)) };
  const stop = watchGatewayState(store, now);
  clock += 3_000;
  listener?.("connecting");
  listener?.("connecting");
  clock += 900;
  listener?.("open");
  stop();
  expect(listener).toBeUndefined();
  expect(lines).toEqual([
    "[hermes-diag] gateway_state state=idle",
    "[hermes-diag] gateway_state state=connecting from=idle after_ms=3000",
    "[hermes-diag] gateway_state state=open from=connecting after_ms=900",
  ]);
});
