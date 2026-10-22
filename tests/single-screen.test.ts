// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { isSingleScreen, installSingleScreenLayout } from "../src/desktop/single-screen";

afterEach(() => vi.restoreAllMocks());
it("covers common Android single-screen widths and phone landscape", () => {
  for (const width of [320, 360, 375, 393, 412, 432, 443, 480, 600]) {
    expect(isSingleScreen(width, width, 900)).toBe(true);
    expect(isSingleScreen(900, 900, width)).toBe(true);
  }
});
it("never classifies unfolded Fold/tablet from the keyboard-reduced viewport height", () => {
  for (const width of [640, 768, 851, 884, 1024, 1280]) {
    expect(isSingleScreen(width, width, 850)).toBe(false);
  }
});
it("fold/unfold and rotation update transient layout state without saving preferences", () => {
  let width = 443, sw = 443, sh = 976;
  vi.spyOn(window, "innerWidth", "get").mockImplementation(() => width);
  vi.spyOn(window.screen, "width", "get").mockImplementation(() => sw);
  vi.spyOn(window.screen, "height", "get").mockImplementation(() => sh);
  const stop = installSingleScreenLayout();
  expect(document.documentElement.hasAttribute("data-android-compact")).toBe(true);
  width = sw = 851; sh = 884;
  window.dispatchEvent(new Event("resize"));
  expect(document.documentElement.hasAttribute("data-android-compact")).toBe(false);
  width = sw = 976; sh = 443;
  window.dispatchEvent(new Event("resize"));
  expect(document.documentElement.hasAttribute("data-android-compact")).toBe(true);
  stop();
  expect(document.documentElement.hasAttribute("data-android-compact")).toBe(false);
  expect(document.documentElement.style.getPropertyValue("--android-visible-height")).toBe("");
});
