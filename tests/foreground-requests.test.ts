// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { pcAuth } from "../src/pc-auth";
import { nativeRest } from "../src/desktop/native-api";
import { capabilityCall } from "../src/desktop/capabilities";

const lifecycle = (state: "pause" | "resume") => window.dispatchEvent(new CustomEvent("hermes:native-lifecycle", { detail: { state } }));
afterEach(() => { lifecycle("resume"); vi.restoreAllMocks(); vi.useRealTimers(); delete window.HermesPc; delete window.HermesApi; });

it("does not send a ticket or REST call to native while hidden, even for long background stays", async () => {
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  const ticket = vi.fn((id: string) => window.__hermesPcResult!(id, true, "synthetic-ticket"));
  const rest = vi.fn((id: string) => window.__hermesApiResult!(id, true, JSON.stringify({ status: 200, body: "{}" })));
  window.HermesPc = { request: ticket }; window.HermesApi = { call: rest };
  await expect(pcAuth.ticket()).rejects.toMatchObject({ name: "PcForegroundRequired" });
  await expect(nativeRest(capabilityCall({ path: "/api/profiles/active" }))).rejects.toMatchObject({ name: "PcForegroundRequired" });
  expect(ticket).not.toHaveBeenCalled(); expect(rest).not.toHaveBeenCalled();
});

it("honors native pause even with a visible document and sends only fresh requests after return", async () => {
  vi.useFakeTimers();
  const ticket = vi.fn((id: string) => window.__hermesPcResult!(id, true, "synthetic-ticket"));
  const rest = vi.fn((id: string) => window.__hermesApiResult!(id, true, JSON.stringify({ status: 200, body: "{}" })));
  window.HermesPc = { request: ticket }; window.HermesApi = { call: rest };
  await pcAuth.ticket();
  lifecycle("pause");
  await expect(pcAuth.ticket()).rejects.toMatchObject({ name: "PcForegroundRequired" });
  await expect(nativeRest(capabilityCall({ path: "/api/profiles/active" }))).rejects.toMatchObject({ name: "PcForegroundRequired" });
  await vi.advanceTimersByTimeAsync(180_000);
  lifecycle("resume"); lifecycle("resume");
  expect(ticket).toHaveBeenCalledTimes(1); expect(rest).not.toHaveBeenCalled();
  await pcAuth.ticket(); await nativeRest(capabilityCall({ path: "/api/profiles/active" }));
  expect(ticket).toHaveBeenCalledTimes(2); expect(rest).toHaveBeenCalledTimes(1);
});

it("distinguishes native foreground deferral from rejected login without automatic retry", async () => {
  const ticket = vi.fn((id: string) => window.__hermesPcResult!(id, false, "PC_FOREGROUND_REQUIRED"));
  const rest = vi.fn((id: string) => window.__hermesApiResult!(id, false, "PC_FOREGROUND_REQUIRED"));
  window.HermesPc = { request: ticket }; window.HermesApi = { call: rest };
  await expect(pcAuth.ticket()).rejects.toMatchObject({ name: "PcForegroundRequired" });
  await expect(nativeRest(capabilityCall({ path: "/api/profiles/active" }))).rejects.toMatchObject({ name: "PcForegroundRequired" });
  lifecycle("pause"); lifecycle("resume");
  expect(ticket).toHaveBeenCalledTimes(1); expect(rest).toHaveBeenCalledTimes(1);
  ticket.mockImplementation(id => window.__hermesPcResult!(id, false, "PC_SIGN_IN_REQUIRED"));
  await expect(pcAuth.ticket()).rejects.toMatchObject({ name: "PcSignInRequired" });
});

it("never replays already-dispatched ticket or REST work after a timeout and late callback", async () => {
  vi.useFakeTimers();
  const ticket = vi.fn(), rest = vi.fn();
  window.HermesPc = { request: ticket }; window.HermesApi = { call: rest };
  const failedTicket = expect(pcAuth.ticket()).rejects.toThrow("timed out");
  const failedRest = expect(nativeRest(capabilityCall({ path: "/api/profiles/active" }))).rejects.toThrow("did not answer");
  lifecycle("pause");
  await vi.advanceTimersByTimeAsync(180_000);
  await failedTicket; await failedRest;
  lifecycle("resume");
  window.__hermesPcResult!(ticket.mock.calls[0][0], true, "late-synthetic-ticket");
  window.__hermesApiResult!(rest.mock.calls[0][0], true, JSON.stringify({ status: 200, body: "{}" }));
  expect(ticket).toHaveBeenCalledTimes(1); expect(rest).toHaveBeenCalledTimes(1);
});
