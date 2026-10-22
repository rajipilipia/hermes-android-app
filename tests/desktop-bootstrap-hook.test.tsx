// @vitest-environment jsdom
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { installDesktopHost } from "../src/desktop/host";
import { useGatewayBoot } from "../vendor/hermes/apps/desktop/src/app/gateway/hooks/use-gateway-boot";
import { takeGatewaySurvivor } from "../vendor/hermes/apps/desktop/src/app/gateway/hooks/gateway-hmr-survivor";
import { $desktopBoot } from "../vendor/hermes/apps/desktop/src/store/boot";
import { $activeGatewayProfile, $profiles, refreshActiveProfile } from "../vendor/hermes/apps/desktop/src/store/profile";
import { $connection, $currentCwd, setConnection } from "../vendor/hermes/apps/desktop/src/store/session";
import { closeSecondaryGateways, setPrimaryGateway } from "../vendor/hermes/apps/desktop/src/store/gateway";
import { getProfiles } from "../vendor/hermes/apps/desktop/src/api/profiles";
import { getStatus } from "../vendor/hermes/apps/desktop/src/api/config";
import { setApiRequestProfile, setApiRequestConnection } from "../vendor/hermes/apps/desktop/src/api/client";

// Unrelated terminal probing is optional UI work, not part of owner discovery.
vi.mock("../vendor/hermes/apps/desktop/src/store/terminal-backend-warning", () => ({ warnIfTerminalBackendUnavailable: vi.fn(async () => false) }));

const calls: { method: string; params: Record<string, unknown> }[] = [];
class NamedOnlySocket extends EventTarget {
  static OPEN = 1;
  static CLOSED = 3;
  static instances: NamedOnlySocket[] = [];
  readyState = 0;
  constructor(readonly url: string) {
    super();
    NamedOnlySocket.instances.push(this);
    queueMicrotask(() => { if (this.readyState === 3) return; this.readyState = 1; this.dispatchEvent(new Event("open")); });
  }
  send(raw: string) {
    const frame = JSON.parse(raw);
    if (!frame.method) return;
    calls.push({ method: frame.method, params: frame.params ?? {} });
    let result: unknown;
    if (frame.method.startsWith("desktop.")) throw new Error("native-only host must not use a PC add-on");
    if (frame.method === "ping") result = { pong: true };
    else if (frame.method === "session.events.since") result = { events: [], count: 0, latest_seq: 0, epoch: "fixture", open_requests: [] };
    else result = {};
    queueMicrotask(() => this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({ jsonrpc: "2.0", id: frame.id, result }) })));
  }
  close() {
    if (this.readyState === 3) return;
    this.readyState = 3;
    this.dispatchEvent(Object.assign(new Event("close"), { code: 1000 }));
  }
}
// Hermes's own REST through the native bridge (synthetic fixtures), scoped to the server's "research" profile.
const restCalls: Record<string, unknown>[] = [];
const fixtures: Record<string, unknown> = {
  "GET /api/status": { version: "fixture", gateway_running: true, gateway_state: "running" },
  "GET /api/profiles": { profiles: [{ name: "research", is_default: false }] },
  "GET /api/profiles/active": { active: "research", current: "research" },
  "GET /api/fs/default-cwd": { cwd: "C:\\synthetic-workspace", branch: "" },
  "GET /api/config": { config: {} },
};
const rest = async (params: Record<string, unknown>) => {
  restCalls.push(params);
  // The primary lookup comes before any owner is known.
  if (params.operation === "GET /api/profiles/active" && restCalls.length === 1) return { status: 200, body: fixtures["GET /api/profiles/active"] };
  return params.profile === "research"
    ? { status: 200, body: fixtures[String(params.operation)] ?? {} }
    : { status: 403, body: { detail: "principal/profile permission denied" } };
};
let host: ReturnType<typeof installDesktopHost> | undefined;
afterEach(() => {
  cleanup();
  takeGatewaySurvivor()?.gateway.close();
  closeSecondaryGateways();
  setPrimaryGateway(null);
  host?.dispose(); host = undefined;
  for (const socket of NamedOnlySocket.instances) socket.close();
  NamedOnlySocket.instances = [];
  calls.length = 0;
  restCalls.length = 0;
  setConnection(null);
  setApiRequestProfile(null); setApiRequestConnection(null);
  $profiles.set([]); $currentCwd.set("");
  delete (window as unknown as { hermesDesktop?: unknown }).hermesDesktop;
  vi.unstubAllGlobals();
});

it("the genuine useGatewayBoot cold flow obtains research from Hermes's own API through the native host, with one socket", async () => {
  vi.stubGlobal("WebSocket", NamedOnlySocket);
  takeGatewaySurvivor()?.gateway.close();
  setConnection(null);
  setApiRequestProfile(null); setApiRequestConnection(null);
  $profiles.set([]); $currentCwd.set("");
  const credentials = { signIn: vi.fn(async () => {}), signOut: vi.fn(), ticket: vi.fn(async () => "synthetic-one-use-ticket") };
  host = installDesktopHost({ auth: credentials, rest: rest as never });
  const descriptor = vi.spyOn(host, "getConnection");
  const ready = vi.fn();
  const refresh = vi.fn(async () => { await Promise.all([getProfiles(), refreshActiveProfile(), getStatus()]); });
  function Harness() {
    useGatewayBoot({ beforeConnectionSwitch: () => {}, handleGatewayEvent: () => {}, handleServerRequest: () => false,
      onConnectionReady: ready, onGatewayReady: () => {}, refreshHermesConfig: refresh, refreshSessions: async () => {} });
    return null;
  }
  await act(async () => { render(<Harness />); });
  await waitFor(() => expect($desktopBoot.get().running).toBe(false));
  expect($desktopBoot.get().error).toBeNull();
  expect(descriptor).toHaveBeenCalledWith(undefined); // actual optional getDefault fallback, no copied getWindowBackend logic
  expect(ready).toHaveBeenCalledWith(expect.objectContaining({ profile: "research", sharedPrimary: true, token: "", wsUrl: "" }));
  expect($connection.get()?.profile).toBe("research");
  expect($activeGatewayProfile.get()).toBe("research");
  expect(refresh).toHaveBeenCalledTimes(1);
  expect(restCalls[0]).toEqual({ operation: "GET /api/profiles/active", profile: "default", pathParams: {}, query: {} });
  for (const operation of ["GET /api/profiles", "GET /api/profiles/active", "GET /api/fs/default-cwd"])
    expect(restCalls.slice(1)).toContainEqual({ operation, profile: "research", pathParams: {}, query: {} });
  expect(restCalls.slice(1).every(call => call.profile === "research")).toBe(true);
  await expect(getProfiles("default")).rejects.toThrow("403");
  expect(restCalls.at(-1)?.profile).toBe("default");
  expect(calls.some(call => call.method.startsWith("desktop."))).toBe(false);
  expect(credentials.ticket).toHaveBeenCalledTimes(1); // only Desktop's own chat socket
});
