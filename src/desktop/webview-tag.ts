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
  loadHTML?: (html: string) => Promise<void>;
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
    loadEpoch = 0;
    created = false;
    wanted = "";
    html: string | null = null;
    evictedVisible = false;
    placed = "";
    attached = false;

    constructor(readonly el: HTMLElement) {}

    create() {
      if (this.created) return;
      this.created = true;
      this.placed = "";
      void send({ op: "create", guest: this.id }).then(() => {
        const first = this.wanted || this.el.getAttribute("src") || "";
        const pending = this.html !== null ? this.loadHTML(this.html) : first ? this.load(first) : undefined;
        const epoch = this.loadEpoch;
        // Before creation, the caller has already returned. Report a current
        // deferred failure through Desktop's existing recovery event instead.
        void pending?.catch((error: unknown) => {
          if (!this.el.isConnected || !this.created || epoch !== this.loadEpoch) return;
          this.event("did-fail-load", {
            errorCode: -2,
            errorDescription: error instanceof Error ? error.message : String(error),
            isMainFrame: true,
          });
        });
      }, () => (this.created = false));
    }

    load(url: string): Promise<void> {
      const epoch = ++this.loadEpoch;
      // Desktop's empty Browser tab is about:blank: nothing to load natively.
      if (url === "about:blank") return Promise.resolve();
      this.wanted = url;
      this.loading = true;
      if (!this.created) return Promise.resolve();
      return send({ op: "load", guest: this.id, url }).then(() => undefined, (error: unknown) => {
        if (epoch === this.loadEpoch) this.loading = false;
        throw error instanceof Error ? error : new Error(String(error));
      });
    }

    loadHTML(html: string): Promise<void> {
      ++this.loadEpoch;
      if (new TextEncoder().encode(html).length > 2 * 1024 * 1024)
        return Promise.reject(new Error("HTML preview exceeds the 2 MiB limit."));
      this.html = html;
      this.wanted = "";
      this.loading = true;
      if (!this.created) return Promise.resolve();
      return send({ op: "html", guest: this.id, html }).then(() => undefined);
    }

    op(name: string) {
      if (this.created) void send({ op: name, guest: this.id }).catch(() => {});
    }

    event(type: string, detail: Detail) {
      // Only native touch gestures can emit this event. Offline guest scripts
      // have no bridge and cannot drive another session's scroll container.
      if (type === "preview-scroll") {
        const dy = detail.dy;
        if (this.html !== null && typeof dy === "number" && Number.isFinite(dy) && Math.abs(dy) <= 500) {
          for (let node = this.el.parentElement; node; node = node.parentElement) {
            if (/(auto|scroll)/.test(win.getComputedStyle(node).overflowY) && node.scrollHeight > node.clientHeight) {
              node.scrollTop += dy;
              break;
            }
          }
        }
        return;
      }
      if (type === "evicted") {
        // Native closed this guest to save memory (or its page crashed); reopen it when shown.
        this.created = false;
        this.placed = "";
        if (this.html !== null) {
          this.evictedVisible = true;
          this.el.dispatchEvent(new Event("preview-paused"));
        } else if (this.url) this.wanted = this.url;
        return;
      }
      if (typeof detail.pageUrl === "string" && detail.pageUrl) this.url = detail.pageUrl;
      if (typeof detail.pageTitle === "string") this.title = detail.pageTitle;
      if (typeof detail.canGoBack === "boolean") this.back = detail.canGoBack;
      if (typeof detail.canGoForward === "boolean") this.forward = detail.canGoForward;
      if (type === "did-start-loading") this.loading = true;
      if (type === "did-stop-loading" || type === "did-fail-load") this.loading = false;
      const event = new Event(type);
      for (const key of ["url", "title", "errorCode", "errorDescription", "validatedURL", "isMainFrame", "height"])
        if (key in detail) Object.defineProperty(event, key, { value: detail[key] });
      if (type === "page-title-updated") Object.defineProperty(event, "title", { value: this.title });
      this.el.dispatchEvent(event);
    }

    /** Rectangle in CSS px and whether nothing covers it (menus, dialogs, drawers, error panes). */
    measure(): { x: number; y: number; w: number; h: number; visible: boolean; contentW?: number; contentH?: number; offsetX?: number; offsetY?: number } {
      const box = this.el.getBoundingClientRect();
      let x = Math.max(0, box.left), y = Math.max(0, box.top);
      let right = Math.min(box.right, win.innerWidth), bottom = Math.min(box.bottom, win.innerHeight);
      if (this.html !== null) {
        // The transcript, not the whole app viewport, is the clipping window.
        // Preserve the guest's full layout size as its visible slice moves.
        for (let node = this.el.parentElement; node; node = node.parentElement) {
          const style = win.getComputedStyle(node), r = node.getBoundingClientRect();
          if (/(hidden|clip|auto|scroll)/.test(style.overflowX)) { x = Math.max(x, r.left); right = Math.min(right, r.right); }
          if (/(hidden|clip|auto|scroll)/.test(style.overflowY)) { y = Math.max(y, r.top); bottom = Math.min(bottom, r.bottom); }
          // Reuse Desktop's existing sticky-prompt exclusion; native overlays
          // do not inherit their DOM ancestor's CSS clip-path.
          if (node.hasAttribute("data-sticky-prompt-clip")) {
            const inset = Number.parseFloat(style.getPropertyValue("--sticky-prompt-clip"));
            if (Number.isFinite(inset) && inset > 0) y = Math.max(y, r.top + Math.min(r.height, inset));
          }
        }
        // Keep the native slice above this chat's composer. All other overlays
        // still go through uncovered(), including menus and blocking dialogs.
        if (this.el.closest('[data-slot="aui_thread-viewport"]')) {
          const dock = this.el.closest('[data-chat-surface]')?.querySelector('[data-slot="composer-dock"]');
          const r = dock?.getBoundingClientRect();
          if (r && r.width > 0 && r.height > 0 && r.left < right && r.right > x && r.top < bottom && r.bottom > y)
            bottom = Math.min(bottom, r.top);
        }
      }
      const w = Math.max(0, right - x), h = Math.max(0, bottom - y);
      const rect = { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) };
      return {
        ...rect,
        ...(this.html !== null ? { contentW: Math.round(box.width), contentH: Math.round(box.height), offsetX: Math.max(0, Math.round(x - box.left)), offsetY: Math.max(0, Math.round(y - box.top)) } : {}),
        visible: w >= 1 && h >= 1 && doc.visibilityState === "visible" && this.uncovered(x, y, w, h),
      };
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
      if (guest.evictedVisible) {
        if (!place.visible) guest.evictedVisible = false;
        else continue;
      }
      if (!guest.created) {
        if (!place.visible && (guest.url || guest.html !== null)) continue;
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
      loadHTML: (html: string) => guest.loadHTML(String(html)),
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
