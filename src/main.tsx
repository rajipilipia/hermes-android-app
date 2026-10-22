import "./desktop/fonts.css";
import "./desktop/mobile.css";
import "./desktop/single-screen.css";
import "./desktop/connection.css";
import { installMobile } from "./desktop/mobile";
import { installDesktopHost } from "./desktop/host";
import { pcAuth } from "./pc-auth";
import { installSignInControl, observePcAuth } from "./desktop/auth-control";
import { currentServer, nativeServerSetup } from "./desktop/server-setup";
import { installSocketDiag, watchGatewayState } from "./desktop/stability";
import { installWebviewTag } from "./desktop/webview-tag";
import { request as requestBrowser } from "./desktop/native-browser";
import { startDesktopWithRecovery } from "./desktop/startup-recovery";

// Phone behavior must precede every renderer module so the first autofocus is already guarded.
if (!currentServer()) {
  // First launch: no server chosen. Hermes' own remote-setup panel picks one; native validates,
  // confirms and signs in, then reloads the app at that server.
  installMobile();
  installDesktopHost({ auth: pcAuth });
  void import("./desktop/setup-page").then(module => module.mountSetupPage(document.getElementById("root")!));
} else {
  // Restart at the bare page: a reload would keep the renderer's hash route (e.g. Settings).
  const restart = () => location.replace(location.origin + location.pathname);
  const signIn = installSignInControl({
    auth: pcAuth,
    restart,
    nativeAvailable: !!window.HermesPc,
    changeServer: window.HermesServer ? () => nativeServerSetup.request("reset", "").then(() => {}) : undefined,
  });
  if (!window.HermesPc) signIn.requireSignIn();

  // In-app browser stage 1: links open in Desktop's own browser pane again (Desktop's default).
  // Stage 0 had switched "always open links in the system browser" on while the pane was blank;
  // undo that automatic value once. The user can still turn it on in Desktop's settings.
  try {
    if (localStorage.getItem("hermes.android.browserPane.v1") === null) {
      if (localStorage.getItem("hermes.desktop.alwaysExternalLinks.v1") === "true")
        localStorage.removeItem("hermes.desktop.alwaysExternalLinks.v1");
      localStorage.setItem("hermes.android.browserPane.v1", "stage1");
    }
  } catch { /* storage unavailable: Desktop's default applies */ }
  // Desktop's pane creates its <webview> tag while rendering, so this precedes every renderer module.
  if (window.HermesBrowser) installWebviewTag(window, value => requestBrowser("guest", value));

  // Desktop modules inspect their host at module evaluation time. Never move this
  // below a static renderer import or into a React effect.
  installMobile();
  // Before any socket exists: connection open/close timings for stability rounds (observe only).
  installSocketDiag();
  startDesktopWithRecovery({
    root: document.getElementById("root")!,
    createHost: () => installDesktopHost({ auth: observePcAuth(pcAuth, signIn), signedOut: restart }),
    requireSignIn: () => signIn.requireSignIn(),
    failureText: `Hermes on ${location.host} did not answer. Check that it is running and reachable, then return to Hermes or tap Retry.`,
    mount: async () => {
      // The host-approved primary is resolved before any renderer module loads.
      const { installPcAccountSettings } = await import("./desktop/account-settings");
      if (window.HermesPc) installPcAccountSettings(signIn);
      if (window.HermesPc) {
        const { initializePhoneRuntime } = await import("./desktop/phone-runtime");
        initializePhoneRuntime();
      }
      await import("../vendor/hermes/apps/desktop/src/main");
      // Diagnostics only: a failure here must never become a startup error.
      void import("../vendor/hermes/apps/desktop/src/store/session")
        .then(({ $gatewayState }) => watchGatewayState($gatewayState))
        .catch(() => {});
    },
  });
}
