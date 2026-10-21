// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { startDesktopWithRecovery } from "../src/desktop/startup-recovery";

let stop: (() => void) | undefined;
afterEach(() => { stop?.(); stop = undefined; vi.restoreAllMocks(); document.body.replaceChildren(); });
const lifecycle = (state: "pause" | "resume") => window.dispatchEvent(new CustomEvent("hermes:native-lifecycle", { detail: { state } }));

it("retries bootstrap once on foreground return, not on duplicate or later resume events", async () => {
  const root = document.createElement("div"); document.body.append(root);
  const bootstrap = vi.fn(async () => { throw new Error("temporary failure"); });
  const createHost = vi.fn(() => ({ bootstrap, dispose: vi.fn() }));
  const mount = vi.fn(async () => {});
  stop = startDesktopWithRecovery({ root, createHost, mount, requireSignIn: vi.fn(), failureText: "Unavailable" });
  await vi.waitFor(() => expect(root.querySelector("button")?.textContent).toBe("Retry"));
  lifecycle("pause"); lifecycle("resume"); lifecycle("resume");
  await vi.waitFor(() => expect(bootstrap).toHaveBeenCalledTimes(2));
  await vi.waitFor(() => expect(root.querySelector("button")?.textContent).toBe("Retry"));
  lifecycle("pause"); lifecycle("resume");
  expect(bootstrap).toHaveBeenCalledTimes(2);
  expect(mount).not.toHaveBeenCalled();
  // An exhausted automatic budget never removes the explicit recovery action.
  bootstrap.mockResolvedValueOnce(undefined as never);
  root.querySelector<HTMLButtonElement>("button")!.click();
  await vi.waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
  expect(createHost).toHaveBeenCalledTimes(3);
});

it("defers an initially hidden page until its first foreground event", async () => {
  const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  const root = document.createElement("div");
  const bootstrap = vi.fn(async () => {}), mount = vi.fn(async () => {});
  stop = startDesktopWithRecovery({ root, createHost: () => ({ bootstrap, dispose: vi.fn() }), mount, requireSignIn: vi.fn(), failureText: "Unavailable" });
  expect(bootstrap).not.toHaveBeenCalled();
  visibility.mockReturnValue("visible"); document.dispatchEvent(new Event("visibilitychange"));
  lifecycle("resume");
  await vi.waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
  expect(bootstrap).toHaveBeenCalledTimes(1);
});

it("recovers when return precedes the pending failure, without concurrent attempts", async () => {
  const root = document.createElement("div");
  let reject!: (reason: Error) => void;
  const bootstrap = vi.fn()
    .mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }))
    .mockResolvedValue(undefined);
  const mount = vi.fn(async () => {});
  stop = startDesktopWithRecovery({ root, createHost: () => ({ bootstrap, dispose: vi.fn() }), mount, requireSignIn: vi.fn(), failureText: "Unavailable" });
  lifecycle("pause"); lifecycle("resume"); lifecycle("resume");
  expect(bootstrap).toHaveBeenCalledTimes(1);
  reject(new Error("background timeout"));
  await vi.waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
  expect(bootstrap).toHaveBeenCalledTimes(2);
});

it("never retries sign-in-required errors or invokes renderer startup", async () => {
  const root = document.createElement("div");
  const bootstrap = vi.fn(async () => { throw Object.assign(new Error("Sign in"), { name: "PcSignInRequired" }); });
  const mount = vi.fn(async () => {}), requireSignIn = vi.fn();
  stop = startDesktopWithRecovery({ root, createHost: () => ({ bootstrap, dispose: vi.fn() }), mount, requireSignIn, failureText: "Unavailable" });
  await vi.waitFor(() => expect(requireSignIn).toHaveBeenCalledTimes(1));
  lifecycle("pause"); lifecycle("resume");
  expect(bootstrap).toHaveBeenCalledTimes(1);
  expect(root.querySelector("button")).toBeNull();
  expect(mount).not.toHaveBeenCalled();
});

it("does not retry a background failure until the app returns", async () => {
  const root = document.createElement("div");
  let reject!: (reason: Error) => void;
  const bootstrap = vi.fn()
    .mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }))
    .mockResolvedValue(undefined);
  const mount = vi.fn(async () => {});
  stop = startDesktopWithRecovery({ root, createHost: () => ({ bootstrap, dispose: vi.fn() }), mount, requireSignIn: vi.fn(), failureText: "Unavailable" });
  lifecycle("pause"); reject(new Error("background timeout"));
  await vi.waitFor(() => expect(root.querySelector("button")?.textContent).toBe("Retry"));
  root.querySelector<HTMLButtonElement>("button")!.click();
  expect(bootstrap).toHaveBeenCalledTimes(1);
  lifecycle("resume");
  await vi.waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
  expect(bootstrap).toHaveBeenCalledTimes(2);
});

it("does not mount or retry a stale startup after page teardown", async () => {
  const root = document.createElement("div");
  let finish!: () => void;
  const bootstrap = vi.fn(() => new Promise<void>(resolve => { finish = resolve; }));
  const mount = vi.fn(async () => {}), dispose = vi.fn();
  stop = startDesktopWithRecovery({ root, createHost: () => ({ bootstrap, dispose }), mount, requireSignIn: vi.fn(), failureText: "Unavailable" });
  window.dispatchEvent(new Event("pagehide")); finish();
  await Promise.resolve(); await Promise.resolve();
  lifecycle("pause"); lifecycle("resume");
  expect(mount).not.toHaveBeenCalled();
  expect(bootstrap).toHaveBeenCalledTimes(1);
  expect(dispose).toHaveBeenCalledTimes(1);
});

it("does not retry once renderer import has started", async () => {
  const root = document.createElement("div");
  const bootstrap = vi.fn(async () => {}), mount = vi.fn(async () => { throw new Error("renderer failure"); });
  stop = startDesktopWithRecovery({ root, createHost: () => ({ bootstrap, dispose: vi.fn() }), mount, requireSignIn: vi.fn(), failureText: "Unavailable" });
  await vi.waitFor(() => expect(root.textContent).toContain("renderer could not start"));
  lifecycle("pause"); lifecycle("resume");
  expect(root.querySelector("button")).toBeNull();
  expect(bootstrap).toHaveBeenCalledTimes(1);
  expect(mount).toHaveBeenCalledTimes(1);
});
