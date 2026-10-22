/**
 * Server setup for the Hermes connection cards (Settings → Gateways, first launch).
 * Only a typed server address crosses to native, which validates it and asks before switching.
 * Results carry no tokens or tickets. Native owns all credentials (see pc-auth.ts).
 */
export const SETUP_ORIGIN = "https://setup.hermes-android.invalid";
export type ServerOperation = "probe" | "signIn" | "cloudSignIn" | "test" | "apply" | "reset" | "portal";
export interface ServerSetup {
  request(operation: ServerOperation, value: string): Promise<string>;
}
interface NativeServerBridge { request(id: string, operation: string, value: string): void; }
declare global {
  interface Window {
    HermesServer?: NativeServerBridge;
    __hermesServerResult?: (id: string, ok: boolean, value: string) => void;
  }
}

const pending = new Map<string, { resolve: (value: string) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>();
let sequence = 0;

export const nativeServerSetup: ServerSetup = {
  request(operation, value) {
    const bridge = typeof window === "undefined" ? undefined : window.HermesServer;
    if (!bridge) return Promise.reject(new Error("Connecting to a Hermes server needs the Android app."));
    window.__hermesServerResult = (id, ok, result) => {
      const entry = pending.get(id);
      if (!entry) return;
      pending.delete(id);
      clearTimeout(entry.timer);
      if (ok) entry.resolve(result);
      else entry.reject(new Error(result));
    };
    return new Promise((resolve, reject) => {
      const id = String(++sequence);
      // Sign-in waits for the system browser (native gives it 10 minutes). A probe on a slow server
      // can spend 45 s on /api/status and 30 s on the provider list.
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error("The server did not answer in time. Try again."));
      }, operation === "signIn" ? 610_000 : operation === "probe" ? 90_000 : operation === "test" ? 60_000 : 120_000);
      pending.set(id, { resolve, reject, timer });
      try {
        bridge.request(id, operation, value);
      } catch {
        pending.delete(id);
        clearTimeout(timer);
        reject(new Error("Native server setup is unavailable."));
      }
    });
  },
};

/** The page is served at the server origin; the setup origin means no server is chosen yet. */
export function currentServer(origin = globalThis.location?.origin ?? SETUP_ORIGIN): string {
  return origin === SETUP_ORIGIN ? "" : origin;
}
