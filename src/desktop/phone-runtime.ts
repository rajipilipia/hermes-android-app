import { $activeGatewayProfile } from "../../vendor/hermes/apps/desktop/src/store/profile";
import { $busy, $awaitingResponse } from "../../vendor/hermes/apps/desktop/src/store/session";
import { $workingSessionIds } from "../../vendor/hermes/apps/desktop/src/store/session-states";
import { activeGatewayConnectionId } from "../../vendor/hermes/apps/desktop/src/store/gateway";

/** Android-only lifecycle glue; stored chat restoration remains the upstream owner's job. */
export function initializePhoneRuntime(): () => void {
  let last: boolean | undefined;
  const update = () => {
    const active = $busy.get() || $awaitingResponse.get() || $workingSessionIds.get().length > 0;
    if (active === last) return;
    const raw = window.prompt("hermes.android.work.v1", JSON.stringify({ active }));
    let ok = false;
    try { ok = JSON.parse(raw ?? "{}").ok === true; } catch { /* native unavailable */ }
    if (ok) last = active;
    let warning = document.getElementById("hermes-background-unavailable");
    if (active && !ok) {
      if (!warning) {
        warning = document.createElement("aside");
        warning.id = "hermes-background-unavailable";
        warning.setAttribute("role", "alert");
        warning.style.cssText = "position:fixed;bottom:0;left:0;right:0;z-index:9999;padding:8px;background:#402000;color:white";
        warning.textContent = "Background connection unavailable. Keep Hermes open while it finishes.";
        document.body.append(warning);
      }
    } else warning?.remove();
  };
  // listen, not subscribe: the unadopted initial 'default' must not erase a saved owner.
  const remember = $activeGatewayProfile.listen(profile => {
    const source = activeGatewayConnectionId();
    if (source !== null && source !== "local") return;
    void window.hermesDesktop?.profile?.remember(profile).catch(() => {});
  });
  const subscriptions = [$busy.subscribe(update), $awaitingResponse.subscribe(update), $workingSessionIds.subscribe(update)];
  const resume = (event: Event) => {
    if ((event as CustomEvent<{state?: string}>).detail?.state === "resume") { last = undefined; update(); }
  };
  window.addEventListener("hermes:native-lifecycle", resume);
  const dispose = (event?: Event) => {
    remember();subscriptions.forEach(stop => stop());
    window.removeEventListener("hermes:native-lifecycle", resume);
    window.removeEventListener("pagehide", dispose);
    // Chromium blocks prompt() during pagehide; native releases work at the next document start (MainActivity.onPageStarted).
    if (event?.type !== "pagehide") window.prompt("hermes.android.work.v1", JSON.stringify({ active: false }));
    document.getElementById("hermes-background-unavailable")?.remove();
  };
  window.addEventListener("pagehide", dispose, { once: true });
  return dispose;
}
