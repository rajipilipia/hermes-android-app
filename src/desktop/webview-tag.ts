// Desktop's in-app browser pane on Android (R1 stage 1, approved). Desktop's pane creates an
// Electron <webview> tag and drives it (loadURL, goBack, events such as did-navigate). Android
// WebView has no such tag, so the pane stayed blank. Here createElement("webview") still returns
// the plain element Desktop styles and places, plus the tag's methods; native draws a separate
// WebView over the element's rectangle (BrowserPane.java). The page never receives the guest's
// content, and the guest gets no bridge. Not offered: executeJavaScript, sendInputEvent, DevTools
// and the guest context menu (Desktop treats them as optional).

type Request = (value: string) => Promise<string>;
type Detail = Record<string, unknown> & { pageUrl?: string; pageTitle?: string; canGoBack?: boolean; canGoForward?: boolean };

export type GuestElement = HTMLElement & {
  loadURL(url: string): Promise<void>;
  getURL(): string;
  getTitle(): string;
  canGoBack(): boolean;
  canGoForward(): boolean;
  isLoading(): boolean;
  goBack(): void;
  goForward(): void;
  reload(): void;
  reloadIgnoringCache(): void;
  stop(): void;
};

const TICK_MS = 150;
/** Inset of the probe points used to find menus, sheets and dialogs drawn over the pane. Desktop
 *  keeps thin chrome on the pane's edges that covers nothing visible (the 8px resize handle, the
 *  status bar buttons' enlarged touch areas), so the corners are probed this far inside. */
const PROBE_INSET = 12;

