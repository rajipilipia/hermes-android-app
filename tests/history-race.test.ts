import { it, expect } from "vitest";
import { ChatController } from "../src/chat";
import { Peer } from "./fixture";
it("does not lose a completion racing resume history hydration", async () => {
  const p = new Peer(),
    base = p.respond.bind(p);
  p.respond = (method, params) => {
    if (method === "session.resume")
      return {
        session_id: "runtime-1",
        stored_session_id: "stored-1",
        messages: [],
        message_count: 0,
        info: {},
        running: true,
        inflight: { user: "Question", assistant: "Part ", streaming: true },
      };
    if (method === "session.history") {
      p.emit("message.delta", { text: "two" });
      p.emit("message.complete", { text: "Part two" });
      return { count: 1, messages: [{ role: "user", text: "Question" }] };
    }
    return base(method, params);
  };
  const c = new ChatController(p.client());
  await c.connect("wss://example.test/ws", "");
  await c.open("stored-1");
  expect(c.state.busy).toBe(false);
  expect(c.state.messages.map((m) => m.text)).toEqual(["Question", "Part two"]);
  c.disconnect();
});
