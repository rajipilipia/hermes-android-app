// Android layout defaults for the pinned Hermes Desktop status bar (2026-10-18).
// "Version & updates" and "Backend version" start hidden and can be turned on from the
// status bar menu. Upstream locks them on, so the vendored source is patched at build
// time (vendor/ stays untouched, like the other vite transforms). A changed upstream
// layout fails the build loudly instead of silently dropping the default.
const PREFS = "/vendor/hermes/apps/desktop/src/store/statusbar-prefs.ts";
const ITEMS = "/vendor/hermes/apps/desktop/src/app/shell/hooks/use-statusbar-items.tsx";
const PICKER = "/vendor/hermes/apps/desktop/src/app/chat/sidebar/profile-dropdown-switcher.tsx";
const CONTROLS = "/vendor/hermes/apps/desktop/src/app/shell/statusbar-controls.tsx";
const HIDDEN_LIST = /(export const STATUSBAR_HIDDEN_BY_DEFAULT: readonly string\[\] = \[)/;
const LOCKED_VERSION = /lockedVisible: true,(\s+onSelect: \(\) => openUpdateOverlayFor\(target\),)/;

function replacePinned(code: string, before: string, after: string): string {
  if (code.split(before).length !== 2) throw new Error("Status bar profile adapter changed upstream.");
  return code.replace(before, after);
}

export function patchStatusbarSource(id: string, code: string): string | undefined {
  const file = id.replaceAll("\\", "/").split("?")[0];
  if (file.endsWith(CONTROLS)) {
    for (const side of ["left", "right"] as const) {
      const items = side === "left" ? "leftItems" : "items";
      code = replacePinned(code,
        `<div className="flex min-w-0 items-stretch gap-0.5 overflow-x-clip">\n            {${items}`,
        `<div data-android-statusbar-cluster="${side}" className="flex min-w-0 items-stretch gap-0.5 overflow-x-clip">\n            {${items}`);
    }
    code = replacePinned(code, "<button className={cn(STATUSBAR_ACTION_CLASS, item.className)}",
      "<button data-android-statusbar-item={item.id} className={cn(STATUSBAR_ACTION_CLASS, item.className)}");
    code = replacePinned(code, "<a className={cn(STATUSBAR_ACTION_CLASS, item.className)}",
      "<a data-android-statusbar-item={item.id} className={cn(STATUSBAR_ACTION_CLASS, item.className)}");
    code = replacePinned(code, "<div\n          className={cn(",
      "<div data-android-statusbar-item={item.id}\n          className={cn(");
    return replacePinned(code, "<button\n        className={cn(STATUSBAR_ACTION_CLASS, item.className)}",
      "<button data-android-statusbar-item={item.id}\n        className={cn(STATUSBAR_ACTION_CLASS, item.className)}");
  }
  if (file.endsWith(PREFS)) {
    if (!HIDDEN_LIST.test(code)) throw new Error("Status bar default list changed upstream.");
    return code.replace(HIDDEN_LIST, "$1\n  'version-backend',\n  'version-client',");
  }
  if (file.endsWith(ITEMS)) {
    if (!LOCKED_VERSION.test(code)) throw new Error("Status bar version item changed upstream.");
    code = code.replace(LOCKED_VERSION, "lockedVisible: false,$1");
    // Match single-screen.ts, including rotated phones; subscribe so unfolding restores Desktop rules.
    code = replacePinned(code, "  const profileRailVisible = useStore($profileRailVisible)",
      "  const profileRailVisible = useStore($profileRailVisible)\n" +
      "  const compactProfilePicker = useMediaQuery('(width < 640px), (device-width < 640px), (device-height < 640px)')");
    code = replacePinned(code, "hidden: !sessionsShowing || profileRailVisible,",
      "hidden: !compactProfilePicker && (!sessionsShowing || profileRailVisible),");
    // Both selectors share profile state. Only the mounted rail or the dropdown handles the create hotkey.
    code = replacePinned(code, "render: () => <ProfileSwitcher compact />",
      "render: () => <ProfileSwitcher compact listenForCreateRequests={!sessionsShowing || !profileRailVisible} />");
    code = replacePinned(code, "      profileRailVisible,", "      compactProfilePicker,\n      profileRailVisible,");
    return "import { useMediaQuery } from '@/hooks/use-media-query'\n" + code;
  }
  if (file.endsWith(PICKER)) {
    // Include the ellipsis so it cannot consume the eighth visible character.
    // The extra inline span is neutral outside the compact-only CSS.
    code = replacePinned(code, '<span className="truncate">{triggerLabel}</span>',
      '<span className="truncate" data-android-profile-prefix={Array.from(triggerLabel).slice(0, 8).join(\'\') + (Array.from(triggerLabel).length > 8 ? \'…\' : \'\')}><span>{triggerLabel}</span></span>');
    code = replacePinned(code,
      "export function ProfileSwitcher({ compact = false }: { compact?: boolean }) {",
      "export function ProfileSwitcher({ compact = false, listenForCreateRequests = true }: { compact?: boolean; listenForCreateRequests?: boolean }) {");
    code = replacePinned(code, "lastCreateRef.current = createRequest\n    setCreateOpen(true)",
      "lastCreateRef.current = createRequest\n    if (listenForCreateRequests) setCreateOpen(true)");
    return replacePinned(code, "[createRequest]", "[createRequest, listenForCreateRequests]");
  }
  return undefined;
}
