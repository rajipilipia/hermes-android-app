import { it, expect } from "vitest";
import { gatewayUrl } from "../src/security";
it("permits only explicit debug loopback / emulator cleartext, never LAN or lookalikes", () => {
  for (const host of ["127.0.0.1", "localhost", "10.0.2.2"]) {
    expect(gatewayUrl(`ws://${host}:18765/ws`, "", true)).toBe(
      `ws://${host}:18765/ws`,
    );
    expect(() => gatewayUrl(`ws://${host}:18765/ws`, "", false)).toThrow();
  }
  for (const host of [
    "192.168.1.2",
    "localhost.example",
    "127.1",
    "2130706433",
    "0x7f000001",
    "[::1]",
    "10.0.2.3",
  ])
    expect(() => gatewayUrl(`ws://${host}/ws`, "", true)).toThrow();
  expect(gatewayUrl("wss://hermes.example/ws", "a+b &?", false)).toBe(
    "wss://hermes.example/ws?token=a%2Bb+%26%3F",
  );
});
