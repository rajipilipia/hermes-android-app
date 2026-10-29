// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { atom } from "nanostores";
const state = vi.hoisted(() => ({ source: null as string | null }));
vi.mock("../vendor/hermes/apps/desktop/src/store/profile", async () => {
  const { atom } = await import("nanostores"); return { $activeGatewayProfile: atom("default") };
});
vi.mock("../vendor/hermes/apps/desktop/src/store/session", async () => {
  const { atom } = await import("nanostores"); return { $busy: atom(false), $awaitingResponse: atom(false) };
});
vi.mock("../vendor/hermes/apps/desktop/src/store/session-states", async () => {
  const { atom } = await import("nanostores"); return { $workingSessionIds: atom<string[]>([]) };
});
vi.mock("../vendor/hermes/apps/desktop/src/store/gateway", () => ({ activeGatewayConnectionId: () => state.source }));
import { $activeGatewayProfile } from "../vendor/hermes/apps/desktop/src/store/profile";
import { $busy, $awaitingResponse } from "../vendor/hermes/apps/desktop/src/store/session";
import { $workingSessionIds } from "../vendor/hermes/apps/desktop/src/store/session-states";
import { initializePhoneRuntime } from "../src/desktop/phone-runtime";
const working = $workingSessionIds as unknown as ReturnType<typeof atom<string[]>>;
let dispose: (() => void) | undefined;
let remember = vi.fn(async (_name: string) => ({}));
let prompt = vi.fn((_marker: string, _value: string) => '{"ok":true}');
beforeEach(() => {
  state.source = null; $busy.set(false); $awaitingResponse.set(false); working.set([]); $activeGatewayProfile.set("default");
  remember = vi.fn(async (_name: string) => ({}));
  window.hermesDesktop = { profile: { remember } } as never;
  prompt = vi.fn((_marker: string, _value: string) => '{"ok":true}');
  vi.stubGlobal("prompt", prompt);
});
afterEach(() => { dispose?.(); dispose = undefined; vi.unstubAllGlobals(); delete (window as unknown as {hermesDesktop?:unknown}).hermesDesktop; });
it("does not overwrite startup owner with the initial default; remembers only primary-server selections", () => {
  dispose = initializePhoneRuntime(); expect(remember).not.toHaveBeenCalled();
  $activeGatewayProfile.set("research"); expect(remember).toHaveBeenCalledWith("research");
  state.source = "unrelated-registry"; $activeGatewayProfile.set("other"); expect(remember).toHaveBeenCalledTimes(1);
});
it("protects awaiting replies and switched-away running sessions without repeatedly starting a service", () => {
  dispose = initializePhoneRuntime();
  $awaitingResponse.set(true); $busy.set(true); $awaitingResponse.set(false);
  expect(prompt.mock.calls.map(c => JSON.parse(c[1]).active)).toEqual([false, true]);
  working.set(["synthetic-runtime"]); $busy.set(false);
  expect(prompt).toHaveBeenCalledTimes(2);
  working.set([]); expect(JSON.parse(prompt.mock.calls.at(-1)![1])).toEqual({active:false});
});
it("surfaces failed service admission and retries on resume without sending any prompt", () => {
  prompt.mockReturnValue('{"ok":false}'); dispose = initializePhoneRuntime(); $busy.set(true);
  expect(document.getElementById("hermes-background-unavailable")?.textContent).toContain("Keep Hermes open");
  prompt.mockReturnValue('{"ok":true}');
  window.dispatchEvent(new CustomEvent("hermes:native-lifecycle", {detail:{state:"resume"}}));
  expect(document.getElementById("hermes-background-unavailable")).toBeNull();
  expect(prompt.mock.calls.every(c => c[0] === "hermes.android.work.v1")).toBe(true);
});
it("releases work and subscriptions on page replacement", () => {
  dispose = initializePhoneRuntime(); $busy.set(true); dispose(); dispose = undefined;
  const count = prompt.mock.calls.length; $busy.set(false); $activeGatewayProfile.set("research");
  expect(prompt).toHaveBeenCalledTimes(count); expect(remember).not.toHaveBeenCalled();
  expect(JSON.parse(prompt.mock.calls.at(-1)![1])).toEqual({active:false});
});
it("does not call the blocked prompt during pagehide but still releases subscriptions", () => {
  dispose = initializePhoneRuntime(); $busy.set(true);
  const count = prompt.mock.calls.length;
  window.dispatchEvent(new Event("pagehide")); dispose = undefined;
  $busy.set(false); expect(prompt).toHaveBeenCalledTimes(count);
});
