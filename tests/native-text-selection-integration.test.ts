import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = fileURLToPath(new URL("../", import.meta.url));
type Sample = { kind: string; menuOpened: boolean; pointerDefaultAllowed: boolean; contextDefaultAllowed: boolean };
function probe(unpatched = false): { transformed: boolean; results: Sample[] } {
  const result = execFileSync(process.execPath, [
    "--experimental-strip-types", path.join(root, "tests/fixtures/native-text-selection.mjs"),
    ...(unpatched ? ["--unpatched"] : []),
  ], { cwd: root, encoding: "utf8", timeout: 45_000 });
  return JSON.parse(result.trim());
}

describe("real Radix touch timer with Android text selection", () => {
  it("keeps native text gestures and preserves link, row, reaction and mouse menus", () => {
    const { transformed, results } = probe();
    expect(transformed).toBe(true);
    for (const kind of ["composer", "input", "text", "composer-pointer"]) {
      expect(results.find(row => row.kind === kind), kind).toMatchObject({
        menuOpened: false, pointerDefaultAllowed: true, contextDefaultAllowed: true,
      });
    }
    for (const kind of ["link", "row", "reaction", "mouse", "link-pointer"]) {
      expect(results.find(row => row.kind === kind)?.menuOpened, kind).toBe(true);
    }
  }, 50_000);

  it("detects the original dependency timer bypass without the build transform", () => {
    const { transformed, results } = probe(true);
    expect(transformed).toBe(false);
    expect(results.find(row => row.kind === "composer")).toMatchObject({
      menuOpened: true, pointerDefaultAllowed: true, contextDefaultAllowed: true,
    });
  }, 50_000);
});
