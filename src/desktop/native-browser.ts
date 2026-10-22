/**
 * Desktop's in-app browser contract on Android (R1, approved staged). Stage 0: openExternal hands an
 * http/https link to the system browser; native validates it (NativeHostPolicy.allowExternal).
 * Stage 1: "guest" requests drive the native browser pane (see webview-tag.ts, BrowserPane.java).
 */
interface NativeBrowserBridge { request(id: string, operation: string, value: string): void; }
declare global {
  interface Window {
    HermesBrowser?: NativeBrowserBridge;
    __hermesBrowserResult?: (id: string, ok: boolean, value: string) => void;
    __hermesGuestEvent?: (guest: number, type: string, detail: string) => void;
  }
}

const pending = new Map<string, { resolve: (value: string) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>();
let sequence = 0;

export function request(operation: "external" | "guest", value: string): Promise<string> {
  const bridge = typeof window === "undefined" ? undefined : window.HermesBrowser;
  if (!bridge) return Promise.reject(new Error("Opening links needs the Android app."));
  window.__hermesBrowserResult = (id, ok, result) => {
    const entry = pending.get(id);
    if (!entry) return;
    pending.delete(id);
    clearTimeout(entry.timer);
    if (ok) entry.resolve(result);
    else entry.reject(new Error(result));
  };
  return new Promise((resolve, reject) => {
    const id = String(++sequence);
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error("The link did not open in time."));
    }, 15_000);
    pending.set(id, { resolve, reject, timer });
    try {
      bridge.request(id, operation, value);
    } catch {
      pending.delete(id);
      clearTimeout(timer);
      reject(new Error("Opening links is unavailable."));
    }
  });
}

/** Desktop's hermesDesktop.openExternal. */
export async function openExternal(url: string): Promise<void> {
  await request("external", String(url));
}
