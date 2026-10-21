// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import type { installDesktopHost } from "../src/desktop/host";

type Host = ReturnType<typeof installDesktopHost>;
vi.mock("../src/desktop/phone-runtime", () => ({ initializePhoneRuntime: vi.fn() }));
let host: Host | undefined;
afterEach(() => {
  window.dispatchEvent(new Event("pagehide"));
  host?.dispose(); host = undefined;
  delete (window as unknown as { hermesDesktop?: unknown }).hermesDesktop;
  vi.doUnmock("../src/desktop/host");
  vi.doUnmock("../src/pc-auth");
  vi.doUnmock("../vendor/hermes/apps/desktop/src/main");
  document.body.replaceChildren();
});

it.each([
  { status: 403, body: { detail: "PRIVATE_UNGRANTED_DETAIL" } },
  { status: 200, body: { active: "default" } }, // no current profile named
])("actual entry never imports the renderer after rejected bootstrap metadata: %j", async reply => {
  vi.resetModules();
  document.body.innerHTML = '<div id="root"></div>';
  const mounted = vi.fn();
  const rpc = vi.fn(async (_params: unknown, _timeoutMs?: number) => reply);
  vi.doMock("../src/desktop/host", async importOriginal => {
    const actual = await importOriginal<typeof import("../src/desktop/host")>();
    return { ...actual, installDesktopHost: (options: Parameters<typeof installDesktopHost>[0]) => {
      host = actual.installDesktopHost({ ...options, rest: rpc as never });
      return host;
    } };
  });
  vi.doMock("../vendor/hermes/apps/desktop/src/main", () => { mounted(); return {}; });
  await import("../src/main");
  await vi.waitFor(() => expect(document.getElementById("root")?.textContent).toContain("did not answer. Check that it is running and reachable"));
  expect(mounted).not.toHaveBeenCalled();
  expect(document.body.textContent).not.toContain("PRIVATE_UNGRANTED_DETAIL");
  expect(rpc).toHaveBeenCalledTimes(1);
  await expect(host!.getConnection()).rejects.toThrow("closed");
});

it("actual entry shows native sign-in when REST bootstrap requires authentication instead of leaving a blank page", async () => {
  vi.resetModules();
  document.body.innerHTML = '<div id="root"></div>';
  const previousBridge = window.HermesPc;
  window.HermesPc = { request: vi.fn() };
  try {
    const credentials = { signIn: vi.fn(async () => {}), signOut: vi.fn(), ticket: vi.fn(async () => "synthetic-ticket") };
    const required = Object.assign(new Error("Sign in to this server again."), { name: "PcSignInRequired" });
    const rest = vi.fn(async () => { throw required; });
    const mounted = vi.fn();
    vi.doMock("../src/pc-auth", () => ({ pcAuth: credentials }));
    vi.doMock("../src/desktop/host", async importOriginal => {
      const actual = await importOriginal<typeof import("../src/desktop/host")>();
      return { ...actual, installDesktopHost: (options: Parameters<typeof installDesktopHost>[0]) => {
        host = actual.installDesktopHost({ ...options, rest });
        return host;
      } };
    });
    vi.doMock("../vendor/hermes/apps/desktop/src/main", () => { mounted(); return {}; });
    await import("../src/main");
    await vi.waitFor(() => expect(document.querySelector(".hermes-android-signin button")?.textContent).toBe("Sign in to this PC"));
    expect(document.querySelector<HTMLButtonElement>(".hermes-android-signin button")?.disabled).toBe(false);
    expect(rest).toHaveBeenCalledTimes(1);
    expect(credentials.ticket).not.toHaveBeenCalled();
    expect(credentials.signIn).not.toHaveBeenCalled();
    expect(mounted).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain("did not answer");
    await expect(host!.getConnection()).rejects.toThrow("closed");
  } finally {
    if (previousBridge) window.HermesPc = previousBridge;
    else delete window.HermesPc;
  }
});

it("actual entry learns the server's primary profile through Hermes's own API BEFORE importing the renderer", async () => {
  vi.resetModules();
  document.body.innerHTML = '<div id="root"></div>';
  const credentials = { signIn: vi.fn(async () => {}), signOut: vi.fn(), ticket: vi.fn(async () => "synthetic-ticket") };
  let metadata!: (value: { status: number; body: unknown }) => void;
  const rest = vi.fn((_params: unknown, _timeoutMs?: number) => new Promise<{ status: number; body: unknown }>(done => { metadata = done; }));
  const mounted = vi.fn();
  vi.doMock("../src/pc-auth", () => ({ pcAuth: credentials }));
  vi.doMock("../src/desktop/host", async importOriginal => {
    const actual = await importOriginal<typeof import("../src/desktop/host")>();
    return { ...actual, installDesktopHost: (options: Parameters<typeof installDesktopHost>[0]) => {
      host = actual.installDesktopHost({ ...options, rest });
      return host;
    } };
  });
  // Only the UI import boundary is replaced; the actual entry/host/auth runs.
  vi.doMock("../vendor/hermes/apps/desktop/src/main", () => { mounted(); return {}; });
  await import("../src/main");
  await vi.waitFor(() => expect(rest).toHaveBeenCalledWith({ operation: "GET /api/profiles/active", profile: "default", pathParams: {}, query: {} }, 30_000));
  expect(mounted).not.toHaveBeenCalled();
  metadata({ status: 200, body: { active: "default", current: "research" } });
  await vi.waitFor(() => expect(mounted).toHaveBeenCalledTimes(1));
  expect(await host!.getConnection()).toMatchObject({ profile: "research" });
  // No socket ticket is needed to start: native REST carries the sign-in itself.
  expect(credentials.ticket).not.toHaveBeenCalled();
});

it("actual entry retries failed bootstrap from its button without mounting twice", async () => {
  vi.resetModules();
  document.body.innerHTML = '<div id="root"></div>';
  const credentials = { signIn: vi.fn(), signOut: vi.fn(), ticket: vi.fn() };
  const rest = vi.fn()
    .mockRejectedValueOnce(new Error("The Hermes server did not answer in time."))
    .mockResolvedValue({ status: 200, body: { current: "research" } });
  const mounted = vi.fn();
  vi.doMock("../src/pc-auth", () => ({ pcAuth: credentials }));
  vi.doMock("../src/desktop/host", async importOriginal => {
    const actual = await importOriginal<typeof import("../src/desktop/host")>();
    return { ...actual, installDesktopHost: (options: Parameters<typeof installDesktopHost>[0]) => {
      host = actual.installDesktopHost({ ...options, rest });
      return host;
    } };
  });
  vi.doMock("../vendor/hermes/apps/desktop/src/main", () => { mounted(); return {}; });
  await import("../src/main");
  await vi.waitFor(() => expect(document.querySelector<HTMLButtonElement>("#root button")?.textContent).toBe("Retry"));
  expect(mounted).not.toHaveBeenCalled();
  const retry = document.querySelector<HTMLButtonElement>("#root button")!;
  retry.click(); retry.click();
  await vi.waitFor(() => expect(mounted).toHaveBeenCalledTimes(1));
  expect(rest).toHaveBeenCalledTimes(2);
  expect(await host!.getConnection()).toMatchObject({ profile: "research" });
  expect(credentials.signIn).not.toHaveBeenCalled();
  expect(credentials.ticket).not.toHaveBeenCalled();
});
