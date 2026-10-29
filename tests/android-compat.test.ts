import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { patchAndroidCompatibility } from "../src/desktop/android-compat";

const modules = [
  "lib/local-preview.ts",
  "lib/desktop-fs.ts",
  "components/assistant-ui/inline-preview-directive.tsx",
  "app/chat/right-rail/preview-pane.tsx",
  "app/chat/right-rail/preview-file.tsx",
  "app/chat/right-rail/preview-artifact.tsx",
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

it("preserves offline scripts for the isolated Android full-file preview, not the upstream static iframe", () => {
  const path = new URL("../vendor/hermes/apps/desktop/src/app/chat/right-rail/preview-pane.tsx", import.meta.url);
  const adapted = patchAndroidCompatibility(path.pathname, readFileSync(path, "utf8"));
  expect(adapted).toContain("androidRemoteHtmlPreviewDocument(target.dataUrl!)");
  expect(adapted).not.toContain("isRemoteHtml ? remoteHtmlPreviewDocument(");
  expect(adapted).toContain("Invalid or oversized offline HTML preview.");
});

it("uses a bounded tall inline frame and the native Android preview action", () => {
  const inline = "vendor/hermes/apps/desktop/src/components/assistant-ui/inline-preview-directive.tsx";
  expect(patchAndroidCompatibility(new URL(`../${inline}`, import.meta.url).pathname, readFileSync(inline, "utf8"))).toContain("const MAX_HEIGHT = 8192");
  const local = "vendor/hermes/apps/desktop/src/lib/local-preview.ts";
  const adapted = patchAndroidCompatibility(new URL(`../${local}`, import.meta.url).pathname, readFileSync(local, "utf8"));
  expect(adapted).toContain("return openAndroidPreview(target)");
  expect(adapted).not.toContain("Desktop preview browser bridge is unavailable");
});
