import type { HermesNotification } from "../../vendor/hermes/apps/desktop/electron/notification-types";

// Separate from HermesPc credentials. Standard WebChromeClient prompt callback;
// native verifies both the calling URL and its current bundled document.
export function notificationRequest(operation: string, payload?: unknown): Record<string, unknown> {
  try {
    const raw = window.prompt("hermes.android.notifications.v1", JSON.stringify({ operation, payload: payload ?? {} }));
    const result: unknown = raw && JSON.parse(raw);
    return result && typeof result === "object" && !Array.isArray(result) ? result as Record<string, unknown> : { ok: false };
  } catch { return { ok: false }; }
}
export type NotificationRoute = { profile: string; sessionId?: string; storedSessionId?: string; activate?: string };
type Routing = { capture(input: HermesNotification): NotificationRoute | undefined; open(route: NotificationRoute, current: () => boolean): Promise<void> };
let routing: Routing | undefined;
export function configureNotificationRouting(value: Routing) { routing = value; }
export function createNotificationHost() {
  let closed = false;
  let draining = false;
  const focuses = new Set<(id: string) => void>();
  const activates = new Set<(payload: { activate?: string }) => void>();
  const drain = async () => {
    if (closed || draining || !routing || (!focuses.size && !activates.size)) return;
    draining = true;
    try {
      const result = notificationRequest("take");
      if (result.ok !== true || !result.route || typeof result.route !== "object") return;
      const route = { ...result.route } as NotificationRoute;
      if (typeof route.profile !== "string" || !route.profile) return;
      const owner = routing;
      await owner.open(route, () => !closed && owner === routing);
      if (closed || owner !== routing) return;
      // Review only. No actionId/notifyId ever crosses back to executable
      // approval/plugin callbacks, including when the OS Review button was used.
      if (route.storedSessionId) for (const callback of focuses) callback(route.storedSessionId);
      else if (route.activate) for (const callback of activates) callback({ activate: route.activate });
    } catch { /* Navigation failure cannot fall back to the active/default owner. */ }
    finally { draining = false; }
  };
  const tap = () => { void drain(); };
  if (typeof window !== "undefined") {
    window.addEventListener("hermes:notification-tap", tap);
    window.addEventListener("focus", tap);
  }
  return {
    notify: async (payload: HermesNotification): Promise<boolean> => {
      if (closed) return false;
      const route = routing?.capture(payload);
      if ((payload.sessionId || payload.focusSessionId || payload.activate) && !route) return false;
      return notificationRequest("show", { ...payload, route }).ok === true;
    },
    onFocusSession(callback: (id: string) => void) { focuses.add(callback); queueMicrotask(tap); return () => { focuses.delete(callback); }; },
    onNotificationActivate(callback: (payload: { activate?: string }) => void) { activates.add(callback); queueMicrotask(tap); return () => { activates.delete(callback); }; },
    onNotificationAction(_callback: (payload: { actionId: string; sessionId?: string }) => void) { return () => {}; },
    cancelNotification: (payload: { notifyId?: string; tag?: string } = {}) => !closed && notificationRequest("cancel", payload).ok === true,
    dispose() {
      closed = true; focuses.clear(); activates.clear();
      if (typeof window !== "undefined") { window.removeEventListener("hermes:notification-tap", tap); window.removeEventListener("focus", tap); }
    },
  };
}
