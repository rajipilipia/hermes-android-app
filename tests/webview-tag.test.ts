// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { installWebviewTag, type GuestElement } from "../src/desktop/webview-tag";

const win = window as Window & typeof globalThis;
let sent: Array<Record<string, unknown>>;
let refuse: ((payload: Record<string, unknown>) => string | undefined) | undefined;
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
    const error = refuse?.(payload);
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
