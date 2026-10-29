import { useEffect, useRef, useState, type CSSProperties } from "react";
import type { GuestElement } from "./webview-tag";

/** Display only: no guest-to-agent prompts, credentials, paths or network bridge. */
export function AndroidOfflineHtml({ srcDoc, title = "HTML preview", className, style, onHeight }: {
  srcDoc: string | null;
  title?: string;
  className?: string;
  style?: CSSProperties;
  onHeight?: (height: number) => void;
}) {
  const host = useRef<HTMLSpanElement>(null);
  const heightCallback = useRef(onHeight);
  heightCallback.current = onHeight;
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const container = host.current;
    if (!container || srcDoc === null) return;
    setError(""); setLoading(true);
    const guest = document.createElement("webview") as GuestElement;
    if (typeof guest.loadHTML !== "function") {
      setError("Offline HTML preview needs the updated Android app."); setLoading(false); return;
    }
    guest.style.cssText = "display:block;width:100%;height:100%;background:transparent";
    guest.setAttribute("aria-label", title);
    let active = true;
    const fail = (message: string) => { if (active) { setError(message); setLoading(false); } };
    const timer = setTimeout(() => fail("The preview did not finish loading. Retry to reopen it."), 20_000);
    guest.addEventListener("did-stop-loading", () => { if (active) { clearTimeout(timer); setLoading(false); } });
    guest.addEventListener("did-fail-load", () => fail("The offline preview could not be displayed."));
    guest.addEventListener("preview-paused", () => fail("Preview paused to limit memory use. Retry to reopen it."));
    guest.addEventListener("content-height", event => {
      const height = (event as Event & { height?: unknown }).height;
      if (active && typeof height === "number" && Number.isFinite(height))
        heightCallback.current?.(Math.max(120, Math.min(8192, height)));
    });
    container.appendChild(guest);
    void guest.loadHTML(srcDoc).catch(() => fail("Invalid, oversized or unavailable offline HTML preview."));
    return () => { active = false; clearTimeout(timer); guest.remove(); };
  }, [srcDoc, title, reload]);
  return <span data-android-inline-preview={onHeight ? "" : undefined} className={className} style={{ ...style, display: "block", position: "relative" }} role="group" aria-label={title}>
    <span ref={host} style={{ display: "block", width: "100%", height: "100%" }} />
    {/* Native placement waits for an uncovered guest. Loading must not block its
        own hit test; errors still cover the guest and keep Retry clickable. */}
    {(loading || error) && <span role={error ? "alert" : "status"} style={{ position: "absolute", inset: 0, overflow: "auto", padding: 12, background: "var(--background, white)", pointerEvents: error ? "auto" : "none" }}>
      {error || "Loading offline preview…"}
      {error && <button type="button" onClick={() => setReload(value => value + 1)} style={{ display: "block", marginTop: 8 }}>Retry</button>}
    </span>}
  </span>;
}