export function installWebviewTag(win: Window & typeof globalThis, request: Request): () => void {
  const doc = win.document;
  const createElement = doc.createElement;
  const guests = new Map<number, Guest>();
  let next = 0;
  let timer: ReturnType<typeof setInterval> | undefined;

  const send = (payload: Record<string, unknown>) => request(JSON.stringify(payload));

  class Guest {
    readonly id = ++next;
    url = "";
    title = "";
    back = false;
    forward = false;
    loading = false;
    created = false;
    wanted = "";
    placed = "";
    attached = false;

    constructor(readonly el: HTMLElement) {}

    create() {
      if (this.created) return;
      this.created = true;
      this.placed = "";
      void send({ op: "create", guest: this.id }).then(() => {
        const first = this.wanted || this.el.getAttribute("src") || "";
        if (first) void this.load(first).catch(() => {});
      }, () => (this.created = false));
    }

    load(url: string): Promise<void> {
      // Desktop's empty Browser tab is about:blank: nothing to load natively.
      if (url === "about:blank") return Promise.resolve();
      this.wanted = url;
      this.loading = true;
      if (!this.created) return Promise.resolve();
      return send({ op: "load", guest: this.id, url }).then(() => undefined, (error: unknown) => {
        this.loading = false;
        throw error instanceof Error ? error : new Error(String(error));
      });
    }

    op(name: string) {
      if (this.created) void send({ op: name, guest: this.id }).catch(() => {});
    }

    event(type: string, detail: Detail) {
      if (type === "evicted") {
        // Native closed this guest to save memory (or its page crashed); reopen it when shown.
        this.created = false;
        this.placed = "";
        if (this.url) this.wanted = this.url;
        return;
      }
      if (typeof detail.pageUrl === "string" && detail.pageUrl) this.url = detail.pageUrl;
      if (typeof detail.pageTitle === "string") this.title = detail.pageTitle;
      if (typeof detail.canGoBack === "boolean") this.back = detail.canGoBack;
      if (typeof detail.canGoForward === "boolean") this.forward = detail.canGoForward;
      if (type === "did-start-loading") this.loading = true;
      if (type === "did-stop-loading" || type === "did-fail-load") this.loading = false;
      const event = new Event(type);
      for (const key of ["url", "title", "errorCode", "errorDescription", "validatedURL", "isMainFrame"])
        if (key in detail) Object.defineProperty(event, key, { value: detail[key] });
      if (type === "page-title-updated") Object.defineProperty(event, "title", { value: this.title });
      this.el.dispatchEvent(event);
    }

    /** Rectangle in CSS px and whether nothing covers it (menus, dialogs, drawers, error panes). */
    measure(): { x: number; y: number; w: number; h: number; visible: boolean } {
      const box = this.el.getBoundingClientRect();
      const x = Math.max(0, box.left), y = Math.max(0, box.top);
      const w = Math.max(0, Math.min(box.right, win.innerWidth) - x), h = Math.max(0, Math.min(box.bottom, win.innerHeight) - y);
      const rect = { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) };
      return { ...rect, visible: w >= 1 && h >= 1 && doc.visibilityState === "visible" && this.uncovered(x, y, w, h) };
    }

    private uncovered(x: number, y: number, w: number, h: number): boolean {
      for (let node: Element | null = this.el; node; node = node.parentElement) {
        if (node.hasAttribute("inert") || node.getAttribute("aria-hidden") === "true") return false;
        const style = win.getComputedStyle(node);
        if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
      }
      const inset = Math.min(PROBE_INSET, w / 2, h / 2);
      const points: Array<[number, number]> = [
        [x + w / 2, y + h / 2], [x + inset, y + inset], [x + w - inset, y + inset], [x + inset, y + h - inset], [x + w - inset, y + h - inset],
      ];
      return points.every(([px, py]) => {
        const hit = doc.elementFromPoint(px, py);
        return !!hit && (hit === this.el || this.el.contains(hit));
      });
    }
  }

  const tick = () => {
    for (const guest of [...guests.values()]) {
      if (!guest.el.isConnected) {
        // Desktop removes the tag when its pane closes (it never re-parents one).
        if (guest.attached) {
          guests.delete(guest.id);
          if (guest.created) void send({ op: "destroy", guest: guest.id }).catch(() => {});
        }
        continue;
      }
      guest.attached = true;
      const place = guest.measure();
      if (!guest.created) {
        if (!place.visible && guest.url) continue; // An evicted guest reopens only when shown.
        guest.create();
      }
      const key = JSON.stringify(place);
      if (key === guest.placed) continue;
      guest.placed = key;
      void send({ op: "bounds", guest: guest.id, ...place }).catch(() => (guest.placed = ""));
    }
    if (!guests.size && timer !== undefined) {
      clearInterval(timer);
      timer = undefined;
    }
  };
  const schedule = () => win.requestAnimationFrame(tick);

  const attach = (el: HTMLElement) => {
    const guest = new Guest(el);
    guests.set(guest.id, guest);
    const tag = el as GuestElement;
    Object.assign(tag, {
      loadURL: (url: string) => guest.load(String(url)),
      getURL: () => guest.url || guest.wanted || el.getAttribute("src") || "",
      getTitle: () => guest.title,
      canGoBack: () => guest.back,
      canGoForward: () => guest.forward,
      isLoading: () => guest.loading,
      goBack: () => guest.op("back"),
      goForward: () => guest.op("forward"),
      reload: () => guest.op("reload"),
      reloadIgnoringCache: () => guest.op("reload"),
      stop: () => guest.op("stop"),
    });
    if (timer === undefined) timer = setInterval(tick, TICK_MS);
    queueMicrotask(schedule);
  };

  doc.createElement = function (this: Document, tagName: string, options?: ElementCreationOptions) {
    const el = (createElement as (tagName: string, options?: ElementCreationOptions) => HTMLElement).call(this, tagName, options);
    if (String(tagName).toLowerCase() === "webview") attach(el);
    return el;
  } as typeof doc.createElement;
  win.__hermesGuestEvent = (guest, type, detail) => {
    let parsed: Detail = {};
    try {
      parsed = JSON.parse(detail) as Detail;
    } catch {
      return;
    }
    guests.get(guest)?.event(type, parsed);
  };
  win.addEventListener("resize", schedule);
  win.addEventListener("scroll", schedule, true);
  doc.addEventListener("visibilitychange", schedule);
  return () => {
    doc.createElement = createElement;
    delete win.__hermesGuestEvent;
    win.removeEventListener("resize", schedule);
    win.removeEventListener("scroll", schedule, true);
    doc.removeEventListener("visibilitychange", schedule);
    if (timer !== undefined) clearInterval(timer);
  };
}
