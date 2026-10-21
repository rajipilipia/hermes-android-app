// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { installDesktopHost } from "../src/desktop/host";
import { initializeNotificationRouting } from "../src/desktop/notification-runtime";
import { $activeSessionId, $selectedStoredSessionId, setSessionOwnerHint } from "../vendor/hermes/apps/desktop/src/store/session";
import { dispatchNativeNotification, setNativeNotifyEnabled, setNativeNotifyKind } from "../vendor/hermes/apps/desktop/src/store/native-notifications";
import { markNativeNotifyBaseline, __resetNativeNotifyBaselineForTests } from "../vendor/hermes/apps/desktop/src/store/notify-baseline";
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
it("uses the genuine pinned dispatcher preferences, replay baseline and dedup before Android show", () => {
  const prompt = vi.fn((_message: string, _payload: string) => '{"ok":true}');
  vi.stubGlobal("prompt", prompt);
  vi.spyOn(document, "hasFocus").mockReturnValue(false);
  const host = installDesktopHost({ auth: { signIn: async () => {}, ticket: async () => "fixture", signOut: async () => {} } });
  try {
    initializeNotificationRouting();
    $activeSessionId.set("notification-runtime-fixture");
    $selectedStoredSessionId.set("notification-stored-fixture");
    setSessionOwnerHint("notification-stored-fixture", { connectionId: "local", profile: "EstDept", mode: "remote" });
    setNativeNotifyEnabled(true); setNativeNotifyKind("approval", true);__resetNativeNotifyBaselineForTests();
    const input = { kind: "approval" as const, title: "Synthetic notification", sessionId: "notification-runtime-fixture" };
    expect(dispatchNativeNotification(input)).toBe(true);
    const shown = JSON.parse(prompt.mock.calls[0][1]);
    expect(shown).toMatchObject({ operation: "show", payload: { sessionId: "notification-runtime-fixture", focusSessionId: "notification-stored-fixture", route: { profile: "EstDept", sessionId: "notification-runtime-fixture", storedSessionId: "notification-stored-fixture" } } });
    expect(dispatchNativeNotification(input)).toBe(false);
    setNativeNotifyKind("approval", false);expect(dispatchNativeNotification(input)).toBe(false);
    setNativeNotifyKind("approval", true);markNativeNotifyBaseline();expect(dispatchNativeNotification(input)).toBe(false);
    __resetNativeNotifyBaselineForTests();setNativeNotifyEnabled(false);expect(dispatchNativeNotification(input)).toBe(false);
    expect(prompt).toHaveBeenCalledOnce();
  } finally { setNativeNotifyEnabled(true);__resetNativeNotifyBaselineForTests();$activeSessionId.set(null);$selectedStoredSessionId.set(null);host.dispose(); }
});
