import { describe, expect, it } from "vitest";
import fs from "node:fs";
import { patchNarrowRightPane } from "../src/desktop/narrow-right-pane";

const rel = "store/layout.ts";
const id = `/x/vendor/hermes/apps/desktop/src/${rel}`;
const code = fs.readFileSync(`vendor/hermes/apps/desktop/src/${rel}`, "utf8");

describe("right-side button on a phone screen", () => {
  it("turns the Files open flag on before the narrow slide-over event, and only for Files", () => {
    const out = patchNarrowRightPane(id, code)!;
    expect(out).toMatch(/if \(id === FILE_BROWSER_PANE_ID && mode !== 'close'\) \{\n[^\n]*\n\s+\$fileBrowserOpen\.set\(true\)\n\s+setTimeout\(/);
    // Every other pane keeps Desktop's direct event.
    expect(out.split("window.dispatchEvent(new CustomEvent(PANE_TOGGLE_REVEAL_EVENT").length - 1).toBe(2);
  });

  it("fails the build when the pinned Desktop source moves", () => {
    expect(() => patchNarrowRightPane(id, "export const x = 1")).toThrow(/pinned Desktop source changed/);
  });

  it("leaves every other file alone", () => {
    expect(patchNarrowRightPane("/x/vendor/hermes/apps/desktop/src/store/other.ts", "x")).toBeUndefined();
  });
});
