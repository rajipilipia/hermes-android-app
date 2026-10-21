// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { createDesktopHost } from "../src/desktop/host";
import { configureNotificationRouting } from "../src/desktop/notifications";
const auth = { signIn: async () => {}, ticket: async () => "ticket", signOut: async () => {} };
afterEach(() => { vi.unstubAllGlobals(); });
it("hands the original Desktop payload to native and reports refusal honestly", async () => {
  const prompt = vi.fn((_message: string, _payload: string) => JSON.stringify({ ok: false }));
  vi.stubGlobal("prompt", prompt);
  const host = createDesktopHost({ auth });
  expect(host).toHaveProperty("notify");
  expect(await (host as any).notify({ title: "Fixture", kind: "turnDone", silent: true })).toBe(false);
  expect(prompt).toHaveBeenCalledWith("hermes.android.notifications.v1", expect.any(String));
  expect(JSON.parse(prompt.mock.calls[0][1] as string)).toMatchObject({ operation: "show", payload: { title: "Fixture", kind: "turnDone", silent: true } });
  host.dispose();
});
it("captures the owner synchronously and consumes native taps through focus, never approval actions", async () => {
  let profile = "EstDept";
  const open = vi.fn(async (_route: unknown) => {});
  configureNotificationRouting({ capture: input => ({ profile, sessionId: input.sessionId, storedSessionId: input.focusSessionId }), open });
  const route = { profile: "EstDept", sessionId: "runtime-1", storedSessionId: "stored-1" };
  const calls: any[] = [];
  let tapped = false;
  vi.stubGlobal("prompt", vi.fn((_message: string, body: string) => {
    const request = JSON.parse(body); calls.push(request);
    return JSON.stringify(request.operation === "take" && tapped ? (tapped = false, { ok: true, route }) : { ok: request.operation === "show" });
  }));
  const host = createDesktopHost({ auth });
  const focus = vi.fn(), action = vi.fn();
  expect(host).toHaveProperty("onFocusSession");
  const unsubscribe = (host as any).onFocusSession(focus);
  (host as any).onNotificationAction(action);
  await host.notify({ kind: "approval", title: "Review fixture", sessionId: "runtime-1", focusSessionId: "stored-1", actions: [{ id: "approve:request-1", text: "Approve" }] });
  profile = "example-profile";
  expect(calls.find(call => call.operation === "show").payload.route).toEqual(route);
  tapped = true;window.dispatchEvent(new Event("hermes:notification-tap"));
  await vi.waitFor(() => expect(focus).toHaveBeenCalledWith("stored-1"));
  expect(open).toHaveBeenCalledWith(route, expect.any(Function));
  expect(action).not.toHaveBeenCalled();
  unsubscribe();host.dispose();
  tapped = true;window.dispatchEvent(new Event("hermes:notification-tap"));
  expect(tapped).toBe(true);
});
