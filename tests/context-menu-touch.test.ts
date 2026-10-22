import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";
import { patchContextMenuTouchSource } from "../src/desktop/context-menu-touch";

const modulePath = fileURLToPath(new URL("../node_modules/@radix-ui/react-context-menu/dist/index.mjs", import.meta.url));
const source = readFileSync(modulePath, "utf8");

it("patches the installed Radix touch timer once without changing its default pointer handling", () => {
  const result = patchContextMenuTouchSource(modulePath, source)!;
  expect(result).toContain('event.pointerType === "touch" && androidNativeTextSelectionTarget(event.target)');
  expect(result.split("if (event.pointerType ===")).toHaveLength(2);
  expect(result).toContain('from "/src/desktop/mobile"');
  expect(result).toContain("window.setTimeout(() => handleOpen(event), 700)");
  expect(result.match(/event\.preventDefault\(\)/g)?.length).toBe(source.match(/event\.preventDefault\(\)/g)?.length);
});

it("fails closed when the pinned Radix timer implementation changes", () => {
  expect(() => patchContextMenuTouchSource(modulePath, source.replaceAll("whenTouchOrPen", "newTouchHandler"))).toThrow("touch timer changed");
  expect(() => patchContextMenuTouchSource(modulePath, source + source)).toThrow("touch timer changed");
});

it("leaves unrelated files untouched and accepts Windows module paths with Vite queries", () => {
  expect(patchContextMenuTouchSource("/elsewhere/index.mjs", source)).toBeUndefined();
  expect(patchContextMenuTouchSource(modulePath.replaceAll("/", "\\") + "?v=test", source)).toBeDefined();
});
