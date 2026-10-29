// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { trackRpc } from "../src/desktop/stability";
import { controlName, installVerboseLogging, routeShape } from "../src/desktop/verbose";
import { redactSecrets } from "../src/desktop/diag";

let lines: string[];
beforeEach(() => {
  lines = [];
  vi.spyOn(console, "info").mockImplementation((line: string) => void lines.push(line));
});
afterEach(() => vi.restoreAllMocks());

class FakeSocket extends EventTarget {
  sent: string[] = [];
  send(data: string) { this.sent.push(data); }
  receive(data: string) { this.dispatchEvent(Object.assign(new Event("message"), { data })); }
}

it("logs each RPC with method, time and result, never params or results", () => {
  let clock = 100;
  const socket = new FakeSocket();
  trackRpc(socket as unknown as WebSocket, 3, () => clock);
  socket.send(JSON.stringify({ jsonrpc: "2.0", id: "r1", method: "prompt.submit", params: { text: "secret words" } }));
  socket.send(JSON.stringify({ jsonrpc: "2.0", id: "r2", method: "session.resume", params: {} }));
  clock = 160;
  socket.receive(JSON.stringify({ jsonrpc: "2.0", id: "r1", result: { note: "an \"error\": inside data" } }));
  socket.receive(JSON.stringify({ jsonrpc: "2.0", id: "r2", error: { code: -32001, message: "private detail" } }));
  expect(socket.sent).toHaveLength(2);
  expect(lines.filter(line => line.startsWith("[hermes-diag]"))).toEqual([
    "[hermes-diag] rpc ws=3 method=prompt.submit ms=60 ok=true",
    "[hermes-diag] rpc ws=3 method=session.resume ms=60 ok=false code=-32001",
  ]);
  expect(lines.filter(line => line.startsWith("[hermes-diag]")).join(" ")).not.toMatch(/secret|private/);
});

it("dev phone: logs every frame in full with secrets masked", () => {
  const socket = new FakeSocket();
  trackRpc(socket as unknown as WebSocket, 2);
  socket.send(JSON.stringify({ jsonrpc: "2.0", id: "a", method: "prompt.submit", params: { text: "my chat words", access_token: "abcd1234efgh" } }));
  socket.receive(JSON.stringify({ jsonrpc: "2.0", method: "event", params: { type: "message.delta", text: "reply words" } }));
  const fullLines = lines.filter(line => line.startsWith("[hermes-full]"));
  expect(fullLines[0]).toMatch(/^\[hermes-full\] ws_out ws=2 len=\d+ .*my chat words/);
  expect(fullLines[0]).not.toContain("abcd1234efgh");
  expect(fullLines[1]).toContain("reply words");
});

it("dev phone: masks Bearer values, JWTs and secret fields but keeps text", () => {
  const out = redactSecrets('Authorization: Bearer abcdefghijklmnop {"password":"hunter22","text":"hello"} eyJhbGciOiJI.eyJzdWIiOiIx.c2lnbmF0dXJl');
  expect(out).toContain("hello");
  expect(out).not.toMatch(/abcdefghijklmnop|hunter22|c2lnbmF0dXJl/);
});

it("summarizes gateway events by type and reports unanswered requests on close", () => {
  vi.useFakeTimers();
  const socket = new FakeSocket();
  trackRpc(socket as unknown as WebSocket, 1);
  for (let i = 0; i < 3; i++) socket.receive(JSON.stringify({ jsonrpc: "2.0", method: "event", params: { type: "message.delta", payload: { text: "hi" } } }));
  socket.send(JSON.stringify({ jsonrpc: "2.0", id: "x", method: "voice.live" }));
  vi.advanceTimersByTime(10_000);
  socket.dispatchEvent(new Event("close"));
  vi.useRealTimers();
  expect(lines).toContain("[hermes-diag] rpc_events ws=1 message.delta=3 types=1");
  expect(lines).toContain("[hermes-diag] rpc_unanswered ws=1 count=1 methods=voice.live");
});

it("names icon controls by label and text controls only by length", () => {
  document.body.innerHTML = `<button aria-label="Open settings"><svg></svg></button><button aria-label="Rename my private chat">My private chat</button>`;
  const [icon, text] = document.querySelectorAll("button");
  expect(controlName(icon)).toMatchObject({ tag: "button", label: "Open settings" });
  expect(controlName(text)).toMatchObject({ label: undefined, text_len: 15 });
});

it("masks ids in routes and logs taps and route changes", () => {
  expect(routeShape({ location: { hash: "#/sessions/20261028_085558_68503c/files", pathname: "/" } } as unknown as Window)).toBe("/sessions/:id/files");
  const stop = installVerboseLogging(window as Window & typeof globalThis);
  document.body.innerHTML = `<button aria-label="New session tab"><svg></svg></button>`;
  document.querySelector("button")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  history.pushState(null, "", "#/settings");
  stop();
  expect(lines.some(line => line.startsWith("[hermes-diag] tap tag=button label=New session tab"))).toBe(true);
  expect(lines.some(line => line.includes("route from=") && line.includes("to=/settings"))).toBe(true);
});
