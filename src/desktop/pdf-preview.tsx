import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { pdfBytes } from "./pdf-data";

/** Canvas rendering avoids Android WebView's unsupported/blocked PDF iframe. */
export function AndroidPdfPreview({ dataUrl, title }: { dataUrl: string; title: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const holder = useRef<HTMLDivElement>(null);
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [width, setWidth] = useState(320);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  useEffect(() => {
    const element = holder.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setWidth(Math.max(120, element.clientWidth - 16)));
    observer.observe(element);
    setWidth(Math.max(120, element.clientWidth - 16));
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let active = true;
    let task: { destroy(): Promise<void> } | undefined;
    setDocument(null); setError(""); setBusy(true); setPage(1);
    void import("pdfjs-dist").then(pdf => {
      if (!active) return;
      pdf.GlobalWorkerOptions.workerSrc = workerUrl;
      const loading = pdf.getDocument({ data: pdfBytes(dataUrl), enableXfa: false, useWasm: false });
      task = loading;
      return loading.promise.then(value => { if (active) setDocument(value); });
    }).catch(() => { if (active) { setError("This PDF could not be decoded. Download it to view it in another app."); setBusy(false); } });
    return () => { active = false; void task?.destroy().catch(() => {}); };
  }, [dataUrl]);
  useEffect(() => {
    const element = canvas.current;
    if (!document || !element) return;
    let active = true;
    let cancel: (() => void) | undefined;
    setBusy(true); setError("");
    void document.getPage(page).then(value => {
      if (!active) return;
      const base = value.getViewport({ scale: 1 });
      const scale = Math.min(width / base.width * Math.min(devicePixelRatio || 1, 2), Math.sqrt(4_000_000 / (base.width * base.height)));
      const viewport = value.getViewport({ scale });
      element.width = Math.ceil(viewport.width); element.height = Math.ceil(viewport.height);
      const render = value.render({ canvas: element, viewport });
      cancel = () => render.cancel();
      return render.promise;
    }).then(() => { if (active) setBusy(false); }).catch(() => { if (active) { setError("This PDF page could not be rendered."); setBusy(false); } });
    return () => { active = false; cancel?.(); };
  }, [document, page, width]);
  return <div ref={holder} className="flex size-full min-w-0 flex-col overflow-hidden" aria-label={title}>
    <div className="flex shrink-0 items-center justify-center gap-3 p-2">
      <button type="button" disabled={!document || page <= 1} onClick={() => setPage(value => value - 1)}>Previous</button>
      <span>{document ? `${page} / ${document.numPages}` : "PDF"}</span>
      <button type="button" disabled={!document || page >= document.numPages} onClick={() => setPage(value => value + 1)}>Next</button>
    </div>
    <div className="min-h-0 flex-1 overflow-auto p-2">
      {busy && !error && <p role="status">Loading PDF…</p>}
      {error && <p role="alert">{error}</p>}
      <canvas ref={canvas} role="img" aria-label={`${title}, page ${page}`} style={{ display: error ? "none" : "block", width: "100%", height: "auto", background: "white" }} />
    </div>
  </div>;
}
