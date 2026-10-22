// Loaded only after authenticated bootstrap, never by the initial host module.
import { configureNotificationRouting } from "./notifications";
import { makeNotificationRouting } from "./notification-routing";
import { knownOwnerForSession, storedSessionIdForRuntimeId } from "../../vendor/hermes/apps/desktop/src/store/session-states";
import { ensureGatewayProfile, $activeGatewayProfile } from "../../vendor/hermes/apps/desktop/src/store/profile";
import { $gateway, activeGatewayConnectionId, activeGatewayProfileKey } from "../../vendor/hermes/apps/desktop/src/store/gateway";
import { $connection, setSessionOwnerHint } from "../../vendor/hermes/apps/desktop/src/store/session";
import { resolveHermesOpenPath } from "../../vendor/hermes/apps/desktop/src/lib/hermes-open-target";
export function initializeNotificationRouting() {
  configureNotificationRouting(makeNotificationRouting({
    owner: knownOwnerForSession,
    stored: storedSessionIdForRuntimeId,
    active: () => {
      if (activeGatewayConnectionId() !== null && activeGatewayConnectionId() !== "local") return;
      if ($gateway.get()?.connectionState !== "open") return;
      const profile = $activeGatewayProfile.get();
      const connection = $connection.get();
      if (activeGatewayProfileKey() === profile || (connection?.sharedPrimary && connection.profile === profile)) return profile;
    },
    ensure: profile => ensureGatewayProfile(profile, { forceLegacyRoute: true }),
    hint: (stored, profile) => setSessionOwnerHint(stored, { connectionId: "local", mode: "remote", profile }),
    path: value => resolveHermesOpenPath(value) ?? undefined,
  }));
}
