import { describe, expect, it } from "vitest";
import fs from "node:fs";
import { patchPhonePanes } from "../src/desktop/phone-panes";

const rel = "contrib/registry.ts";
const id = `/x/vendor/hermes/apps/desktop/src/${rel}`;
const code = fs.readFileSync(`vendor/hermes/apps/desktop/src/${rel}`, "utf8");

describe("panes on a one-screen phone", () => {
  it("marks every pane except the chat collapsible, only on the compact phone", () => {
    const out = patchPhonePanes(id, code)!;
    expect(out).toMatch(/\.sort\(\(a, b\) => \(a\.order \?\? 0\) - \(b\.order \?\? 0\)\)\n[^\n]*\n\s+\.map\(c =>/);
    expect(out).toContain("area === 'panes' &&");
    expect(out).toContain("c.id !== 'workspace' &&");
    expect(out).toContain("document.documentElement.hasAttribute('data-android-compact')");
    expect(out).toContain("{ ...c, data: { ...(c.data as object | undefined), collapsible: true } }");
  });

  it("keeps chat tabs (session and route tiles) in the grid, like Desktop's main surfaces", () => {
    const out = patchPhonePanes(id, code)!;
    expect(out).toContain("!c.id.startsWith('session-tile:') &&");
    expect(out).toContain("!c.id.startsWith('route-tile:') &&");
    // Same set as Desktop's own rule; fail here if the pinned Desktop changes it.
    const layout = fs.readFileSync("vendor/hermes/apps/desktop/src/store/layout.ts", "utf8");
    expect(layout).toContain(
      "return paneId === 'workspace' || paneId.startsWith('session-tile:') || paneId.startsWith('route-tile:')"
    );
  });

  it("fails the build when the pinned Desktop source moves", () => {
    expect(() => patchPhonePanes(id, "export const x = 1")).toThrow(/pinned Desktop source changed/);
  });

  it("leaves every other file alone", () => {
    expect(patchPhonePanes("/x/vendor/hermes/apps/desktop/src/contrib/other.ts", "x")).toBeUndefined();
  });
});
