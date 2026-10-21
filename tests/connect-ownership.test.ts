import { it, expect } from "vitest";
import { ChatController } from "../src/chat";
import { Peer } from "./fixture";
it("disconnect during initial list hydration cannot republish a connected state", async () => {
  const peer = new Peer(),
    base = peer.respond.bind(peer),
    controller = new ChatController(peer.client());
  peer.respond = (method, params) => {
    if (method === "session.list")
      queueMicrotask(() => controller.disconnect());
    return base(method, params);
  };
  await controller.connect("wss://example.test/ws", "");
  expect(controller.state.connected).toBe(false);
  expect(controller.state.status).toBe("offline");
});
