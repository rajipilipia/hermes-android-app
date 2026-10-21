import { it, expect } from "vitest";
import { ChatController } from "../src/chat";
import { Peer } from "./fixture";
it("does not duplicate a final assistant reply already committed while history was fetched", async () => {
  const p = new Peer(),
    base = p.respond.bind(p);
  p.respond = (method, params) => {
    if (method === "session.resume")
      return {
        session_id: "runtime-1",
        stored_session_id: "stored-1",
        messages: [],
        message_count: 1,
        info: {},
        running: true,
        inflight: { user: "Question", assistant: "Part ", streaming: true },
      };
    if (method === "session.history") {
      p.emit("message.delta", { text: "two" });
      p.emit("message.complete", { text: "Part two" });
      return {
        count: 2,
        messages: [
          { role: "user", text: "Question", row_id: 1 },
          { role: "assistant", text: "Part two", row_id: 2 },
        ],
      };
    }
    return base(method, params);
  };
  const c = new ChatController(p.client());
  await c.connect("wss://example.test/ws", "");
  await c.open("stored-1");
  expect(c.state.messages.map((m) => m.text)).toEqual(["Question", "Part two"]);
  expect(c.state.busy).toBe(false);
  c.disconnect();
});
