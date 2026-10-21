// Electron's connection-config IPC (Settings → Gateways, first-run remote setup) for Android.
// Mirrors Hermes Desktop v0.22.0 main.ts for the "remote" mode with native sign-in (RFC 8252).
// Hermes Cloud: an agent's own address with native sign-in (no Portal agent list on Android).
// SSH arrives in a later phase; Local cannot run on a phone.
import type {
  DesktopCloudAgentSignInResult,
  DesktopCloudDiscoverResult,
  DesktopCloudStatus,
  DesktopConnectionConfig,
  DesktopConnectionConfigInput,
  DesktopConnectionProbeResult,
  DesktopConnectionTestResult,
  DesktopOauthLoginResult,
  DesktopOauthLogoutResult,
} from "../../vendor/hermes/apps/desktop/src/global";
import type { PcAuth } from "../pc-auth";
import { currentServer, type ServerSetup } from "./server-setup";

export interface ConnectionConfigOptions {
  server: ServerSetup;
  auth: Pick<PcAuth, "signOut">;
  /** The page origin: the chosen server, or the setup origin before one is chosen. */
  origin?: () => string;
  /** The current server's sign-in was deleted: the open app cannot continue, so restart it at the sign-in panel. */
  signedOut?: () => void;
}

const PORTAL = "https://portal.nousresearch.com";
/** Desktop's own check for a Hermes Cloud agent dashboard (native checks it again). */
export const isCloudAgent = (url: string) => {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && !parsed.port && parsed.hostname.endsWith(".agents.nousresearch.com");
  } catch {
    return false;
  }
};
const CLOUD_HINT =
  "Hermes Android cannot sign in to the Nous Portal itself. The Portal is open in your browser: go to Cloud → Manage agents, make sure your agent is running, open its dashboard and copy the address (it ends in agents.nousresearch.com). Then paste it under Remote gateway and sign in.";

const unsupported = (input: DesktopConnectionConfigInput): string | null => {
  if (input.mode === "local") return "This phone cannot run a local Hermes backend. Choose Remote gateway.";
  if (input.mode === "cloud" && !isCloudAgent(String(input.remoteUrl ?? ""))) return CLOUD_HINT;
  if (input.mode === "ssh") return "Connect via SSH is not available in this Android build yet.";
  if (input.remoteAuthMode === "token") return "Hermes Android signs in with the server's sign-in page, not a session token. Use a gated server.";
  return null;
};

