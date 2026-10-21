import { expect, it, vi } from "vitest";
import { makeNotificationRouting } from "../src/desktop/notification-routing";
it("resolves a captured runtime to its durable owner without active/default substitution", async () => {
  let active = "example-profile";
  const ensure = vi.fn(async (profile: string) => { active = profile; });
  const hint = vi.fn();
  const route = makeNotificationRouting({ owner: () => ({ connectionId: "local", profile: "EstDept", mode: "remote" }), stored: () => "stored-1", active: () => active, ensure, hint, path: value => value?.startsWith("/") ? value : undefined });
  const captured = route.capture({ kind: "approval", sessionId: "runtime-1", title: "Fixture" });
  expect(captured).toEqual({ profile: "EstDept", sessionId: "runtime-1", storedSessionId: "stored-1" });
  await route.open(captured!, () => true);
  expect(ensure).toHaveBeenCalledWith("EstDept");
  expect(hint).toHaveBeenCalledWith("stored-1", "EstDept");
});
it("rejects unknown, foreign and mismatched ownership instead of normalizing to default", async () => {
  let owner: unknown;
  const hint = vi.fn();
  const route = makeNotificationRouting({ owner: () => owner as any, stored: () => "stored-1", active: () => "example-profile", ensure: async () => {}, hint, path: () => undefined });
  const input = { kind: "approval" as const, title: "Fixture", sessionId: "runtime-1" };
  for (owner of [undefined, { profile: "EstDept", connectionId: "other-pc" }, { profile: "EstDept", connectionId: "local", targetProfile: "other" }]) expect(route.capture(input)).toBeUndefined();
  await expect(route.open({ profile: "EstDept", storedSessionId: "stored-1" }, () => true)).rejects.toThrow("owner");
  expect(hint).not.toHaveBeenCalled();
  await expect(route.open({ profile: "example-profile", storedSessionId: "stored-1" }, () => false)).rejects.toThrow("stale");
});
