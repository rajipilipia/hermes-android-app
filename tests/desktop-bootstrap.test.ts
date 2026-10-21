// @vitest-environment jsdom
import { afterEach, describe, it, expect, vi } from "vitest";
import { readFileSync } from "node:fs";
import { installDesktopHost } from "../src/desktop/host";
import { Peer } from "./fixture";
import {
  configureGatewayRegistry,
  setPrimaryGateway,
  requestGatewayForProfile,
} from "../vendor/hermes/apps/desktop/src/store/gateway";
import {
  getStatus,
  getHermesConfigDefaults,
  getHermesConfigSchema,
  getEnvVars,
} from "../vendor/hermes/apps/desktop/src/api/config";
import { getGlobalModelOptions } from "../vendor/hermes/apps/desktop/src/api/models";
import {
  listSidebarSessions,
  listAllProfileSessions,
  searchSessions,
  getSessionMessages,
} from "../vendor/hermes/apps/desktop/src/api/sessions";
import {
  setApiRequestProfile,
  setApiRequestConnection,
} from "../vendor/hermes/apps/desktop/src/api/client";
import { desktopDefaultCwd } from "../vendor/hermes/apps/desktop/src/lib/desktop-fs";
import { setConnection } from "../vendor/hermes/apps/desktop/src/store/session";
import {
  refreshActiveProfile,
  $activeProfile,
} from "../vendor/hermes/apps/desktop/src/store/profile";

// Explicit synthetic DTOs validate the actual pinned renderer helper -> bridge
// seam. They are NOT original-service, live-PC, cold-UI or Android evidence.
const startupFixtures: Record<string, unknown> = {
  "GET /api/status": {
    version: "fixture",
    gateway_running: true,
    gateway_state: "running",
  },
  "GET /api/profiles/active": { active: "default", current: "default" },
  "GET /api/profiles": {
    profiles: [
      { name: "default", is_default: true },
      { name: "example-profile", is_default: false },
    ],
  },
  "GET /api/config/defaults": {
    display: { show_reasoning: true },
    compression: { enabled: true },
  },
  "GET /api/config/schema": {
    fields: {
      "display.show_reasoning": {
        type: "bool",
        category: "Display",
        description: "Show reasoning",
      },
    },
    category_order: ["Display"],
  },
  "GET /api/env": {
    OPENAI_API_KEY: {
      is_set: true,
      is_password: true,
      description: "Provider authentication",
    },
  },
  "GET /api/model/options": {
    model: "fixture-model",
    provider: "fixture",
    providers: [
      {
        slug: "fixture",
        name: "Fixture",
        models: ["fixture-model"],
        authenticated: true,
        aliases: ["fixture-alias"],
      },
    ],
  },
  "GET /api/fs/default-cwd": {
    cwd: "C:\\work\\ქართული #?&%2f",
    branch: "fixture-branch",
  },
  "GET /api/profiles/sessions/sidebar": {
    recents: {
      sessions: [],
      profiles_truncated: { "example-profile": false },
      profiles_usage: { "example-profile": { cost_usd: 0.25, tokens: 40 } },
    },
    cron: { sessions: [] },
    messaging: { sessions: [], total: 0 },
    errors: [],
    storage: {},
  },
  "GET /api/profiles/sessions": {
    sessions: [],
    total: 0,
    limit: 200,
    offset: 0,
    profile_totals: { "example-profile": 0 },
    errors: [],
  },
  "GET /api/sessions/search": {
    results: [
      { session_id: "saved-1", title: "Fixture match", profile: "example-profile" },
    ],
  },
  "GET /api/sessions/{session_id}/messages": {
    session_id: "saved-1",
    profile: "example-profile",
    messages: [{ role: "assistant", content: "Fixture reply" }],
    pagination: { limit: 120, offset: 0, order: "latest", has_more: false },
  },
};

