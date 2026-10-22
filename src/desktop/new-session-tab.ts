import { PRIMARY_SESSION_VIEW } from "../../vendor/hermes/apps/desktop/src/app/chat/session-view";
import { resolveSessionOwner } from "../../vendor/hermes/apps/desktop/src/app/session/hooks/use-session-actions/utils";
import { notifyError } from "../../vendor/hermes/apps/desktop/src/store/notifications";
import { $activeGatewayProfile, type AgentProfileRoute } from "../../vendor/hermes/apps/desktop/src/store/profile";
import { $defaultReasoningEffort } from "../../vendor/hermes/apps/desktop/src/store/session";
import { $focusedStoredSessionId } from "../../vendor/hermes/apps/desktop/src/store/session-focus";
import { $focusedSessionState } from "../../vendor/hermes/apps/desktop/src/store/session-states";

export interface AndroidTabSelection {
  model?: string;
  provider?: string;
  reasoning_effort?: string;
  fast: boolean;
  service_tier?: string;
}
export interface AndroidTabOptions {
  listed: false;
  profile: string;
  route: AgentProfileRoute | null;
  androidSelection: AndroidTabSelection;
}

/** Freeze the visible selection BEFORE any profile/socket await. Never publish it
 * into the old chat, change a default, move a draft, or submit a prompt. */
export function captureAndroidTabSelection(): AndroidTabSelection {
  const state = $focusedSessionState.get();
  const view = PRIMARY_SESSION_VIEW;
  const model = (state?.model ?? view.$model.get()).trim();
  const provider = (state?.provider ?? view.$provider.get()).trim();
  const effort = (state?.reasoningEffort || view.$reasoningEffort.get() || $defaultReasoningEffort.get()).trim();
  const tier = state?.serviceTier ?? view.$serviceTier?.get();
  return {
    ...(model ? { model } : {}),
    ...(provider ? { provider } : {}),
    ...(effort ? { reasoning_effort: effort } : {}),
    fast: state?.fast ?? view.$fast.get(),
    ...(tier === "ultrafast" ? { service_tier: tier } : {}),
  };
}

export async function openAndroidNewSessionTab(open: (dir: "center", options: AndroidTabOptions) => unknown): Promise<void> {
  const stored = $focusedStoredSessionId.get();
  const profile = $activeGatewayProfile.get();
  const selection = captureAndroidTabSelection();
  try {
    const owner = stored ? await resolveSessionOwner(stored) : profile;
    if (!owner) throw new Error("This chat's profile is still loading. Try New tab again after it loads.");
    const route = typeof owner === "string" ? null : owner;
    await open("center", {
      listed: false,
      profile: typeof owner === "string" ? owner : owner.profile,
      route,
      androidSelection: selection,
    });
  } catch (error) {
    notifyError(error, "Could not create a new session");
  }
}
