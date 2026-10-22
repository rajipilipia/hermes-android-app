import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { patchStatusbarSource } from "../src/desktop/statusbar-defaults";
const base = "vendor/hermes/apps/desktop/src/";
const css = readFileSync("src/desktop/single-screen.css", "utf8");
it("tags actual statusbar item roots and clusters without editing vendor", () => {
  const path = base + "app/shell/statusbar-controls.tsx";
  const result = patchStatusbarSource("/" + path, readFileSync(path, "utf8"))!;
  expect(result.match(/data-android-statusbar-item=\{item.id\}/g)).toHaveLength(4);
  for (const side of ["left", "right"]) expect(result).toContain(`data-android-statusbar-cluster="${side}"`);
  expect(() => patchStatusbarSource("/" + path, "upstream changed")).toThrow(/changed upstream/);
});
it("reserves real first-eight-character width, not a fixed ch approximation", () => {
  const path = base + "app/chat/sidebar/profile-dropdown-switcher.tsx";
  const result = patchStatusbarSource("/" + path, readFileSync(path, "utf8"))!;
  expect(result).toContain("data-android-profile-prefix={Array.from(triggerLabel).slice(0, 8).join('') + (Array.from(triggerLabel).length > 8 ? '…' : '')}");
  expect(css).toContain("content: attr(data-android-profile-prefix)");
  expect(css).toContain("min-width: min-content");
});
it("keeps mandatory controls and shrinks project text before backend text only on compact Android", () => {
  for (const marker of ['data-android-statusbar-cluster="right"', 'data-android-statusbar-item="workspace-cwd"', 'data-android-statusbar-item="gateway-health"', 'data-android-profile-prefix']) {
    const rule = css.split("}").find(block => block.includes(marker));
    expect(rule).toContain("html[data-android-compact]");
  }
  expect(css).toMatch(/workspace-cwd[^}]*flex:\s*0 1000 auto/);
  expect(css).toMatch(/gateway-health[^}]*flex:\s*0 1 auto/);
  expect(css).toMatch(/footer\[data-slot="statusbar"\][^{]*\{[^}]*overflow:\s*hidden/);
  expect(css).toMatch(/statusbar"\] button::after[^}]*inset:\s*0/);
});
