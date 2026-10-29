// @vitest-environment jsdom
import { expect, it } from "vitest";
import { ensureGatewayForAgent, requestGatewayForAgent } from "../vendor/hermes/apps/desktop/src/store/gateway";

// The phone host has no Electron getConnectionFor door. A chat owned by the explicit `local` source must
// still take the profile route; before the phone-connection-scope adapter these threw at once.
it("does not treat the phone's local owner as an undialable registry connection", async () => {
  expect(window.hermesDesktop?.getConnectionFor).toBeUndefined();
  const registry = /cannot dial registry connections/;
  const request = await requestGatewayForAgent("local", "example-profile", "session.status", {}, 50).then(() => null, (error: Error) => error);
  expect(String(request?.message ?? "")).not.toMatch(registry);
  const ensure = await ensureGatewayForAgent("local", "example-profile").then(() => null, (error: Error) => error);
  expect(String(ensure?.message ?? "")).not.toMatch(registry);
});
