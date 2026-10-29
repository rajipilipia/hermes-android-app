// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { installWebviewTag, type GuestElement } from "../src/desktop/webview-tag";

const win = window as Window & typeof globalThis;
let sent: Array<Record<string, unknown>>;
let refuse: ((payload: Record<string, unknown>) => string | undefined | Promise<string | undefined>) | undefined;
let uninstall: () => void;
let cover: Element | null;

beforeEach(() => {
  vi.useFakeTimers();
  sent = [];
  refuse = undefined;
  cover = null;
  document.body.innerHTML = '<div id="pane"></div><div id="menu"></div>';
  uninstall = installWebviewTag(win, async (value) => {
    const payload = JSON.parse(value) as Record<string, unknown>;
    sent.push(payload);
    const error = await refuse?.(payload);
    if (error) throw new Error(error);
    return "";
  });
  Object.defineProperty(win, "innerWidth", { value: 412, configurable: true });
  Object.defineProperty(win, "innerHeight", { value: 915, configurable: true });
  document.elementFromPoint = (() => cover) as typeof document.elementFromPoint;
});
afterEach(() => {
  uninstall();
  vi.useRealTimers();
});

const guestTag = (src = "https://example.org/") => {
  const tag = document.createElement("webview") as GuestElement;
  tag.setAttribute("src", src);
  tag.getBoundingClientRect = () => ({ left: 0, top: 96, right: 412, bottom: 800, width: 412, height: 704, x: 0, y: 96, toJSON() {} }) as DOMRect;
  cover = tag;
  document.getElementById("pane")!.appendChild(tag);
  return tag;
};
const settle = async (ms = 150) => {
  await vi.advanceTimersByTimeAsync(ms);
};
const ops = () => sent.map((p) => p.op);

it("gives Desktop's <webview> tag its methods; other elements are untouched; uninstall restores createElement", () => {
  const tag = document.createElement("webview") as GuestElement;
  for (const name of ["loadURL", "getURL", "getTitle", "canGoBack", "canGoForward", "goBack", "goForward", "reload", "reloadIgnoringCache", "stop", "isLoading"])
    expect(typeof (tag as unknown as Record<string, unknown>)[name]).toBe("function");
  expect("loadURL" in document.createElement("div")).toBe(false);
  expect(tag.canGoBack()).toBe(false);
  uninstall();
  expect("loadURL" in document.createElement("webview")).toBe(false);
  uninstall = () => {};
});

it("creates the native guest when attached, loads src, and places it over the tag's rectangle", async () => {
  guestTag();
  await settle();
  expect(sent).toEqual([
    { op: "create", guest: 1 },
    { op: "bounds", guest: 1, x: 0, y: 96, w: 412, h: 704, visible: true },
    // Loads once native has created the guest.
    { op: "load", guest: 1, url: "https://example.org/" },
  ]);
  await settle(600);
  expect(ops()).toEqual(["create", "bounds", "load"]); // Unchanged rectangle: no repeat.
});

it("hides the native guest while a menu, sheet or inert ancestor covers the pane", async () => {
  const tag = guestTag();
  await settle();
  cover = document.getElementById("menu");
  await settle();
  expect(sent.at(-1)).toMatchObject({ op: "bounds", visible: false });
  cover = tag;
  await settle();
  expect(sent.at(-1)).toMatchObject({ op: "bounds", visible: true });
  document.getElementById("pane")!.setAttribute("inert", "");
  await settle();
  expect(sent.at(-1)).toMatchObject({ op: "bounds", visible: false });
});

it("native events update the synchronous getters before Desktop's listeners run", async () => {
  const tag = guestTag();
  await settle();
  const seen: Array<[string, unknown, boolean, string]> = [];
  for (const type of ["did-navigate", "page-title-updated", "did-fail-load", "did-stop-loading"])
    tag.addEventListener(type, (event) => seen.push([type, (event as Event & { url?: string; errorCode?: number }).url ?? (event as Event & { errorCode?: number }).errorCode, tag.canGoBack(), tag.getTitle()]));
  win.__hermesGuestEvent!(1, "did-navigate", JSON.stringify({ url: "https://example.org/next", pageUrl: "https://example.org/next", pageTitle: "", canGoBack: true, canGoForward: false }));
  win.__hermesGuestEvent!(1, "page-title-updated", JSON.stringify({ pageUrl: "https://example.org/next", pageTitle: "Next page", canGoBack: true, canGoForward: false }));
  win.__hermesGuestEvent!(1, "did-fail-load", JSON.stringify({ errorCode: -105, errorDescription: "x", validatedURL: "https://nope.example/", isMainFrame: true, pageUrl: "", pageTitle: "Next page", canGoBack: true, canGoForward: false }));
  win.__hermesGuestEvent!(2, "did-stop-loading", "{}"); // Unknown guest: ignored.
  win.__hermesGuestEvent!(1, "did-stop-loading", "not json"); // Malformed: ignored.
  expect(seen).toEqual([
    ["did-navigate", "https://example.org/next", true, ""],
    ["page-title-updated", undefined, true, "Next page"],
    ["did-fail-load", -105, true, "Next page"],
  ]);
  expect(tag.getURL()).toBe("https://example.org/next");
  tag.goBack();
  await settle(0);
  expect(sent.at(-1)).toEqual({ op: "back", guest: 1 });
});