export function createConnectionConfig(options: ConnectionConfigOptions) {
  const server = () => currentServer(options.origin?.());
  const config = (profile: string | null, mode: DesktopConnectionConfig["mode"], remoteUrl: string): DesktopConnectionConfig => ({
    envOverride: false,
    mode,
    profile,
    remoteAuthMode: "oauth",
    remoteOauthConnected: mode === "remote" && !!remoteUrl && remoteUrl === server(),
    remoteTokenPreview: null,
    remoteTokenSet: false,
    secureTokenStorage: true,
    remoteTokenPlainText: false,
    remoteUrl,
    cloudOrg: "",
    sshHost: "",
    sshUser: "",
    sshPort: null,
    sshKeyPath: "",
    sshRemoteHermesPath: "",
    sshRemoteProfile: "",
  });
  // A named profile follows the phone's one server: Android has no per-profile overrides yet.
  const read = (profile?: string | null) =>
    profile ? config(profile, "local", "") : config(null, "remote", server());
  const target = (input: DesktopConnectionConfigInput) => {
    if (input.profile) {
      // Clearing an override that cannot exist is a no-op, as in Desktop.
      if (input.mode === "local") return null;
      throw new Error("Per-profile servers are not available on Android yet. All profiles use this phone's server.");
    }
    const reason = unsupported(input);
    if (reason) throw new Error(reason);
    const url = String(input.remoteUrl ?? "").trim();
    if (!url) throw new Error("Enter your Hermes server address.");
    return url;
  };
  return {
    getConnectionConfig: async (profile?: string | null): Promise<DesktopConnectionConfig> => read(profile),
    // Saving alone stores nothing: native saves a server only after the user confirms and signs in.
    saveConnectionConfig: async (input: DesktopConnectionConfigInput): Promise<DesktopConnectionConfig> => {
      const url = target(input);
      return url === null ? read(input.profile) : config(null, "remote", url);
    },
    applyConnectionConfig: async (input: DesktopConnectionConfigInput): Promise<DesktopConnectionConfig> => {
      const url = target(input);
      if (url === null) return read(input.profile);
      // Native reloads the page at the server origin; this document ends here.
      const origin = await options.server.request("apply", url);
      return config(null, "remote", origin);
    },
    testConnectionConfig: async (input: DesktopConnectionConfigInput): Promise<DesktopConnectionTestResult> => {
      let url: string | null;
      try {
        url = target(input);
      } catch (error) {
        return { ok: false, reachable: false, error: error instanceof Error ? error.message : String(error) };
      }
      if (url === null) return { ok: true, reachable: true };
      try {
        const baseUrl = await options.server.request("test", url);
        return { ok: true, reachable: true, baseUrl };
      } catch (error) {
        return { ok: false, reachable: false, baseUrl: url, error: error instanceof Error ? error.message : String(error) };
      }
    },
    probeConnectionConfig: async (remoteUrl: string): Promise<DesktopConnectionProbeResult> => {
      try {
        const result = JSON.parse(await options.server.request("probe", remoteUrl)) as DesktopConnectionProbeResult;
        return {
          baseUrl: String(result.baseUrl),
          reachable: result.reachable === true,
          authMode: result.authMode === "oauth" || result.authMode === "token" ? result.authMode : "unknown",
          providers: Array.isArray(result.providers) ? result.providers : [],
          version: typeof result.version === "string" ? result.version : null,
          error: typeof result.error === "string" ? result.error : null,
        };
      } catch (error) {
        // Desktop's probe never throws: an invalid or unreachable address is "can't tell yet".
        return { baseUrl: remoteUrl, reachable: false, authMode: "unknown", providers: [], version: null, error: error instanceof Error ? error.message : String(error) };
      }
    },
    oauthLoginConnectionConfig: async (remoteUrl: string): Promise<DesktopOauthLoginResult> => {
      try {
        const baseUrl = await options.server.request("signIn", remoteUrl);
        globalThis.dispatchEvent?.(new Event("hermes:server-signed-in"));
        return { ok: true, baseUrl, connected: true };
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        // The card already says sign-in did not complete; a cancel needs no extra detail.
        return { ok: false, baseUrl: remoteUrl, connected: false, ...(message === "Cancelled." ? {} : { error: message }) };
      }
    },
    // Desktop's Portal session (hidden cookie window) cannot be copied safely, so there is no agent
    // list: login opens the Portal and says where to paste the agent address. Agent sign-in is the
    // same native browser sign-in as Remote gateway, limited to agent dashboards.
    cloud: {
      status: async (): Promise<DesktopCloudStatus> => ({ portalBaseUrl: PORTAL, signedIn: false }),
      login: async (): Promise<DesktopCloudStatus & { ok: boolean }> => {
        await options.server.request("portal", "");
        throw new Error(CLOUD_HINT);
      },
      logout: async (): Promise<DesktopCloudStatus & { ok: boolean }> => ({ ok: true, portalBaseUrl: PORTAL, signedIn: false }),
      discover: async (_org?: string): Promise<DesktopCloudDiscoverResult> => {
        throw Object.assign(new Error(CLOUD_HINT), { needsCloudLogin: true });
      },
      agentSignIn: async (dashboardUrl: string): Promise<DesktopCloudAgentSignInResult> => {
        if (!isCloudAgent(dashboardUrl)) throw new Error("That is not a Hermes Cloud agent address.");
        try {
          return { baseUrl: await options.server.request("cloudSignIn", dashboardUrl), connected: true };
        } catch {
          return { baseUrl: dashboardUrl, connected: false };
        }
      },
    },
    oauthLogoutConnectionConfig: async (remoteUrl: string): Promise<DesktopOauthLogoutResult> => {
      let origin = "";
      try { origin = new URL(remoteUrl).origin; } catch { /* not this server */ }
      // Only the phone's current server has a sign-in to delete; the deletion is acknowledged natively.
      if (origin && origin === server()) {
        await options.auth.signOut();
        // After Desktop's card settles; without it the open chat waits on a socket that cannot sign in (NG-2b).
        if (options.signedOut) setTimeout(options.signedOut, 0);
      }
      return { ok: true, connected: false };
    },
  };
}
