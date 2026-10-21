// Android layout defaults for the pinned Hermes Desktop status bar (2026-10-18).
// "Version & updates" and "Backend version" start hidden and can be turned on from the
// status bar menu. Upstream locks them on, so the vendored source is patched at build
// time (vendor/ stays untouched, like the other vite transforms). A changed upstream
// layout fails the build loudly instead of silently dropping the default.
const PREFS = "/vendor/hermes/apps/desktop/src/store/statusbar-prefs.ts";
const ITEMS = "/vendor/hermes/apps/desktop/src/app/shell/hooks/use-statusbar-items.tsx";
const HIDDEN_LIST = /(export const STATUSBAR_HIDDEN_BY_DEFAULT: readonly string\[\] = \[)/;
const LOCKED_VERSION = /lockedVisible: true,(\s+onSelect: \(\) => openUpdateOverlayFor\(target\),)/;

export function patchStatusbarSource(id: string, code: string): string | undefined {
  const file = id.replaceAll("\\", "/").split("?")[0];
  if (file.endsWith(PREFS)) {
    if (!HIDDEN_LIST.test(code)) throw new Error("Status bar default list changed upstream.");
    return code.replace(HIDDEN_LIST, "$1\n  'version-backend',\n  'version-client',");
  }
  if (file.endsWith(ITEMS)) {
    if (!LOCKED_VERSION.test(code)) throw new Error("Status bar version item changed upstream.");
    return code.replace(LOCKED_VERSION, "lockedVisible: false,$1");
  }
  return undefined;
}
