// Android build adapters for the pinned Desktop renderer. Source/vendor bytes stay
// unchanged. Exact-match guards require review if the upstream implementation moves.
function replaceOnce(code: string, before: string, after: string, label: string): string {
  if (code.split(before).length !== 2) throw new Error(`Android ${label} adapter: pinned Desktop source changed.`);
  return code.replace(before, after);
}

export function patchAndroidCompatibility(id: string, source: string): string | undefined {
  const file = id.replaceAll("\\", "/").split("?")[0];
  let code = source;
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/chat/composer/hooks/use-composer-metrics.ts")) {
    // The Android stylesheet gives narrow screens a separate input/control row.
    // Keep the model and reasoning entry points instead of removing them to fit
    // Desktop's one-line toolbar. Wide/Fold metrics remain byte-for-byte logic.
    code = replaceOnce(code, "compactPill: fit.compactPill || fit.tight,",
      'compactPill: document.documentElement.hasAttribute("data-android-compact") ? false : fit.compactPill || fit.tight,', "phone model label");
    code = replaceOnce(code, "foldVoice: fit.foldVoice || fit.minimal,",
      'foldVoice: document.documentElement.hasAttribute("data-android-compact") ? true : fit.foldVoice || fit.minimal,', "phone voice menu");
    return replaceOnce(code, "minimal: fit.minimal,",
      'minimal: document.documentElement.hasAttribute("data-android-compact") ? false : fit.minimal,', "phone controls");
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/chat/composer/floating-target.ts")) {
    code = replaceOnce(code, "if (!owner || selectionOutsideComposer() || inFloatingLayer(document.activeElement)) {",
      'if (document.documentElement.hasAttribute("data-android-touch") || !owner || selectionOutsideComposer() || inFloatingLayer(document.activeElement)) {', "native caret");
    return replaceOnce(code, "if (keyboardNavigation || keepsOwnFocus(target) || (pointerDownTarget && target.contains(pointerDownTarget))) {",
      'if (document.documentElement.hasAttribute("data-android-touch") || keyboardNavigation || keepsOwnFocus(target) || (pointerDownTarget && target.contains(pointerDownTarget))) {', "native focus");
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/chat/composer/reasoning-pill.tsx")) {
    // Wait for a completed touch tap. Radix normally opens on pointerdown, while
    // Android is still finishing its selection/keyboard gesture. Mouse and keys
    // continue through Radix unchanged. No custom text editing is introduced.
    return replaceOnce(code, 'data-testid="reasoning-pill"', `data-testid="reasoning-pill"
            onPointerDown={event => {
              if (event.pointerType === 'touch') event.preventDefault()
            }}
            onClick={event => {
              if (event.nativeEvent instanceof PointerEvent && event.nativeEvent.pointerType === 'touch') setMenuOpen(!open)
            }}`, "reasoning tap");
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/contrib/wiring.tsx")) {
    code = replaceOnce(code, "void openNewSessionTile('center', { listed: false })",
      "void openAndroidNewSessionTab(openNewSessionTile)", "new tab selection");
    return 'import { openAndroidNewSessionTab } from "/src/desktop/new-session-tab";\n' + code;
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/session/hooks/use-session-actions/index.ts")) {
    code = replaceOnce(code, "        listed?: boolean\n        profile?: string",
      '        listed?: boolean\n        androidSelection?: import("/src/desktop/new-session-tab").AndroidTabSelection\n        profile?: string', "new tab options");
    code = replaceOnce(code, "        // Same lease chain as createBackendSessionForSend: owner socket held",
      `        if (options?.androidSelection) Object.assign(params, options.androidSelection)

        // Same lease chain as createBackendSessionForSend: owner socket held`, "new tab request");
    return replaceOnce(code, "const runtimeInfo = applyRuntimeInfo(created.info, { foreground: false })",
      "const runtimeInfo = applyRuntimeInfo({ ...options?.androidSelection, ...created.info }, { foreground: false })", "new tab runtime");
  }
  return undefined;
}
