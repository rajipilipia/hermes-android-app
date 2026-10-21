import type { HermesNotification } from "../../vendor/hermes/apps/desktop/electron/notification-types";
import type { NotificationRoute } from "./notifications";
type Owner = undefined | null | string | { profile: string; connectionId: string; targetProfile?: string; mode?: string };
export function makeNotificationRouting(deps: {
  owner(id: string): Owner;
  stored(id: string): string | undefined | null;
  active(): string | undefined;
  ensure(profile: string): Promise<void>;
  hint(stored: string, profile: string): void;
  path(value?: string): string | undefined;
}) {
  return {
    capture(input: HermesNotification): NotificationRoute | undefined {
      const id = input.sessionId || input.focusSessionId;
      const owner = id ? deps.owner(id) : deps.active();
      // The Android app connects to one Hermes server. Never flatten another registry
      // connection or an alias whose actual target differs from its profile.
      if (!owner || (typeof owner !== "string" && (owner.connectionId !== "local" || (owner.targetProfile && owner.targetProfile !== owner.profile)))) return;
      const profile = typeof owner === "string" ? owner : owner.profile;
      if (!profile) return;
      const storedSessionId = input.focusSessionId || (id ? deps.stored(id) : undefined);
      if (id && !storedSessionId) return;
      const activate = input.activate ? deps.path(input.activate) : undefined;
      if (input.activate && !activate) return;
      return { profile, ...(input.sessionId ? { sessionId: input.sessionId } : {}), ...(storedSessionId ? { storedSessionId } : {}), ...(activate ? { activate } : {}) };
    },
    async open(route: NotificationRoute, current: () => boolean) {
      if (!current()) throw new Error("Notification owner is stale.");
      await deps.ensure(route.profile);
      if (!current()) throw new Error("Notification owner is stale.");
      if (deps.active() !== route.profile) throw new Error("Notification owner activation failed.");
      if (route.storedSessionId) deps.hint(route.storedSessionId, route.profile);
    },
  };
}
