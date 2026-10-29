// Android build adapter: a session tab ("+" tab) keeps its chat mounted when its title changes.
// Desktop's pane mirror registers the tab again when the title changes, with a new arrow
// `render: () => cfg.render(key)`. The tree draws a pane with `createElement(render)`, so React sees a
// new component type and rebuilds the whole chat. The first message in a "+" tab sets its title, so
// the rebuild ended a voice call at its first task (close_trigger=unmount, seen 2026-10-28 on the phone;
// the PC Desktop has the same code). Here each tab key keeps one render function for its life.
// Vendor bytes stay unchanged; the exact-match guard fails the build if the Desktop source moves.
function replaceOnce(code: string, before: string, after: string, label: string): string {
  if (code.split(before).length !== 2) throw new Error(`Android ${label} adapter: pinned Desktop source changed.`);
  return code.replace(before, after);
}

export function patchStableTileRender(id: string, source: string): string | undefined {
  const file = id.replaceAll("\\", "/").split("?")[0];
  if (!file.endsWith("/vendor/hermes/apps/desktop/src/app/chat/pane-mirror.ts")) return undefined;
  let code = replaceOnce(source, `  const paneId = (key: string) => \`\${cfg.prefix}:\${key}\`
`, `  const paneId = (key: string) => \`\${cfg.prefix}:\${key}\`

  // Android: one render function per tab key, so a title refresh does not remount the tab body.
  const renders = new Map<string, () => ReactNode>()

  const renderFor = (key: string) => {
    let render = renders.get(key)

    if (!render) {
      render = () => cfg.render(key)
      renders.set(key, render)
    }

    return render
  }
`, "stable tile render");
  code = replaceOnce(code, `    registered.delete(key)
    parked.delete(key)`, `    registered.delete(key)
    renders.delete(key)
    parked.delete(key)`, "stable tile render dispose");
  return replaceOnce(code, `        render: () => cfg.render(key)
      })`, `        render: renderFor(key)
      })`, "stable tile render register");
}
