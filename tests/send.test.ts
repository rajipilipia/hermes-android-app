import { it, expect } from "vitest";
import { ChatController } from "../src/chat";
import { Peer } from "./fixture";
it("creates a new session, submits once and streams only matching reply chunks", async () => {
  const p = new Peer(),
    c = new ChatController(p.client());
  await c.connect("wss://example.test/ws", "");
  await c.create();
  expect(c.state.runtimeId).toBe("new-runtime");
  await c.send("Test prompt");
  expect(p.calls.filter((x) => x.method === "prompt.submit")).toHaveLength(1);
  expect(p.calls.find((x) => x.method === "prompt.submit")?.params).toEqual({
    session_id: "new-runtime",
    text: "Test prompt",
    surface: "android-prototype",
  });
  p.emit("message.start", {}, "new-runtime");
  p.emit("message.delta", { text: "Wrong" }, "other");
  p.emit("message.delta", { text: "Hello " }, "new-runtime");
  p.emit("message.delta", { text: "phone" }, "new-runtime");
  expect(c.state.messages.at(-1)?.text).toBe("Hello phone");
  p.emit(
    "message.complete",
    { text: "Hello phone", error: null },
    "new-runtime",
  );
  expect(c.state.busy).toBe(false);
  expect(c.state.messages.map((m) => m.text)).toEqual([
    "Test prompt",
    "Hello phone",
  ]);
  c.disconnect();
});
