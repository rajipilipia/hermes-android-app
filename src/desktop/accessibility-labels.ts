// Android build adapter: names icon-only Desktop buttons for TalkBack. Desktop shows the name
// only as a hover tooltip, which a phone never sees. No visual change; vendor bytes stay
// unchanged and exact-match guards fail the build if the Desktop source moves.
function replaceOnce(code: string, before: string, after: string, label: string): string {
  if (code.split(before).length !== 2) throw new Error(`Android ${label} adapter: pinned Desktop source changed.`);
  return code.replace(before, after);
}

export function patchAccessibilityLabels(id: string, source: string): string | undefined {
  const file = id.replaceAll("\\", "/").split("?")[0];
  let code = source;
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/settings/index.tsx")) {
    code = replaceOnce(code, `<Tip label={t.settings.exportConfig}>
        <OverlayIconButton onClick`, `<Tip label={t.settings.exportConfig}>
        <OverlayIconButton aria-label={t.settings.exportConfig} onClick`, "settings export label");
    code = replaceOnce(code, `<Tip label={t.settings.importConfig}>
        <OverlayIconButton
`, `<Tip label={t.settings.importConfig}>
        <OverlayIconButton
          aria-label={t.settings.importConfig}
`, "settings import label");
    return replaceOnce(code, `<Tip label={t.settings.resetToDefaults}>
        <OverlayIconButton
`, `<Tip label={t.settings.resetToDefaults}>
        <OverlayIconButton
          aria-label={t.settings.resetToDefaults}
`, "settings reset label");
  }
  // "Thinking" switch in the effort/reasoning menu: its row text is a sibling, not a label.
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/shell/model-edit-submenu.tsx"))
    return replaceOnce(code, `<Switch
            checked={thinkingOn}`, `<Switch
            aria-label={copy.thinking}
            checked={thinkingOn}`, "thinking switch label");
  // Status bar buttons with an icon and no text (the command center icon) get Desktop's own
  // tooltip text as their name. Items with a visible label keep it. These edits touch only the
  // tail of each <button> tag, so the data-android-statusbar-item adapter still matches its tag head.
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/shell/statusbar-controls.tsx")) {
    const name = "aria-label={item.label || item.detail ? undefined : item.title}";
    code = replaceOnce(code, `disabled={item.disabled} type="button">
          {content}`, `disabled={item.disabled} ${name} type="button">
          {content}`, "status bar menu button label");
    return replaceOnce(code, `        disabled={item.disabled}
        onClick={event => {`, `        disabled={item.disabled}
        ${name}
        onClick={event => {`, "status bar action button label");
  }
  return undefined;
}
