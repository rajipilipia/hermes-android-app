import { it, expect, vi } from "vitest";
import { ChatController } from "../src/chat";
import { Peer } from "./fixture";
it("reconnects, resumes stored ID, reconciles history and NEVER resends an ambiguous prompt", async () => {
  vi.useFakeTimers();
  const p = new Peer(),
    c = new ChatController(p.client(), 50);
  await c.connect("wss://example.test/ws", "memory-only");
  await c.open("stored-1");
  p.failPrompt = true;
  await c.send("Do not repeat me");
  expect(c.state.uncertain).toBe(true);
  expect(c.state.connected).toBe(false);
  p.failPrompt = false;
  await vi.advanceTimersByTimeAsync(60);
  expect(p.sockets.length).toBe(2);
  expect(c.state.connected).toBe(true);
  expect(
    p.calls
      .filter((x) => x.method === "session.resume")
      .map((x) => x.params.session_id),
  ).toEqual(["stored-1", "stored-1"]);
  expect(p.calls.filter((x) => x.method === "prompt.submit")).toHaveLength(1);
  expect(c.state.messages.at(-1)?.text).toBe("Hello back");
  c.disconnect();
  await vi.advanceTimersByTimeAsync(1000);
  expect(p.sockets.length).toBe(2);
  vi.useRealTimers();
});