it("loadURL rejects with native's message when the address is refused", async () => {
  const tag = guestTag();
  await settle();
  refuse = (payload) => (payload.op === "load" ? "Hermes does not open this address in its browser." : undefined);
  await expect(tag.loadURL("https://gateway.example.com/")).rejects.toThrow("Hermes does not open this address");
});

for (const operation of ["load", "html"] as const) {
  it(`forwards a deferred initial ${operation} failure to the existing recovery listener once`, async () => {
    const message = operation === "load"
      ? "Sign-in requires your system browser. Use Open in browser."
      : "The offline preview could not be displayed.";
    refuse = payload => payload.op === operation ? message : undefined;
    const tag = guestTag("about:blank");
    const failures: Array<Record<string, unknown>> = [];
    tag.addEventListener("did-fail-load", event => {
      const failure = event as Event & { errorDescription: string; errorCode: number; isMainFrame: boolean };
      failures.push({ message: failure.errorDescription, code: failure.errorCode, mainFrame: failure.isMainFrame, loading: tag.isLoading() });
    });
    if (operation === "load") await tag.loadURL("https://accounts.google.com/gsi/transform");
    else await tag.loadHTML!("<p>Synthetic offline preview</p>");
    await settle();
    expect(failures).toEqual([{ message, code: -2, mainFrame: true, loading: false }]);
    await settle(600);
    expect(sent.filter(payload => payload.op === operation)).toHaveLength(1);
    expect(failures).toHaveLength(1);
  });
}

it("does not publish an old deferred failure after a newer navigation", async () => {
  let finishInitial!: (message: string) => void;
  refuse = payload => payload.op === "load" && payload.url === "https://accounts.google.com/gsi/transform"
    ? new Promise<string>(resolve => { finishInitial = resolve; })
    : undefined;
  const tag = guestTag("https://accounts.google.com/gsi/transform");
  const failed = vi.fn();
  tag.addEventListener("did-fail-load", failed);
  await settle();
  await tag.loadURL("https://example.org/");
  finishInitial("Old sign-in guidance must not cover the new page.");
  await settle();
  expect(failed).not.toHaveBeenCalled();
  expect(tag.isLoading()).toBe(true);
});

it("loads offline HTML through a typed operation rather than a URL", async () => {
  const tag = guestTag("about:blank");
  await settle();
  expect(typeof (tag as unknown as { loadHTML?: unknown }).loadHTML).toBe("function");
  await (tag as GuestElement & { loadHTML(html: string): Promise<void> }).loadHTML("<button>synthetic</button>");
  expect(sent.at(-1)).toEqual({ op: "html", guest: 1, html: "<button>synthetic</button>" });
});

it("clips tall offline guests to the transcript without shrinking their layout viewport", async () => {
  const tag = guestTag("about:blank");
  const pane = document.getElementById("pane")!;
  pane.style.overflowY = "auto";
  pane.getBoundingClientRect = () => ({ left: 0, top: 96, right: 412, bottom: 800, width: 412, height: 704 }) as DOMRect;
  tag.getBoundingClientRect = () => ({ left: 0, top: -200, right: 412, bottom: 1647, width: 412, height: 1847 }) as DOMRect;
  await tag.loadHTML!("<p>Tall synthetic widget</p>");
  await settle();
  expect(sent.find(p => p.op === "bounds")).toMatchObject({
    x: 0, y: 96, w: 412, h: 704, contentW: 412, contentH: 1847, offsetX: 0, offsetY: 296, visible: true,
  });
});

