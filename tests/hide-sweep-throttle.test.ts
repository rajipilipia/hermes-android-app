import { describe, expect, it } from "vitest";
import fs from "node:fs";
import { patchHideSweepThrottle, HIDE_SWEEP_MIN_INTERVAL_MS } from "../src/desktop/hide-sweep-throttle";

const rel = "plugins/hermes-bots/session-sweep.ts";
const id = `/x/vendor/hermes/apps/desktop/src/${rel}`;
const code = fs.readFileSync(`vendor/hermes/apps/desktop/src/${rel}`, "utf8");

describe("Hermes Bots hide sweep on a phone", () => {
  it("runs on load and the first 'open', then at most once per 10 minutes", () => {
    expect(HIDE_SWEEP_MIN_INTERVAL_MS).toBe(600_000);
    const out = patchHideSweepThrottle(id, code)!;
    expect(out).toContain("state === 'open' && (lastOpenSweepAt === 0 || Date.now() - lastOpenSweepAt >= 600000)");
    expect(out).toMatch(/lastOpenSweepAt = Date\.now\(\)\n\s+schedule\(\)/);
    // The load-time run stays: the unconditional schedule() after the listener is untouched.
    expect(out).toContain("  schedule()\n}\n\n/** One (owner, session id) pair");
  });

  it("fails the build when the pinned Desktop source moves, and ignores other files", () => {
    expect(() => patchHideSweepThrottle(id, "export const x = 1")).toThrow(/pinned Desktop source changed/);
    expect(patchHideSweepThrottle("/x/vendor/hermes/apps/desktop/src/plugins/hermes-bots/other.ts", "x")).toBeUndefined();
  });
});
