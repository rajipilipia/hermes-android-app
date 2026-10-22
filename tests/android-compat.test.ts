import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { patchAndroidCompatibility } from "../src/desktop/android-compat";

const modules = [
  "app/chat/composer/floating-target.ts",
  "app/chat/composer/reasoning-pill.tsx",
  "app/chat/composer/hooks/use-composer-metrics.ts",
  "app/contrib/wiring.tsx",
  "app/session/hooks/use-session-actions/index.ts",
];
for (const module of modules) {
  it(`adapts pinned ${module} without writing upstream and rejects duplicate source`, () => {
    const path = new URL(`../vendor/hermes/apps/desktop/src/${module}`, import.meta.url);
    const source = readFileSync(path, "utf8");
    const result = patchAndroidCompatibility(path.pathname, source);
    expect(result).toBeDefined();
    expect(result).not.toBe(source);
    expect(readFileSync(path, "utf8")).toBe(source);
    expect(() => patchAndroidCompatibility(path.pathname, source + source)).toThrow("pinned Desktop source changed");
  });
}
it("does not transform unrelated code", () => {
  expect(patchAndroidCompatibility("/other/index.ts", "untouched")).toBeUndefined();
});
