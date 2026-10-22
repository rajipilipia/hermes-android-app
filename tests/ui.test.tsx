// @vitest-environment jsdom
import { it, expect } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { App } from "../src/App";
import { ChatController } from "../src/chat";
import { Peer } from "./fixture";
it("phone UI connects, lists sessions, creates and sends an explicit prompt and renders stream text safely", async () => {
  const peer = new Peer(),
    controller = new ChatController(peer.client());
  render(<App controller={controller} />);
  fireEvent.click(screen.getByText("Manual / debug connection"));
  fireEvent.change(screen.getByLabelText("Gateway endpoint"), {
    target: { value: "wss://example.test/ws" },
  });
  fireEvent.change(screen.getByLabelText("Access token"), {
    target: { value: "memory-only" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Connect" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Saved chat" })).toBeTruthy(),
  );
  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  await waitFor(() => expect(controller.state.runtimeId).toBe("new-runtime"));
  fireEvent.change(screen.getByLabelText("Message Hermes"), {
    target: { value: "Hello Hermes" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await waitFor(() =>
    expect(peer.calls.some((c) => c.method === "prompt.submit")).toBe(true),
  );
  peer.emit(
    "message.delta",
    { text: "<script>not executable</script>" },
    "new-runtime",
  );
  await waitFor(() =>
    expect(screen.getByText("<script>not executable</script>")).toBeTruthy(),
  );
  expect(document.querySelector("script")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Connection settings" }));
  fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
  expect(controller.state.connected).toBe(false);
  expect(
    (screen.getByLabelText("Access token") as HTMLInputElement).value,
  ).toBe("");
  controller.disconnect();
  cleanup();
});
