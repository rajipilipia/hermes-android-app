/**
 * Hermes's own REST API, as Desktop's remote mode calls it (the app uses no PC add-on).
 * The page sends only a capabilityCall() result; native admits contract operations and builds the
 * request (see NativeApi.java). Replies carry the HTTP status and JSON body, never a credential.
 */
import type { capabilityCall } from "./capabilities";
import { foregroundRequired, isBackgrounded } from "../foreground";

export type NativeRest = (params: ReturnType<typeof capabilityCall>, timeoutMs?: number) => Promise<{ status: number; body: unknown }>;
interface NativeApiBridge { call(id: string, request: string): void; }
declare global {
  interface Window {
    HermesApi?: NativeApiBridge;
    __hermesApiResult?: (id: string, ok: boolean, value: string) => void;
  }
}

const pending = new Map<string, { resolve: (value: string) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>();
let sequence = 0;

export const nativeRest: NativeRest = (params, timeoutMs = 60_000) => {
  const bridge = typeof window === "undefined" ? undefined : window.HermesApi;
  if (!bridge) return Promise.reject(new Error("This Desktop feature needs the Android app."));
  if (isBackgrounded()) return Promise.reject(foregroundRequired());
  window.__hermesApiResult = (id, ok, value) => {
    const entry = pending.get(id);
    if (!entry) return;
    pending.delete(id);
    clearTimeout(entry.timer);
    if (ok) entry.resolve(value);
    else {
      const error = value === "PC_FOREGROUND_REQUIRED" ? foregroundRequired()
        : new Error(value === "PC_SIGN_IN_REQUIRED" ? "Sign in to this server again." : value);
      if (value === "PC_SIGN_IN_REQUIRED") error.name = "PcSignInRequired";
      entry.reject(error);
    }
  };
  return new Promise<string>((resolve, reject) => {
    const id = String(++sequence);
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error("The Hermes server did not answer in time."));
    }, Math.min(Math.max(timeoutMs, 1_000), 120_000) + 5_000);
    pending.set(id, { resolve, reject, timer });
    try {
      bridge.call(id, JSON.stringify(params));
    } catch {
      pending.delete(id);
      clearTimeout(timer);
      reject(new Error("Native Hermes REST is unavailable."));
    }
  }).then(raw => {
    const reply = JSON.parse(raw) as { status: number; body: string };
    let body: unknown = reply.body;
    try { body = reply.body ? JSON.parse(reply.body) : null; } catch { /* non-JSON error text stays text */ }
    return { status: reply.status, body };
  });
};
