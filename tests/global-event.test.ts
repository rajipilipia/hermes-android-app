import { it, expect } from "vitest";
import { ChatController } from "../src/chat";
import { Peer } from "./fixture";
it("global gateway notifications without a session are not transcript events", async () => {
  const p = new Peer(),
    c = new ChatController(p.client());
  await c.connect("wss://example.test/ws", "");
  expect(() =>
    p.sockets
      .at(-1)
      ?.frame({
        method: "event",
        params: {
          type: "gateway.ready",
          payload: { heartbeat: false, replay_epoch: "epoch" },
        },
      }),
  ).not.toThrow();
  expect(c.state.messages).toEqual([]);
  c.disconnect();
});
