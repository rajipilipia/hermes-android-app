import { describe, it, expect, vi } from "vitest";
import { createConnectionConfig } from "../src/desktop/connection-config";
import { SETUP_ORIGIN, type ServerOperation } from "../src/desktop/server-setup";

const SERVER = "https://gateway.example.com";
function setup(origin: string, replies: Partial<Record<ServerOperation, string | Error>> = {}) {
  const request = vi.fn(async (operation: ServerOperation, _value: string) => {
    const reply = replies[operation];
    if (reply instanceof Error) throw reply;
    return reply ?? "";
  });
  const signOut = vi.fn(async () => {});
  const signedOut = vi.fn();
  const config = createConnectionConfig({ server: { request }, auth: { signOut }, origin: () => origin, signedOut });
  return { config, request, signOut, signedOut };
}

describe("Android connection-config host (Desktop remote mode)", () => {
  it("reports the phone's one server as a signed-in remote connection, and no server during setup", async () => {
    const live = setup(SERVER).config;
    expect(await live.getConnectionConfig()).toMatchObject({ mode: "remote", remoteAuthMode: "oauth", remoteUrl: SERVER, remoteOauthConnected: true, profile: null, envOverride: false });
    // Named profiles follow the phone's server: no per-profile override badge.
    expect(await live.getConnectionConfig("work")).toMatchObject({ mode: "local", profile: "work", remoteUrl: "" });
    expect(await setup(SETUP_ORIGIN).config.getConnectionConfig()).toMatchObject({ mode: "remote", remoteUrl: "", remoteOauthConnected: false });
  });

  it("rejects modes a phone cannot use yet, and token auth, before any native call", async () => {
    const { config, request } = setup(SERVER);
    for (const input of [
      { mode: "local" as const },
      { mode: "cloud" as const, remoteUrl: "https://gateway.example.com" },
      { mode: "cloud" as const, remoteUrl: "https://agent.agents.nousresearch.com.evil.example" },
      { mode: "ssh" as const, sshHost: "pc" },
      { mode: "remote" as const, remoteAuthMode: "token" as const, remoteToken: "x", remoteUrl: SERVER },
      { mode: "remote" as const, remoteAuthMode: "oauth" as const, remoteUrl: SERVER, profile: "work" },
    ]) {
      await expect(config.saveConnectionConfig(input)).rejects.toThrow();
      await expect(config.applyConnectionConfig(input)).rejects.toThrow();
    }
    expect(request).not.toHaveBeenCalled();
    // Clearing a per-profile override that cannot exist is a harmless no-op.
    await expect(config.applyConnectionConfig({ mode: "local", profile: "work" })).resolves.toMatchObject({ mode: "local" });
  });

  it("save stores nothing; sign-in, test and apply go to native with only the typed address", async () => {
    const { config, request } = setup(SETUP_ORIGIN, { signIn: SERVER, test: SERVER, apply: SERVER });
    const input = { mode: "remote" as const, remoteAuthMode: "oauth" as const, remoteUrl: SERVER };
    expect(await config.saveConnectionConfig(input)).toMatchObject({ remoteUrl: SERVER });
    expect(request).not.toHaveBeenCalled();
    expect(await config.oauthLoginConnectionConfig(SERVER)).toEqual({ ok: true, baseUrl: SERVER, connected: true });
    expect(await config.testConnectionConfig(input)).toEqual({ ok: true, reachable: true, baseUrl: SERVER });
    expect(await config.applyConnectionConfig(input)).toMatchObject({ mode: "remote", remoteUrl: SERVER });
    expect(request.mock.calls).toEqual([["signIn", SERVER], ["test", SERVER], ["apply", SERVER]]);
  });

  it("reports native failures the way Desktop's IPC does (results, not throws, for login/test/probe)", async () => {
    const { config } = setup(SETUP_ORIGIN, {
      signIn: new Error("Cancelled."),
      test: new Error("Sign in to gateway.example.com first."),
      probe: new Error("Enter the https:// address"),
    });
    // A cancel adds no detail to the card's own "sign-in did not complete" sentence.
    expect(await config.oauthLoginConnectionConfig(SERVER)).toEqual({ ok: false, baseUrl: SERVER, connected: false });
    expect(await config.testConnectionConfig({ mode: "remote", remoteUrl: SERVER })).toMatchObject({ ok: false, reachable: false, error: "Sign in to gateway.example.com first." });
    expect(await config.probeConnectionConfig("http://gateway.example.com/path")).toEqual({
      baseUrl: "http://gateway.example.com/path", reachable: false, authMode: "unknown", providers: [], version: null, error: "Enter the https:// address",
    });
  });

  it("passes only known probe fields through", async () => {
    const probe = JSON.stringify({ baseUrl: SERVER, reachable: true, authMode: "oauth", providers: [{ name: "nous", displayName: "Nous Research", supportsPassword: false }], version: "0.22.0", error: null, extra: "dropped" });
    const result = await setup(SETUP_ORIGIN, { probe }).config.probeConnectionConfig(SERVER);
    expect(result).toEqual({ baseUrl: SERVER, reachable: true, authMode: "oauth", providers: [{ name: "nous", displayName: "Nous Research", supportsPassword: false }], version: "0.22.0", error: null });
  });

  it("signs out only for the phone's current server, then restarts at the sign-in panel", async () => {
    vi.useFakeTimers();
    try {
      const { config, signOut, signedOut } = setup(SERVER);
      expect(await config.oauthLogoutConnectionConfig("https://other.example.com")).toEqual({ ok: true, connected: false });
      expect(signOut).not.toHaveBeenCalled();
      vi.runAllTimers();
      expect(signedOut).not.toHaveBeenCalled();
      expect(await config.oauthLogoutConnectionConfig(`${SERVER}/`)).toEqual({ ok: true, connected: false });
      expect(signOut).toHaveBeenCalledTimes(1);
      // Desktop's card gets its answer first; the restart follows.
      expect(signedOut).not.toHaveBeenCalled();
      vi.runAllTimers();
      expect(signedOut).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a failed sign-out does not restart", async () => {
    const { config, signOut, signedOut } = setup(SERVER);
    signOut.mockRejectedValueOnce(new Error("Local sign-out cleanup failed. Try again."));
    await expect(config.oauthLogoutConnectionConfig(SERVER)).rejects.toThrow("cleanup failed");
    await new Promise(resolve => setTimeout(resolve, 5));
    expect(signedOut).not.toHaveBeenCalled();
  });

  it("Hermes Cloud: no Portal session on Android; the card opens the Portal and agent sign-in is native", async () => {
    const AGENT = "https://my-agent.agents.nousresearch.com";
    const { config, request } = setup(SETUP_ORIGIN, { cloudSignIn: AGENT, apply: AGENT });
    expect(await config.cloud.status()).toEqual({ portalBaseUrl: "https://portal.nousresearch.com", signedIn: false });
    await expect(config.cloud.login()).rejects.toThrow("paste it under Remote gateway");
    expect(request).toHaveBeenLastCalledWith("portal", "");
    await expect(config.cloud.discover()).rejects.toMatchObject({ needsCloudLogin: true });
    expect(await config.cloud.agentSignIn(AGENT)).toEqual({ baseUrl: AGENT, connected: true });
    expect(request).toHaveBeenLastCalledWith("cloudSignIn", AGENT);
    for (const bad of ["https://gateway.example.com", "https://x.agents.nousresearch.com:8443", "http://x.agents.nousresearch.com"])
      await expect(config.cloud.agentSignIn(bad)).rejects.toThrow("not a Hermes Cloud agent");
    // A cloud-mode apply for an agent address is a remote apply (Desktop resolves cloud as remote).
    expect(await config.applyConnectionConfig({ mode: "cloud", remoteAuthMode: "oauth", remoteUrl: AGENT })).toMatchObject({ remoteUrl: AGENT });
    expect(request).toHaveBeenLastCalledWith("apply", AGENT);
    expect(await config.cloud.logout()).toMatchObject({ ok: true, signedIn: false });
  });
});
