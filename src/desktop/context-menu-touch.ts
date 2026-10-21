// Android-only compatibility patch for the pinned Radix ESM module. Vendor and
// node_modules stay untouched. Radix starts a 700 ms pointer timer independently
// of contextmenu, so blocking only contextmenu cannot preserve native selection.
const MODULE = "/node_modules/@radix-ui/react-context-menu/dist/index.mjs";
const TOUCH_START = "whenTouchOrPen((event) => {\n              clearLongPress();";

export function patchContextMenuTouchSource(id: string, code: string): string | undefined {
  if (!id.replaceAll("\\", "/").split("?")[0].endsWith(MODULE)) return undefined;
  if (code.split(TOUCH_START).length !== 2)
    throw new Error("Radix context-menu touch timer changed; review Android text selection.");
  return 'import { nativeTextSelectionTarget as androidNativeTextSelectionTarget } from "/src/desktop/mobile";\n'
    + code.replace(TOUCH_START, `${TOUCH_START}
              if (event.pointerType === "touch" && androidNativeTextSelectionTarget(event.target)) return;`);
}
