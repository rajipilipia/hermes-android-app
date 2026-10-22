// Build-only adapter; never alters source packages or native asset policy.
export function stripBundledFontQuery(css: string): string {
  return css.replace(
    /(codicon-[A-Za-z0-9_-]+\.ttf)\?[A-Fa-f0-9]+(?=[)'"\s])/g,
    "$1",
  );
}