const rect = (top: number, height: number) => ({ left: 0, right: 412, top, bottom: top + height, width: 412, height }) as DOMRect;
const clippedTranscript = (top = -200, inset = 380) => {
  const tag = guestTag("about:blank"), pane = document.getElementById("pane")!;
  const surface = document.createElement("div"), reply = document.createElement("div"), dock = document.createElement("div");
  surface.setAttribute("data-chat-surface", "");
  pane.replaceWith(surface);
  surface.append(pane, dock);
  pane.setAttribute("data-slot", "aui_thread-viewport");
  pane.style.overflowY = "auto";
  pane.getBoundingClientRect = () => rect(96, 704);
  reply.setAttribute("data-sticky-prompt-clip", "");
  reply.style.setProperty("--sticky-prompt-clip", `${inset}px`);
  reply.getBoundingClientRect = () => rect(top, 1847);
  tag.getBoundingClientRect = () => rect(top, 1847);
  pane.append(reply);
  reply.append(tag);
  dock.setAttribute("data-slot", "composer-dock");
  dock.getBoundingClientRect = () => rect(700, 100);
  document.elementFromPoint = ((_x: number, y: number) => y < 180 ? reply : y >= 700 ? dock : cover) as typeof document.elementFromPoint;
  return { tag, pane, reply, dock, surface };
};

for (const [top, inset] of [[-200, 380], [96, 84]]) {
  it(`keeps the full offline layout while clipping pinned prompt and composer at scroll position ${top}`, async () => {
    const { tag } = clippedTranscript(top, inset);
    await tag.loadHTML!("<p>Tall synthetic widget</p>");
    await settle();
    expect(sent.find(p => p.op === "bounds")).toMatchObject({
      y: 180, h: 520, contentH: 1847, offsetY: inset, visible: true,
    });
  });
}

it("still hides the clipped offline guest behind menus, dialogs and inert ancestors", async () => {
  const { tag, surface } = clippedTranscript();
  await tag.loadHTML!("<p>Offline</p>");
  await settle();
  expect(sent.find(p => p.op === "bounds")).toMatchObject({ visible: true });
  cover = document.getElementById("menu");
  await settle();
  expect(sent.at(-1)).toMatchObject({ op: "bounds", visible: false });
  cover = tag;
  await settle();
  expect(sent.at(-1)).toMatchObject({ visible: true });
  surface.setAttribute("inert", "");
  await settle();
  expect(sent.at(-1)).toMatchObject({ visible: false });
});

it("does not use another chat's composer to clip the guest", async () => {
  const { tag, dock } = clippedTranscript();
  const other = document.createElement("div");
  other.setAttribute("data-chat-surface", "");
  document.body.append(other);
  other.append(dock);
  document.elementFromPoint = ((_x: number, y: number) => y < 180 ? other : cover) as typeof document.elementFromPoint;
  await tag.loadHTML!("<p>Offline</p>");
  await settle();
  expect(sent.find(p => p.op === "bounds")).toMatchObject({ y: 180, h: 620, visible: true });
});

it("does not apply transcript clipping to a network browser guest", async () => {
  const { tag } = clippedTranscript(96, 84);
  await tag.loadURL("https://example.org/");
  await settle();
  expect(sent.find(p => p.op === "bounds")).toMatchObject({ y: 96, h: 819, visible: false });
  expect(sent.find(p => p.op === "bounds")).not.toHaveProperty("contentH");
});

it("routes native offline vertical gestures to the owning transcript, not another session", async () => {
  const tag = guestTag("about:blank");
  const pane = document.getElementById("pane")!;
  pane.style.overflowY = "auto";
  Object.defineProperty(pane, "scrollHeight", { value: 4000, configurable: true });
  Object.defineProperty(pane, "clientHeight", { value: 704, configurable: true });
  await tag.loadHTML!("<p>Tall synthetic widget</p>");
  await settle();
  win.__hermesGuestEvent!(1, "preview-scroll", JSON.stringify({ dy: 150 }));
  expect(pane.scrollTop).toBe(150);
  win.__hermesGuestEvent!(1, "preview-scroll", JSON.stringify({ dy: 999999 }));
  win.__hermesGuestEvent!(2, "preview-scroll", JSON.stringify({ dy: 150 }));
  expect(pane.scrollTop).toBe(150);
});

it("removing the tag destroys the guest; an evicted guest reopens at its page when shown again", async () => {
  const tag = guestTag();
  await settle();
  win.__hermesGuestEvent!(1, "did-navigate", JSON.stringify({ url: "https://example.org/b", pageUrl: "https://example.org/b" }));
  win.__hermesGuestEvent!(1, "evicted", "{}");
  sent = [];
  await settle();
  expect(sent).toEqual([
    { op: "create", guest: 1 },
    { op: "bounds", guest: 1, x: 0, y: 96, w: 412, h: 704, visible: true },
    { op: "load", guest: 1, url: "https://example.org/b" },
  ]);
  tag.remove();
  await settle();
  expect(sent.at(-1)).toEqual({ op: "destroy", guest: 1 });
});
