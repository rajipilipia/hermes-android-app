// A phone's small display remains a phone when rotated or when the IME resizes
// the WebView. An unfolded Fold is not classified from its keyboard-shortened
// height. This is transient UI state only; no preference/layout tree is saved.
export function isSingleScreen(width: number, screenWidth: number, screenHeight: number): boolean {
  return width < 640 || (screenWidth > 0 && screenHeight > 0 && Math.min(screenWidth, screenHeight) < 640);
}
export function installSingleScreenLayout(win: Window & typeof globalThis = window): () => void {
  const html = win.document.documentElement;
  const update = () => {
    const compact = isSingleScreen(win.innerWidth, win.screen.width, win.screen.height);
    html.toggleAttribute("data-android-compact", compact);
    html.style.setProperty("--android-visible-height", `${win.visualViewport?.height ?? win.innerHeight}px`);
  };
  update();
  win.addEventListener("resize", update);
  win.visualViewport?.addEventListener("resize", update);
  return () => {
    win.removeEventListener("resize", update);
    win.visualViewport?.removeEventListener("resize", update);
    html.removeAttribute("data-android-compact");
    html.style.removeProperty("--android-visible-height");
  };
}
