// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { createDesktopHost } from "../src/desktop/host";
const auth = () => ({
  signIn: vi.fn(async () => {}),
  ticket: vi.fn(async () => "one-use"),
  signOut: vi.fn(),
});
type Params = { operation: string; profile: string; pathParams: Record<string, unknown>; query: Record<string, unknown>; body?: unknown };
/** Synthetic Hermes REST (the native HermesApi bridge's shape); not a live server result. */
const server = (reply: (params: Params) => { status: number; body: unknown } = () => ({ status: 200, body: {} }), current = "work") =>
  vi.fn(async (params: Params, _timeoutMs?: number) =>
    params.operation === "GET /api/profiles/active" ? { status: 200, body: { active: "default", current } } : reply(params));
describe("native-only Desktop host (Hermes's own API, no PC add-on)", () => {
  it("maps the pinned startup status request without changing its projected DTO", async () => {
    const status = { version: "fixture-version", gateway_running: true, gateway_state: "running" };
    const rest = server(() => ({ status: 200, body: status }));
    const host = createDesktopHost({ auth: auth(), rest });
    expect(await host.api({ path: "/api/status", profile: "example-profile" })).toBe(status);
    expect(rest).toHaveBeenCalledExactlyOnceWith(
      { operation: "GET /api/status", profile: "example-profile", pathParams: {}, query: {} },
      undefined,
    );
  });
  it("names the primary from the server's current profile, like Desktop's remote mode", async () => {
    const rest = server(() => ({ status: 200, body: { profiles: [{ name: "work" }] } }));
    const host = createDesktopHost({ auth: auth(), rest });
    expect(await host.bootstrap()).toBe("work");
    expect(await host.api({ path: "/api/profiles" })).toEqual({ profiles: [{ name: "work" }] });
    // The captured primary owns unscoped calls; the request is the validated capabilityCall shape only.
    expect(rest.mock.calls.map(([params]) => [params.operation, params.profile])).toEqual([
      ["GET /api/profiles/active", "default"],
      ["GET /api/profiles", "work"],
    ]);
    expect(JSON.stringify(rest.mock.calls)).not.toMatch(/https?:|authorization|ticket/i);
  });
  it("shares one primary lookup between concurrent callers and asks again after a failure", async () => {
    let fail = true;
    const rest = vi.fn(async (params: Params) => {
      if (params.operation !== "GET /api/profiles/active") return { status: 200, body: { profiles: [] } };
      if (fail) return { status: 503, body: {} };
      return { status: 200, body: { current: "research" } };
    });
    const host = createDesktopHost({ auth: auth(), rest });
    await expect(host.bootstrap()).rejects.toThrow("profile lookup failed (503)");
    fail = false;
    await expect(Promise.all([host.bootstrap(), host.api({ path: "/api/profiles" }), host.getConnection()])).resolves.toMatchObject([
      "research", { profiles: [] }, { profile: "research" },
    ]);
    expect(rest.mock.calls.filter(([p]) => p.operation === "GET /api/profiles/active")).toHaveLength(2);
  });
  it("does not guess a primary when the server cannot name its profile", async () => {
    const rest = vi.fn(async () => ({ status: 200, body: { active: "default" } }));
    const host = createDesktopHost({ auth: auth(), rest });
    await expect(host.bootstrap()).rejects.toThrow("profile lookup failed");
  });
  it("uses no PC add-on: never a desktop.* RPC, never a second socket", async () => {
    const WebSocket = vi.fn();
    vi.stubGlobal("WebSocket", WebSocket);
    const rest = server(() => ({ status: 200, body: { profiles: [] } }));
    const host = createDesktopHost({ auth: auth(), rest });
    await host.api({ path: "/api/profiles" });
    expect(WebSocket).not.toHaveBeenCalled();
    expect(JSON.stringify(rest.mock.calls)).not.toContain("desktop.");
    expect(host).not.toHaveProperty("androidMedia");
    vi.unstubAllGlobals();
  });
  it("returns credential-free shared remote descriptors with explicit profile ownership", async () => {
    const credentials = auth();
    const host = createDesktopHost({ auth: credentials });
    const descriptor = await (host.getConnection as (profile: string) => Promise<unknown>)("example-profile");
    expect(descriptor).toMatchObject({
      mode: "remote", authMode: "oauth", token: "", wsUrl: "", profile: "example-profile", sharedPrimary: true, nativeOverlayWidth: 0,
    });
    expect(credentials.ticket).not.toHaveBeenCalled();
  });
  it("mints a fresh one-use ticket on every socket dial and never exposes a cached authenticated URL", async () => {
    const credentials = auth();
    credentials.ticket.mockResolvedValueOnce("ticket-1").mockResolvedValueOnce("ticket-2");
    const host = createDesktopHost({ auth: credentials, baseUrl: "https://gateway.example.com" });
    const first = new URL(await host.getGatewayWsUrl("example-profile"));
    const second = new URL(await host.getGatewayWsUrl("example-profile"));
    expect(first.protocol).toBe("wss:");
    expect(first.host).toBe("gateway.example.com");
    expect(first.pathname).toBe("/api/ws");
    expect(first.searchParams.get("ticket")).toBe("ticket-1");
    expect(second.searchParams.get("ticket")).toBe("ticket-2");
    expect(first.searchParams.has("token")).toBe(false);
    expect(JSON.stringify(await host.getConnection("example-profile"))).not.toContain("ticket-");
    credentials.ticket.mockRejectedValueOnce(new Error("sign in required"));
    await expect(host.getGatewayWsUrl("example-profile")).rejects.toThrow("sign in required");
  });
  it("an unscoped socket dial resolves the primary first, then mints its ticket", async () => {
    const credentials = auth();
    const rest = server();
    const host = createDesktopHost({ auth: credentials, baseUrl: "https://gateway.example.com", rest });
    expect(new URL(await host.getGatewayWsUrl()).searchParams.get("ticket")).toBe("one-use");
    expect(rest).toHaveBeenCalledTimes(1);
    expect(credentials.ticket).toHaveBeenCalledTimes(1);
  });
  it("provides truthful boot facts and inert subscriptions without advertising unsupported Electron capabilities", async () => {
    const host = createDesktopHost({ auth: auth() });
    expect(await host.getBootProgress()).toMatchObject({ fakeMode: false, running: false, phase: "ready", error: null });
    expect(await host.getBootstrapState()).toMatchObject({ active: false, bundled: false, manifest: null });
    for (const key of ["onBootProgress", "onBackendExit", "onPreviewFileChanged"]) {
      expect(typeof (host[key as keyof typeof host] as Function)(() => {})).toBe("function");
    }
    expect(host).toMatchObject({ glassSupported: false, translucencySupported: false, localModelsEnabled: false });
    expect(host).not.toHaveProperty("startInstaller");
    expect(host).not.toHaveProperty("openWindow");
    expect(host).not.toHaveProperty("connections");
  });
  it("sends only compiled contract operations with the captured profile and typed query", async () => {
    const rest = server(() => ({ status: 200, body: { sessions: [] } }));
    const host = createDesktopHost({ auth: auth(), rest });
    expect(await host.api({ path: "/api/sessions?limit=20&archived=exclude", profile: "example-profile" })).toEqual({ sessions: [] });
    expect(rest).toHaveBeenCalledExactlyOnceWith(
      { operation: "GET /api/sessions", profile: "example-profile", pathParams: {}, query: { limit: 20, archived: "exclude" } },
      undefined,
    );
    await expect(host.api({ path: "https://attacker.invalid/api/profiles" })).rejects.toThrow();
    await expect(host.api({ path: "/api/env/reveal", method: "POST", body: { key: "TEST" } })).rejects.toThrow();
    await expect(host.api({ path: "/api/profiles", connectionId: "other-pc" })).rejects.toThrow();
    await expect(host.api({ path: "/api/sessions?limit=NaN" })).rejects.toThrow();
    // Voice provider keys (voice-config) are not a contract operation: Desktop then uses its relay.
    await expect(host.api({ path: "/api/audio/voice-config", profile: "example-profile" })).rejects.toThrow();
    expect(rest).toHaveBeenCalledTimes(1);
  });
  it("voice and workspace uploads go to Hermes's own JSON routes", async () => {
    const rest = server((params) => ({ status: 200, body: params.operation === "POST /api/audio/speak"
      ? { ok: true, data_url: "data:audio/mpeg;base64,AAAA", mime_type: "audio/mpeg" }
      : { ok: true, transcript: "hello", provider: "local" } }));
    const host = createDesktopHost({ auth: auth(), rest });
    await host.api({ path: "/api/audio/transcribe", method: "POST", body: { data_url: "data:audio/webm;base64,AAAA", mime_type: "audio/webm" }, profile: "example-profile" });
    await host.api({ path: "/api/audio/speak", method: "POST", body: { text: "Hi" }, profile: "example-profile", timeoutMs: 60_000 });
    expect(rest.mock.calls.map(([p, t]) => [p.operation, t])).toEqual([["POST /api/audio/transcribe", undefined], ["POST /api/audio/speak", 60_000]]);
  });
  it("rejects non-success responses without exposing error bodies and fences disposed in-flight results", async () => {
    const host = createDesktopHost({ auth: auth(), rest: server(() => ({ status: 403, body: { detail: "private raw error" } })) });
    await expect(host.api({ path: "/api/profiles", profile: "research" })).rejects.toThrow("403");
    await expect(host.api({ path: "/api/profiles", profile: "research" })).rejects.not.toThrow("private raw error");
    let resolve!: (value: { status: number; body: unknown }) => void;
    const delayed = createDesktopHost({ auth: auth(), rest: vi.fn(() => new Promise<{ status: number; body: unknown }>((done) => { resolve = done; })) });
    const pending = delayed.api({ path: "/api/profiles", profile: "research" });
    const check = expect(pending).rejects.toThrow("closed");
    await vi.waitFor(() => expect(typeof resolve).toBe("function"));
    delayed.dispose();
    resolve({ status: 200, body: { profiles: [] } });
    await check;
  });
});

describe("connection after the phone was away", () => {
  const lifecycle = (state: string) => window.dispatchEvent(new CustomEvent("hermes:native-lifecycle", { detail: { state } }));
  it("coming back after 30 s or more in the background is a wake: Desktop probes and redials its socket", async () => {
    vi.useFakeTimers();
    const host = createDesktopHost({ auth: auth() });
    const wake = vi.fn();
    const off = host.onPowerResume(wake);
    lifecycle("pause");
    vi.advanceTimersByTime(5_000);
    lifecycle("resume");
    expect(wake).not.toHaveBeenCalled(); // A quick app switch: Desktop's visibility nudge is enough.
    lifecycle("pause");
    vi.advanceTimersByTime(45_000);
    lifecycle("resume");
    expect(wake).toHaveBeenCalledTimes(1);
    lifecycle("resume");
    expect(wake).toHaveBeenCalledTimes(1);
    off();
    lifecycle("pause");
    vi.advanceTimersByTime(60_000);
    lifecycle("resume");
    expect(wake).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});
