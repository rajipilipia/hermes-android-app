// Android build adapter: on a one-screen phone only the chat (Desktop's "workspace" pane) stays in the grid.
// Below Desktop's collapse breakpoint, panes that declare `collapsible` leave the grid and open as slide-overs,
// but Terminal and session tiles do not declare it. A layout saved on a wide screen (for example Terminal
// placed beside the chat) then keeps its saved weights, and the chat shrank to about 40px on the phone.
// Here every other pane reads as collapsible while html[data-android-compact] is set, so all of them use
// Desktop's own slide-over path. Wide screens (unfolded Fold) keep Desktop's grid. Vendor bytes stay unchanged;
// the exact-match guard fails the build if the Desktop source moves.
// Chat tabs stay in the grid: the workspace plus session and route tiles, the same set as Desktop's
// isMainSurface (store/layout.ts). A slide-over session tile is hidden from the tab strip, so the tab-strip
// "+" made a new chat on the PC that the phone never showed (seen 2026-10-28, 28 hidden tabs).
function replaceOnce(code: string, before: string, after: string, label: string): string {
  if (code.split(before).length !== 2) throw new Error(`Android ${label} adapter: pinned Desktop source changed.`);
  return code.replace(before, after);
}

export function patchPhonePanes(id: string, source: string): string | undefined {
  const file = id.replaceAll("\\", "/").split("?")[0];
  if (!file.endsWith("/vendor/hermes/apps/desktop/src/contrib/registry.ts")) return undefined;
  return replaceOnce(source, `            .filter(c => c.enabled !== false && (c.when ? c.when() : true))
            .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))`, `            .filter(c => c.enabled !== false && (c.when ? c.when() : true))
            .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
            // Android: on a one-screen phone every pane except the chat opens as a slide-over.
            .map(c =>
              area === 'panes' &&
              c.id !== 'workspace' &&
              !c.id.startsWith('session-tile:') &&
              !c.id.startsWith('route-tile:') &&
              typeof document !== 'undefined' &&
              document.documentElement.hasAttribute('data-android-compact') &&
              !(c.data as { collapsible?: boolean } | undefined)?.collapsible
                ? { ...c, data: { ...(c.data as object | undefined), collapsible: true } }
                : c
            )`, "phone panes");
}
