import { it, expect } from "vitest";
import { ChatController } from "../src/chat";
import { Peer } from "./fixture";
it("rebuilds an in-progress reply from resume inflight and continues the same bubble", async () => {
  const p = new Peer(),
    base = p.respond.bind(p);
  p.respond = (method, params) =>
    method === "session.resume"
      ? {
          session_id: "runtime-1",
          stored_session_id: "stored-1",
          messages: [],
          message_count: 0,
          info: {},
          running: true,
          inflight: {
            user: "Current question",
            assistant: "Part ",
            streaming: true,
          },
        }
      : base(method, params);
  const c = new ChatController(p.client());
  await c.connect("wss://example.test/ws", "");
  await c.open("stored-1");
  expect(c.state.messages.map((m) => m.text)).toEqual([
    "hello",
    "Hello back",
    "Current question",
    "Part ",
  ]);
  p.emit("message.delta", { text: "two" });
  expect(c.state.messages.at(-1)?.text).toBe("Part two");
  expect(c.state.messages).toHaveLength(4);
  p.emit("message.complete", { text: "Part two" });
  expect(c.state.busy).toBe(false);
  c.disconnect();
});
