import type { PcAuth } from "../pc-auth";
export function observePcAuth(
  auth: PcAuth,
  control: { requireSignIn(): void; authenticated(): void },
): PcAuth {
  return {
    signIn: () => auth.signIn(),
    signOut: () => auth.signOut(),
    ticket: async () => {
      try {
        const ticket = await auth.ticket();
        control.authenticated();
        return ticket;
      } catch (error) {
        if (error instanceof Error && error.name === "PcSignInRequired")
          control.requireSignIn();
        throw error;
      }
    },
  };
}
export function installSignInControl(options: {
  auth: PcAuth;
  restart: () => void;
  nativeAvailable: boolean;
  /** Forget this server (native confirms and signs out) and return to first-launch setup. */
  changeServer?: () => Promise<void>;
}) {
  let element: HTMLElement | undefined;
  let accountElement: HTMLElement | undefined;
  let accountHost: HTMLElement | undefined;
  let settingsGeneration = 0;
  let signedIn = false;
  let disposed = false;
  const remove = () => {
    element?.remove();
    element = undefined;
  };
  const removeAccount = () => {
    accountElement?.remove();
    accountElement = undefined;
  };
  return {
    requireSignIn: () => {
      if (disposed || (element && !signedIn)) return;
      remove();removeAccount();signedIn = false;
      element = document.createElement("aside");
      element.className = "hermes-android-signin";
      element.setAttribute("role", "status");
      const message = document.createElement("span");
      message.textContent = options.nativeAvailable
        ? `Sign in to ${location.host}. Sign-in is encrypted on this Android device.`
        : "PC sign-in is available in the Android APK. This browser preview is not connected.";
      element.append(message);
      if (options.nativeAvailable) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = "Sign in to this PC";
        button.onclick = async () => {
          button.disabled = true;
          message.textContent =
            "Complete sign-in in your system browser, then return to Hermes.";
          try {
            await options.auth.signIn();
            if (!disposed) options.restart();
          } catch {
            if (!disposed) {
              message.textContent =
                "Sign-in did not complete. Try again when you are ready.";
              button.disabled = false;
            }
          }
        };
        element.append(button);
        const change = options.changeServer;
        if (change) {
          const other = document.createElement("button");
          other.type = "button";
          other.textContent = "Use a different server";
          other.onclick = async () => {
            other.disabled = true;
            try {
              await change(); // Native reloads into setup after the user confirms.
            } catch {
              if (!disposed) other.disabled = false;
            }
          };
          element.append(other);
        }
      }
      document.body.append(element);
    },
    authenticated: () => {
      if (disposed || signedIn || !options.nativeAvailable) return;
      remove();signedIn = true;
      accountElement = document.createElement("section");
      accountElement.className = "hermes-android-account";
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Sign out of this PC";
      const message = document.createElement("span");
      message.setAttribute("role", "status");
      accountElement.append(message);
      button.onclick = async () => {
        button.disabled = true;
        message.textContent = "Signing out…";
        try {
          await options.auth.signOut();
          if (!disposed) options.restart();
        } catch {
          if (!disposed) {
            message.textContent = "Sign-out did not complete. Try again.";
            button.disabled = false;
          }
        }
      };
      accountElement.append(button);
      accountHost?.append(accountElement);
    },
    mountSettings: (container: HTMLElement) => {
      if (disposed) return () => {};
      const generation = ++settingsGeneration;
      accountHost = container;
      if (accountElement) container.append(accountElement);
      return () => {
        if (generation !== settingsGeneration || accountHost !== container) return;
        accountElement?.remove();
        accountHost = undefined;
      };
    },
    dispose: () => {
      disposed = true;
      remove();
      removeAccount();
      accountHost = undefined;
      settingsGeneration++;
    },
  };
}
