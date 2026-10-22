// First launch (no server chosen yet): Hermes Desktop's own "Connect to existing Hermes" panel,
// unmodified. Its Apply calls applyConnectionConfig, which reloads the app at the chosen server.
import "../../vendor/hermes/apps/desktop/src/styles.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { FirstRunRemoteSetup } from "../../vendor/hermes/apps/desktop/src/components/remote-setup/first-run";
import { ThemeProvider } from "../../vendor/hermes/apps/desktop/src/themes/context";

export function mountSetupPage(root: HTMLElement) {
  // Hermes' own ThemeProvider paints the full palette (the .dark class alone leaves the page light).
  document.body.classList.add("hermes-android-setup");
  // Desktop's first-run panel enables Apply only after a passing Test. After a successful sign-in the
  // next step is always that test, so run it for the user instead of leaving Apply greyed out.
  addEventListener("hermes:server-signed-in", () => {
    const started = Date.now();
    const tryTest = () => {
      const test = [...root.querySelectorAll("button")].find(b => b.textContent?.trim() === "Test connection");
      if (test && !test.disabled) test.click();
      else if (Date.now() - started < 5_000) setTimeout(tryTest, 100);
    };
    setTimeout(tryTest, 0);
  });
  // "Back" returns to Desktop's local-install choice, which a phone does not have; it stays on this panel.
  createRoot(root).render(
    <StrictMode>
      <ThemeProvider>
        <FirstRunRemoteSetup onBack={() => {}} />
      </ThemeProvider>
    </StrictMode>,
  );
}
