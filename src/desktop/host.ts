// Android/browser host seam. Implemented by behavior-first tracer bullets.
import type { PcAuth } from "../pc-auth";
import type { HermesApiRequest } from "../../vendor/hermes/apps/desktop/src/global";
import {
  canonicalProfile,
  capabilityCall,
  validateCapabilityRequest,
} from "./capabilities";
import { createNotificationHost } from "./notifications";
import { createSelectedFiles } from "./media-files";
import { createConnectionConfig } from "./connection-config";
import { nativeServerSetup, type ServerSetup } from "./server-setup";
import { nativeRest, type NativeRest } from "./native-api";
import { openExternal } from "./native-browser";
import { contextMenuEdit } from "./clipboard";
import { noteFileDenial } from "./file-denial";
import { diag } from "./diag";
/** Time in the background after which coming back counts as a wake (sockets may be stale). */
export const WAKE_AFTER_MS = 30_000;
export interface HostOptions {
  auth: PcAuth;
  baseUrl?: string;
  server?: ServerSetup;
  /** Hermes REST (the server's own API, as Desktop's remote mode uses); defaults to the native HermesApi bridge. */
  rest?: NativeRest;
  /** Settings signed the phone out of its server: restart at the sign-in panel. */
  signedOut?: () => void;
}
export function installDesktopHost(options: HostOptions) {
  const host = createDesktopHost(options);
  // The Electron declaration includes native-only mandatory members. Android
  // deliberately exposes only implemented capabilities; feature probes stay honest.
  window.hermesDesktop = host as unknown as Window["hermesDesktop"];
  return host;
}
/**
 * Native only (the author 2026-10-20): the phone talks to the user's own Hermes exactly as Desktop's
 * remote mode does. Desktop features use Hermes's own REST API (native adds the Bearer token and
 * allows only contract operations); chat, attachments and streams use Hermes's own sockets. No
 * PC add-on is needed or used.
 */
