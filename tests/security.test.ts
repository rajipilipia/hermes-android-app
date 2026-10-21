import { describe, it, expect } from "vitest";
import { gatewayUrl } from "../src/security";
describe("endpoint security", () => {
  it("uses WSS and refuses credentials in endpoint URLs", () => {
    expect(gatewayUrl("wss://hermes.example/ws", "", false)).toBe(
      "wss://hermes.example/ws",
    );
    expect(() => gatewayUrl("ws://hermes.example/ws", "", false)).toThrow();
    expect(() =>
      gatewayUrl("wss://user:pass@hermes.example/ws", "", false),
    ).toThrow();
  });
});
