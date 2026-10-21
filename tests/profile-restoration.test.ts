// @vitest-environment jsdom
import { afterAll, afterEach, expect, it, vi } from "vitest";
import { createDesktopHost } from "../src/desktop/host";

const origin = "https://gateway.example";
const key = `hermes.android.lastProfile.v1:${origin}`;
// Node 26 exposes a host localStorage getter even in jsdom. Use isolated browser storage.
const values = new Map<string, string>();
const localStorage = {
  getItem: (key: string) => values.get(key) ?? null,
  setItem: (key: string, value: string) => { values.set(key, value); },
  removeItem: (key: string) => { values.delete(key); },
  clear: () => values.clear(),
};
vi.stubGlobal("localStorage", localStorage);
afterAll(() => vi.unstubAllGlobals());
const hosts: ReturnType<typeof createDesktopHost>[] = [];
afterEach(() => { hosts.forEach(h => h.dispose()); hosts.length = 0; localStorage.clear(); });
function host(names = ["default", "research"], baseUrl = origin) {
  const rest = vi.fn(async (request: { operation: string }) => ({ status: 200, body:
    request.operation === "GET /api/profiles/active" ? { current: "default" }
      : { profiles: names.map(name => ({ name })) } }));
  const value = createDesktopHost({ baseUrl, auth: { signIn: vi.fn(), signOut: vi.fn(), ticket: vi.fn() }, rest });
  hosts.push(value);
  return value;
}
it("restores the phone's last profile without changing the server primary", async () => {
  localStorage.setItem(key, "research");
  const first = host();
  expect(await first.profile?.getDefault()).toEqual({ profile: "research" });
  expect(await first.getConnection()).toMatchObject({ profile: "default" });
  expect(await first.getConnection("research")).toMatchObject({ profile: "research" });
});
it("falls back when a remembered profile was deleted", async () => {
  localStorage.setItem(key, "research");
  expect(await host(["default"]).profile?.getDefault()).toEqual({ profile: null });
});
it("never restores one server's profile on another server", async () => {
  localStorage.setItem(key, "research");
  expect(await host(["default", "research"], "https://other.example").profile?.getDefault()).toEqual({ profile: null });
});
it("remembers selection locally across host recreation, not through a profile write API", async () => {
  await host().profile?.remember("research");
  expect(localStorage.getItem(key)).toBe("research");
  expect(await host().profile?.getDefault()).toEqual({ profile: "research" });
});
it("preserves primary routing without a remembered override or a valid persistence origin", async () => {
  expect(await host().profile.getDefault()).toEqual({ profile: null });
  localStorage.setItem(key, "default");
  expect(await host().profile.getDefault()).toEqual({ profile: null });
  expect(await host(["default"], "/").profile.getDefault()).toEqual({ profile: null });
});