export function createDesktopHost(options: HostOptions) {
  // The bundled page is served at the chosen server origin (native-validated), so it is the WS origin too.
  const baseUrl = options.baseUrl ?? globalThis.location?.origin ?? "";
  const noEvents = (_callback: (...args: never[]) => unknown) => () => {};
  const rest = (): NativeRest => {
    const call = options.rest ?? (typeof window !== "undefined" && window.HermesApi ? nativeRest : undefined);
    if (!call) throw new Error("This Desktop feature needs the Android app.");
    return call;
  };
  let disposed = false;
  const assertOpen = () => {
    if (disposed) throw new Error("Android connection has been closed.");
  };
  const mintGatewayWsUrl = async (profile?: string | null) => {
    assertOpen();
    canonicalProfile(profile);
    const url = new URL("/api/ws", baseUrl);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.searchParams.set("ticket", await options.auth.ticket());
    assertOpen();
    return url.toString();
  };
  // The primary profile is the one this server runs as (Desktop's "current"). One lookup is
  // shared by concurrent callers; a failure is not remembered, so the next caller asks again.
  let primary: Promise<string> | undefined;
  const bootstrap = (): Promise<string> => {
    assertOpen();
    primary ??= (async () => {
      const reply = await rest()(capabilityCall({ path: "/api/profiles/active" }), 30_000);
      assertOpen();
      const current = (reply.body as { current?: unknown } | null)?.current;
      if (reply.status !== 200 || typeof current !== "string")
        throw new Error(`Hermes server profile lookup failed (${reply.status}).`);
      return canonicalProfile(current);
    })().catch((error: unknown) => {
      primary = undefined;
      throw error;
    });
    return primary;
  };
  const getGatewayWsUrl = async (profile?: string | null) => {
    canonicalProfile(profile);
    if (profile == null) await bootstrap();
    return mintGatewayWsUrl(profile);
  };
  // Desktop's power-resume signal (macOS/Windows wake): Desktop then probes and, if needed, redials
  // the gateway socket. On a phone the same thing happens when Hermes comes back after time in the
  // background: Android may have frozen the app and dropped its sockets without a close event.
  // Short app switches only get Desktop's ordinary visibility nudge.
  const onPowerResume = (callback: () => void) => {
    let pausedAt: number | undefined;
    const onLifecycle = (event: Event) => {
      const state = (event as CustomEvent<{ state?: string }>).detail?.state;
      if (state === "pause") pausedAt ??= Date.now();
      if (state !== "resume" || pausedAt === undefined) return;
      const away = Date.now() - pausedAt;
      pausedAt = undefined;
      if (away < WAKE_AFTER_MS || disposed) return;
      diag("app_wake", { away_ms: away });
      callback();
    };
    window.addEventListener("hermes:native-lifecycle", onLifecycle);
    return () => window.removeEventListener("hermes:native-lifecycle", onLifecycle);
  };
  const selectedFiles = createSelectedFiles(() => disposed);
  const notifications = createNotificationHost();
  // A phone selection is local UI state, never a server profile/config write.
  const profileKey = (() => {
    try {
      const origin = new URL(baseUrl).origin;
      return origin === "null" ? undefined : `hermes.android.lastProfile.v1:${origin}`;
    } catch { return undefined; }
  })();
  const profile = {
    remember: async (name: string) => {
      assertOpen();
      const selected = canonicalProfile(name);
      try { if (profileKey) window.localStorage.setItem(profileKey, selected); } catch { /* storage unavailable */ }
      return { profile: selected };
    },
    getDefault: async () => {
      const fallback = await bootstrap();
      let selected: string;
      try {
        const saved = profileKey ? window.localStorage.getItem(profileKey) : null;
        // No remembered override: preserve the genuine primary-route bootstrap.
        if (!saved || saved === fallback) return { profile: null };
        selected = canonicalProfile(saved);
      } catch { return { profile: null }; }
      // Validate a remembered owner against this server before opening its history.
      const result = await rest()(capabilityCall({ path: "/api/profiles" }), 30_000);
      assertOpen();
      const rows = (result.body as { profiles?: { name?: unknown }[] } | null)?.profiles;
      if (result.status !== 200 || !Array.isArray(rows)) throw new Error("Hermes profile list is unavailable.");
      return { profile: rows.some(row => row?.name === selected) ? selected : null };
    },
  };
  return {
    profile,
    dispose: () => {
      disposed = true;
      notifications.dispose();
      selectedFiles.dispose();
    },
    bootstrap,
    notify: notifications.notify,
    onFocusSession: notifications.onFocusSession,
    onNotificationAction: notifications.onNotificationAction,
    onNotificationActivate: notifications.onNotificationActivate,
    cancelNotification: notifications.cancelNotification,
    selectPaths: selectedFiles.selectPaths,
    getPathForFile: selectedFiles.register,
    readFileDataUrl: selectedFiles.readFileDataUrl,
    savePastedText: selectedFiles.savePastedText,
    saveImageBuffer: selectedFiles.saveImageBuffer,
    api: async <T = unknown>(request: HermesApiRequest): Promise<T> => {
      assertOpen();
      validateCapabilityRequest(request);
      // Capture routing and arguments before suspension. Only absent/null owner
      // means primary; the explicit string default always means canonical root.
      const params = capabilityCall(request);
      const explicitProfile = canonicalProfile(request.profile);
      const timeoutMs = request.timeoutMs;
      params.profile = request.profile == null ? await bootstrap() : explicitProfile;
      // Structure-only timing for connection diagnosis (operation id, ms, status; never values).
      const started = Date.now();
      const timing = (status: number | string) =>
        console.info(`hermes-android timing op="${params.operation}" via=rest ms=${Date.now() - started} status=${status}`);
      let response: { status: number; body: unknown };
      try {
        response = await rest()(params, timeoutMs);
      } catch (error) {
        timing(error instanceof Error ? error.name : "error");
        throw error;
      }
      timing(response?.status ?? "invalid");
      if (response?.status >= 400) noteFileDenial(params, response);
      assertOpen();
      if (
        !Number.isInteger(response?.status) ||
        response.status < 200 ||
        response.status >= 300
      )
        throw new Error(
          `Hermes server request failed (${response?.status ?? "invalid response"}).`,
        );
      return response.body as T;
    },
    glassSupported: false,
    translucencySupported: false,
    localModelsEnabled: false,
    assumeFreshInstall: false,
    localSkin: null,
    onBootProgress: noEvents,
    onBackendExit: noEvents,
    onPreviewFileChanged: noEvents,
    getBootProgress: async () => ({
      error: null,
      fakeMode: false,
      message:
        "Android host ready; server sign-in and transport are checked separately.",
      phase: "ready",
      progress: 1,
      running: false,
      timestamp: Date.now(),
    }),
    getBootstrapState: async () => ({
      active: false,
      manifest: null,
      stages: {},
      error: null,
      log: [],
      startedAt: null,
      completedAt: null,
      setupChoice: null,
      unsupportedPlatform: null,
      bundled: false,
    }),
    getRecentLogs: async () => ({
      path: "",
      lines: ["Android does not own a local Hermes backend."],
    }),
    getGatewayWsUrl,
    onPowerResume,
    openExternal,
    contextMenuEdit,
    ...createConnectionConfig({ server: options.server ?? nativeServerSetup, auth: options.auth, signedOut: options.signedOut }),
    getConnection: async (profile?: string | null) => {
      assertOpen();
      const primaryProfile = profile == null ? await bootstrap() : undefined;
      return {
        baseUrl,
        mode: "remote" as const,
        authMode: "oauth" as const,
        token: "",
        wsUrl: "",
        profile: primaryProfile ?? canonicalProfile(profile),
        sharedPrimary: true,
        isFullscreen: false,
        nativeOverlayWidth: 0,
        windowButtonPosition: null,
        logs: [],
      };
    },
  };
}
