// Android build adapter: makes Desktop's right-side button (Files) open on a phone screen.
// Below Desktop's collapse breakpoint every open/toggle only fires the slide-over event, but the
// Files pane is hidden from the slide-over list while its "file-browser open" flag is off, and the
// narrow path never turns that flag on. So the tap did nothing. Here the narrow path turns the
// flag on first, then fires the event on the next task, after React has put Files back in the
// list. Wide screens (unfolded Fold) keep Desktop's path. A project folder is still required:
// without one Desktop hides Files by design. Vendor bytes stay unchanged; the exact-match guard
// fails the build if the Desktop source moves.
function replaceOnce(code: string, before: string, after: string, label: string): string {
  if (code.split(before).length !== 2) throw new Error(`Android ${label} adapter: pinned Desktop source changed.`);
  return code.replace(before, after);
}

export function patchNarrowRightPane(id: string, source: string): string | undefined {
  const file = id.replaceAll("\\", "/").split("?")[0];
  if (!file.endsWith("/vendor/hermes/apps/desktop/src/store/layout.ts")) return undefined;
  return replaceOnce(source, `  window.dispatchEvent(new CustomEvent(PANE_TOGGLE_REVEAL_EVENT, { detail: { id, mode } }))

  return true
}`, `  if (id === FILE_BROWSER_PANE_ID && mode !== 'close') {
    // Android: Files is hidden from the slide-over list until its open flag is on.
    $fileBrowserOpen.set(true)
    setTimeout(() => window.dispatchEvent(new CustomEvent(PANE_TOGGLE_REVEAL_EVENT, { detail: { id, mode } })), 0)

    return true
  }

  window.dispatchEvent(new CustomEvent(PANE_TOGGLE_REVEAL_EVENT, { detail: { id, mode } }))

  return true
}`, "narrow files reveal");
}