function startupHost() {
  // Hermes's own REST through the native bridge (synthetic fixtures).
  const rpc = vi.fn(
    async (params: Record<string, unknown>, _timeoutMs?: number) => {
      const operation = String(params.operation);
      if (operation === "GET /api/profiles/active")
        return { status: 200, body: { active: "default", current: "default" } };
      if (!Object.hasOwn(startupFixtures, operation))
        throw new Error(`No fixture for ${operation}`);
      return { status: 200, body: structuredClone(startupFixtures[operation]) };
    },
  );
  const host = installDesktopHost({
    auth: {
      signIn: async () => {},
      signOut: async () => {},
      ticket: async () => "synthetic-ticket",
    },
    rest: rpc,
  });
  return { host, rpc };
}

afterEach(() => {
  setPrimaryGateway(null);
  setApiRequestProfile(null);
  setApiRequestConnection(null);
  setConnection(null);
  delete (window as unknown as { hermesDesktop?: unknown }).hermesDesktop;
});

describe("Desktop Android bootstrap", () => {
  it("uses the real shared-primary dispatcher to stamp named create/resume/prompt RPCs, not an ignored WS query", async () => {
    const { host } = startupHost();
    const peer = new Peer();
    const client = peer.client();
    const url = new URL(await host.getGatewayWsUrl("example-profile"));
    expect(url.searchParams.has("profile")).toBe(false);
    await client.connect(url.toString());
    configureGatewayRegistry({ onEvent: () => {} });
    setPrimaryGateway(client as never, "default");
    try {
      await requestGatewayForProfile("example-profile", "session.create", {
        source: "desktop",
      });
      await requestGatewayForProfile("example-profile", "session.resume", {
        session_id: "stored-1",
      });
      await requestGatewayForProfile("example-profile", "prompt.submit", {
        session_id: "runtime-1",
        text: "Synthetic unsent-to-provider fixture",
      });
      expect(
        peer.calls.map((call) => ({
          method: call.method,
          params: call.params,
        })),
      ).toEqual([
        {
          method: "session.create",
          params: { source: "desktop", profile: "example-profile" },
        },
        {
          method: "session.resume",
          params: { session_id: "stored-1", profile: "example-profile" },
        },
        {
          method: "prompt.submit",
          params: {
            session_id: "runtime-1",
            text: "Synthetic unsent-to-provider fixture",
            profile: "example-profile",
          },
        },
      ]);
    } finally {
      setPrimaryGateway(null);
      client.close();
      host.dispose();
    }
  });
  it("runs the actual startup helper burst on the captured named owner and preserves finite DTOs", async () => {
    const { host, rpc } = startupHost();
    setConnection(await host.getConnection("example-profile"));
    setApiRequestProfile("example-profile");
    const results = await Promise.all([
      getStatus(),
      getHermesConfigDefaults(),
      getHermesConfigSchema(),
      getEnvVars(),
      getGlobalModelOptions(),
      desktopDefaultCwd(),
    ]);
    const operations = [
      "GET /api/status",
      "GET /api/config/defaults",
      "GET /api/config/schema",
      "GET /api/env",
      "GET /api/model/options",
      "GET /api/fs/default-cwd",
    ];
    expect(results).toEqual(
      operations.map((operation) => startupFixtures[operation]),
    );
    expect(rpc.mock.calls.map((call) => call[0]).filter((call) => call.operation !== "GET /api/profiles/active")).toEqual(
      operations.map((operation) => ({
        operation,
        profile: "example-profile",
        pathParams: {},
        query:
          operation === "GET /api/model/options" ? { explicit_only: true } : {},
      })),
    );
    host.dispose();
  });

  it("hydrates primary active-profile presentation without a sticky-profile write or named-owner drift", async () => {
    const { host, rpc } = startupHost();
    $activeProfile.set("previous");
    await refreshActiveProfile();
    expect($activeProfile.get()).toBe("default");
    expect(rpc.mock.calls.map((call) => call[0])).toEqual([
      // The host's primary lookup (Desktop's "current" profile), then Desktop's own reads.
      { operation: "GET /api/profiles/active", profile: "default", pathParams: {}, query: {} },
      {
        operation: "GET /api/profiles/active",
        profile: "default",
        pathParams: {},
        query: {},
      },
      {
        operation: "GET /api/profiles",
        profile: "default",
        pathParams: {},
        query: {},
      },
    ]);
    // A concrete scoped read is an explicit owner, not global active state.
    await host.api({ path: "/api/profiles/active", profile: "example-profile" });
    expect(rpc.mock.calls.at(-1)?.[0]).toEqual({
      operation: "GET /api/profiles/active",
      profile: "example-profile",
      pathParams: {},
      query: {},
    });
    expect(host.profile.getDefault).toBeTypeOf("function");
    expect(host.profile.remember).toBeTypeOf("function");
    expect(host.profile).not.toHaveProperty("setDefault");
    expect(host.profile).not.toHaveProperty("set");
    host.dispose();
  });

  it("runs actual sidebar, aggregate, search and message helpers without stripping real selectors", async () => {
    const { host, rpc } = startupHost();
    setApiRequestProfile("example-profile");
    expect(
      await listSidebarSessions({
        recentsProfile: "all",
        recentsLimit: 30,
        cronLimit: 50,
        messagingLimit: 40,
        recentsExclude: ["cron", "telegram"],
        messagingExclude: ["desktop"],
      }),
    ).toMatchObject(
      startupFixtures["GET /api/profiles/sessions/sidebar"] as object,
    );
    expect(
      await listAllProfileSessions(200, 1, "exclude", "recent", "all"),
    ).toEqual(startupFixtures["GET /api/profiles/sessions"]);
    expect(await searchSessions("ქართული #?&%2f", "example-profile")).toEqual(
      startupFixtures["GET /api/sessions/search"],
    );
    expect(
      await getSessionMessages("saved-1", "example-profile", {
        limit: 120,
        order: "latest",
        includeCompacted: true,
      }),
    ).toEqual(startupFixtures["GET /api/sessions/{session_id}/messages"]);
    expect(rpc.mock.calls.map((call) => call[0]).filter((call) => call.operation !== "GET /api/profiles/active")).toEqual([
      {
        operation: "GET /api/profiles/sessions/sidebar",
        profile: "example-profile",
        pathParams: {},
        query: {
          recents_profile: "all",
          recents_limit: 30,
          cron_limit: 50,
          messaging_limit: 40,
          recents_exclude: "cron,telegram",
          messaging_exclude: "desktop",
        },
      },
      {
        operation: "GET /api/profiles/sessions",
        profile: "example-profile",
        pathParams: {},
        query: {
          limit: 200,
          offset: 0,
          min_messages: 1,
          archived: "exclude",
          order: "recent",
          profile: "all",
        },
      },
      {
        operation: "GET /api/sessions/search",
        profile: "example-profile",
        pathParams: {},
        query: { q: "ქართული #?&%2f" },
      },
      {
        operation: "GET /api/sessions/{session_id}/messages",
        profile: "example-profile",
        pathParams: { session_id: "saved-1" },
        query: { limit: 120, order: "latest", include_compacted: true },
      },
    ]);
    host.dispose();
  });
  it("installs the Android host before dynamically mounting the pinned genuine renderer, not the old prototype", () => {
    const entry = readFileSync("src/main.tsx", "utf8");
    expect(entry).toContain("installDesktopHost");
    expect(entry).toMatch(
      /import\(['"]\.\.\/vendor\/hermes\/apps\/desktop\/src\/main['"]\)/,
    );
    expect(entry).not.toContain("./App");
    expect(entry.indexOf("installDesktopHost(")).toBeLessThan(
      entry.lastIndexOf("import("),
    );
  });
});
