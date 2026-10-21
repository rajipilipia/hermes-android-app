import { it, expect } from "vitest";
import { ChatController } from "../src/chat";
import { Peer } from "./fixture";
it("lists stored sessions and opens the returned runtime ID with authoritative history", async () => {
  const peer = new Peer(),
    chat = new ChatController(peer.client());
  await chat.connect("wss://example.test/ws", "memory-token");
  expect(chat.state.sessions[0].id).toBe("stored-1");
  await chat.open("stored-1");
  expect(chat.state.runtimeId).toBe("runtime-1");
  expect(chat.state.storedId).toBe("stored-1");
  expect(chat.state.messages.map((m: { text: string }) => m.text)).toEqual([
    "hello",
    "Hello back",
  ]);
  expect(
    peer.calls.find((c) => c.method === "session.resume")?.params.session_id,
  ).toBe("stored-1");
  expect(peer.calls.some((c) => c.method === "session.history")).toBe(true);
  chat.disconnect();
});
