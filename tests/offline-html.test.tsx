// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AndroidOfflineHtml } from "../src/desktop/offline-html";
import { installWebviewTag } from "../src/desktop/webview-tag";

let root: Root;
let sent: Array<Record<string, unknown>>;
let uninstall: () => void;
let covered: boolean;

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  sent = [];
  covered = false;
  document.body.innerHTML = '<div id="root"></div><div id="dialog"></div>';
  uninstall = installWebviewTag(window, async value => {
    sent.push(JSON.parse(value) as Record<string, unknown>);
    return "";
  });
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0, y: 96, left: 0, top: 96, right: 412, bottom: 416,
    width: 412, height: 320, toJSON() {},
  });
  // jsdom has no layout/hit testing. Model the same overlay occlusion the
  // real phone proved: a hit-testable status/error layer covers the guest.
  vi.stubGlobal("innerWidth", 412);
  vi.stubGlobal("innerHeight", 915);
  document.elementFromPoint = (() => {
    if (covered) return document.getElementById("dialog");
    const overlay = document.querySelector<HTMLElement>('[role="status"], [role="alert"]');
    if (overlay && getComputedStyle(overlay).pointerEvents !== "none") return overlay;
    return document.querySelector("webview");
  }) as typeof document.elementFromPoint;
  root = createRoot(document.getElementById("root")!);
});
afterEach(async () => {
  await act(async () => root.unmount());
  uninstall();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const render = () => act(async () => {
  root.render(createElement(AndroidOfflineHtml, {
    srcDoc: "<button>synthetic preview</button>",
    title: "QA offline preview",
    style: { height: 320 },
  }));
});
const settle = () => act(async () => { await vi.advanceTimersByTimeAsync(150); });
const currentGuest = () => Number(sent.filter(payload => payload.op === "create").at(-1)?.guest);
const nativeEvent = (type: string) => act(async () => {
  window.__hermesGuestEvent!(currentGuest(), type, "{}");
});

it("starts its native guest while the loading indicator is still present", async () => {
  await render();
  expect(document.querySelector('[role="status"]')).not.toBeNull();
  await settle();
  expect(sent.some(payload => payload.op === "create")).toBe(true);
  expect(sent.some(payload => payload.op === "html")).toBe(true);
  expect(sent.find(payload => payload.op === "bounds")).toMatchObject({ visible: true });
  await nativeEvent("did-stop-loading");
  expect(document.querySelector('[role="status"], [role="alert"]')).toBeNull();
});

it("keeps failure recovery clickable and starts a fresh guest on Retry", async () => {
  await render();
  await settle();
  await nativeEvent("did-fail-load");
  const error = document.querySelector<HTMLElement>('[role="alert"]')!;
  expect(error.textContent).toContain("could not be displayed");
  expect(getComputedStyle(error).pointerEvents).not.toBe("none");
  await settle();
  expect(sent.filter(payload => payload.op === "bounds").at(-1)).toMatchObject({ visible: false });
  const previous = currentGuest();
  await act(async () => error.querySelector("button")!.click());
  await settle();
  expect(currentGuest()).not.toBe(previous);
  expect(sent.filter(payload => payload.op === "html")).toHaveLength(2);
  await nativeEvent("did-stop-loading");
  expect(document.querySelector('[role="alert"], [role="status"]')).toBeNull();
});

it("still defers a guest hidden by an unrelated dialog", async () => {
  covered = true;
  await render();
  await settle();
  expect(sent.some(payload => payload.op === "create")).toBe(false);
  covered = false;
  await settle();
  expect(sent.some(payload => payload.op === "html")).toBe(true);
});

it("reports tall inline content without the old 1200px truncation", async () => {
  const onHeight = vi.fn();
  await act(async () => root.render(createElement(AndroidOfflineHtml, {
    srcDoc: "<p>Tall synthetic widget</p>", onHeight, style: { height: 280 },
  })));
  await settle();
  await act(async () => window.__hermesGuestEvent!(currentGuest(), "content-height", JSON.stringify({ height: 1847 })));
  expect(document.querySelector("[data-android-inline-preview]")).not.toBeNull();
  expect(onHeight).toHaveBeenLastCalledWith(1847);
  await act(async () => window.__hermesGuestEvent!(currentGuest(), "content-height", JSON.stringify({ height: 9000 })));
  expect(onHeight).toHaveBeenLastCalledWith(8192);
});
