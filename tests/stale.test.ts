import { it, expect } from "vitest";
import { ChatController } from "../src/chat";
import { Peer } from "./fixture";
it("disconnect fences an outstanding create reply from publishing into another connection", async () => {
  const p = new Peer(),
    c = new ChatController(p.client());
  await c.connect("wss://example.test/ws", "");
  const pending = c.create();
  c.disconnect();
  await pending.catch(() => {});
  expect(c.state.runtimeId).toBe("");
  expect(c.state.error).toBe("");
  expect(c.state.syncing).toBe(false);
});
it("changing session selection before a prompt response fails cannot mark the new session uncertain", async () => {
  const p = new Peer(),
    c = new ChatController(p.client());
  await c.connect("wss://example.test/ws", "");
  await c.open("stored-1");
  p.failPrompt = true;
  const pending = c.send("one");
  c.disconnect();
  await pending;
  expect(c.state.uncertain).toBe(false);
  expect(c.state.error).toBe("");
});
