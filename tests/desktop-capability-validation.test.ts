import { describe, expect, it, vi } from "vitest";
import type { HermesApiRequest } from "../vendor/hermes/apps/desktop/src/global";
import { capabilityCall } from "../src/desktop/capabilities";
import { createDesktopHost } from "../src/desktop/host";

const makeHost = () => {
  const ticket = vi.fn(async () => "one-use");
  // Hermes's own REST through the native bridge (synthetic, unconfigured).
  const rest = vi.fn(
    async (_params: unknown, _timeoutMs?: number): Promise<{ status: number; body: unknown }> => ({
      status: 503,
      body: { detail: "Unconfigured synthetic peer" },
    }),
  );
  return {
    ticket,
    rpc: rest,
    host: createDesktopHost({
      auth: { ticket, signIn: async () => {}, signOut: async () => {} },
      rest,
    }),
  };
};

describe("Desktop request validation", () => {
  it.each([
    [
      "/api/sessions/search?q=ქართული%20%23%3F%26%252f&profile=example-profile",
      "GET /api/sessions/search",
      { q: "ქართული #?&%2f" },
    ],
    [
      "/api/sessions/saved-1?profile=example-profile",
      "GET /api/sessions/{session_id}",
      {},
    ],
    [
      "/api/sessions/saved-1/messages?profile=example-profile&order=latest&include_compacted=true",
      "GET /api/sessions/{session_id}/messages",
      { order: "latest", include_compacted: true },
    ],
    [
      "/api/sessions/saved-1/timeline?profile=example-profile&after_row_id=0&limit=500",
      "GET /api/sessions/{session_id}/timeline",
      { after_row_id: 0, limit: 500 },
    ],
    [
      "/api/sessions/saved-1/messages/around?row_id=42&profile=example-profile&limit=120",
      "GET /api/sessions/{session_id}/messages/around",
      { row_id: 42, limit: 120 },
    ],
  ])(
    "maps a redundant upstream profile query only to its already captured owner: %s",
    (path, operation, query) => {
      expect(
        capabilityCall({ path: path as string, profile: "example-profile" }),
      ).toEqual({
        operation,
        profile: "example-profile",
        pathParams: (path as string).includes("/saved-1")
          ? { session_id: "saved-1" }
          : {},
        query,
      });
    },
  );
  it.each([
    ["1", true],
    ["0", false],
  ])(
    "decodes the actual Desktop model-picker flag %s into JSON %s",
    (raw, value) => {
      expect(
        capabilityCall({
          path: `/api/model/options?explicit_only=${raw}&include_unconfigured=${raw}&refresh=${raw}`,
          profile: "example-profile",
        }),
      ).toEqual({
        operation: "GET /api/model/options",
        profile: "example-profile",
        pathParams: {},
        query: {
          explicit_only: value,
          include_unconfigured: value,
          refresh: value,
        },
      });
    },
  );
  it.each(["all", "example-profile", "default"])(
    "preserves declared aggregate selector %s independently of the canonical owner",
    (selector) => {
      expect(
        capabilityCall({
          path: `/api/profiles/sessions?profile=${selector}&limit=200&offset=20&min_messages=1&archived=include&order=recent&exclude_sources=cron%2Ctelegram`,
          profile: "work",
        }),
      ).toEqual({
        operation: "GET /api/profiles/sessions",
        profile: "work",
        pathParams: {},
        query: {
          profile: selector,
          limit: 200,
          offset: 20,
          min_messages: 1,
          archived: "include",
          order: "recent",
          exclude_sources: "cron,telegram",
        },
      });
      expect(
        capabilityCall({
          path: `/api/profiles/sessions/sidebar?recents_profile=${selector}&recents_limit=30&cron_limit=50&messaging_limit=40&recents_exclude=cron%2Ctelegram&messaging_exclude=desktop`,
          profile: "work",
        }),
      ).toEqual({
        operation: "GET /api/profiles/sessions/sidebar",
        profile: "work",
        pathParams: {},
        query: {
          recents_profile: selector,
          recents_limit: 30,
          cron_limit: 50,
          messaging_limit: 40,
          recents_exclude: "cron,telegram",
          messaging_exclude: "desktop",
        },
      });
    },
  );

  it("defaults owner independently of aggregate selectors and never invents one from query.profile", () => {
    expect(
      capabilityCall({ path: "/api/profiles/sessions?profile=all" }),
    ).toMatchObject({
      profile: "default",
      query: { profile: "all" },
    });
    expect(
      capabilityCall({ path: "/api/sessions/search?q=hello&profile=default" }),
    ).toMatchObject({
      profile: "default",
      query: { q: "hello" },
    });
    expect(() =>
      capabilityCall({ path: "/api/sessions/search?q=hello&profile=example-profile" }),
    ).toThrow();
  });

  it.each([
    "/api/sessions/search?q=x&profile=all",
    "/api/sessions/search?q=x&profile=work",
    "/api/sessions/search?q=x&profile=example-profile&profile=example-profile",
    "/api/profiles?profile=example-profile",
    "/api/profiles/active?profile=example-profile",
    "/api/model/options?recents_profile=all",
    "/api/profiles/sessions?profile=current",
    "/api/profiles/sessions?profile=Work",
    "/api/profiles/sessions?profile=root",
    "/api/profiles/sessions?profile=all&profile=example-profile",
    "/api/profiles/sessions/sidebar?profile=all",
    "/api/profiles/sessions/sidebar?recents_profile=all&recents_profile=all",
    "/api/profiles/sessions/sidebar?recents_profile=default%20",
    "/api/sessions?limit=200",
    "/api/sessions/saved-1/messages/around?row_id=0",
    "/api/sessions/saved-1/messages/around?limit=10",
    "/api/sessions/saved-1/timeline?after_row_id=-1",
    "/api/sessions/saved-1/timeline?limit=501",
    "/api/sessions/search?q=a&q=b",
    "/api/model/options?explicit_only=1&explicit_only=0",
    "/api/model/options?explicit_only=TRUE",
    "/api/model/options?explicit_only=yes",
    "/api/model/options?explicit_only=2",
    "/api/model/options?explicit_only=01",
    "/api/model/options?explicit_only=",
    "/api/model/options?refresh=null",
  ])(
    "rejects invalid, duplicated or authority-confused typed selectors: %s",
    (path) => {
      expect(() => capabilityCall({ path, profile: "example-profile" })).toThrow();
    },
  );

  it("does not coerce string fields which happen to contain boolean spellings", () => {
    expect(
      capabilityCall({ path: "/api/sessions/search?q=1&source=0" }).query,
    ).toEqual({ q: "1", source: "0" });
  });

  it.each([
    "/srv/project/a b.txt",
    "C:\\work\\project\\a b.txt",
    "/srv/project/ქართული #?&%2f.txt",
  ])("preserves the decoded filesystem query exactly: %s", (path) => {
    expect(
      capabilityCall({
        path: `/api/fs/read-text?path=${encodeURIComponent(path)}`,
        profile: "example-profile",
      }),
    ).toEqual({
      operation: "GET /api/fs/read-text",
      profile: "example-profile",
      pathParams: {},
      query: { path },
    });
  });

  it.each(["headers", "url", "principal"])(
    "rejects unknown %s fields before both RPC and local voice policy",
    async (field) => {
      const { host, rpc, ticket } = makeHost();
      for (const path of ["/api/profiles", "/api/audio/voice-config"]) {
        const request = {
          path,
          [field]: "not a supported field",
        } as HermesApiRequest;
        await expect(host.api(request)).rejects.toThrow();
      }
      expect(rpc).not.toHaveBeenCalled();
      expect(ticket).not.toHaveBeenCalled();
    },
  );

  it.each([
    "all",
    "current",
    "hermes",
    "test",
    "tmp",
    "root",
    "sudo",
    "Default",
    "Work",
    "default ",
    "",
    "a".repeat(65),
  ])(
    "rejects noncanonical profile %j before API, descriptor and socket operations",
    async (profile) => {
      const { host, rpc, ticket } = makeHost();
      for (const path of ["/api/profiles", "/api/audio/voice-config"])
        await expect(host.api({ path, profile })).rejects.toThrow();
      await expect(host.getConnection(profile)).rejects.toThrow();
      await expect(host.getGatewayWsUrl(profile)).rejects.toThrow();
      expect(rpc).not.toHaveBeenCalled();
      expect(ticket).not.toHaveBeenCalled();
    },
  );

  it("accepts documented Desktop routing hints without forwarding extra authority", () => {
    expect(
      capabilityCall({
        path: "/api/profiles",
        connectionId: "pc",
        profile: "example-profile",
        passive: true,
        priority: "foreground",
        timeoutMs: 45000,
      }),
    ).toEqual({
      operation: "GET /api/profiles",
      profile: "example-profile",
      pathParams: {},
      query: {},
    });
  });

  it.each([
    "/api/sessions/%2fother",
    "/api/sessions/%5cother",
    "/api/sessions/%2e%2e/other",
    "/api/sessions/../profiles",
    "/api/profiles#other",
    "https://other.invalid/api/profiles",
    "/api/fs/read-text?path=%00",
    "/api/fs/read-text?path=a&path=b",
  ])("retains strict route and typed-query checks for %s", (path) => {
    expect(() => capabilityCall({ path })).toThrow();
  });

  it("never asks Hermes for voice provider keys; Desktop then uses Hermes's own relay routes", async () => {
    const { host, rpc } = makeHost();
    await expect(
      host.api({ path: "/api/audio/voice-config", connectionId: "pc", profile: "example-profile" }),
    ).rejects.toThrow();
    expect(rpc).not.toHaveBeenCalled();
  });
});
