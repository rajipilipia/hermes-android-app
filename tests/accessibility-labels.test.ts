import { describe, expect, it } from "vitest";
import fs from "node:fs";
import { patchAccessibilityLabels } from "../src/desktop/accessibility-labels";
import { patchStatusbarSource } from "../src/desktop/statusbar-defaults";

const root = "vendor/hermes/apps/desktop/src/";
const read = (rel: string) => fs.readFileSync(root + rel, "utf8");
const idOf = (rel: string) => `/x/${root}${rel}`;

describe("names for unnamed Desktop controls (TalkBack)", () => {
  it("names the Thinking switch with Desktop's own string", () => {
    const rel = "app/shell/model-edit-submenu.tsx";
    const out = patchAccessibilityLabels(idOf(rel), read(rel))!;
    expect(out).toMatch(/<Switch\n\s+aria-label=\{copy\.thinking\}\n\s+checked=\{thinkingOn\}/);
    // The other switches keep their existing names untouched.
    expect(out.split("aria-label={copy.fast}").length).toBe(2);
  });

  it("names label-less status bar buttons from their tooltip text, and the status bar adapter still applies after it", () => {
    const rel = "app/shell/statusbar-controls.tsx";
    const out = patchAccessibilityLabels(idOf(rel), read(rel))!;
    expect(out.split("aria-label={item.label || item.detail ? undefined : item.title}").length - 1).toBe(2);
    // Same order as vite.config.ts: labels first, then the status bar data attributes.
    const both = patchStatusbarSource(idOf(rel), out)!;
    expect(both).toContain("data-android-statusbar-item={item.id}");
    expect(both.split("aria-label={item.label || item.detail ? undefined : item.title}").length - 1).toBe(2);
  });

  it("keeps the Settings labels", () => {
    const rel = "app/settings/index.tsx";
    const out = patchAccessibilityLabels(idOf(rel), read(rel))!;
    expect(out).toContain("aria-label={t.settings.exportConfig}");
    expect(out).toContain("aria-label={t.settings.resetToDefaults}");
  });

  it("fails the build when the pinned Desktop source moves, and ignores other files", () => {
    for (const rel of ["app/shell/model-edit-submenu.tsx", "app/shell/statusbar-controls.tsx", "app/settings/index.tsx"])
      expect(() => patchAccessibilityLabels(idOf(rel), "export const x = 1")).toThrow(/pinned Desktop source changed/);
    expect(patchAccessibilityLabels(idOf("app/shell/other.tsx"), "x")).toBeUndefined();
  });
});
