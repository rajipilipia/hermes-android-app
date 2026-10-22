// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ReasoningPill } from "../vendor/hermes/apps/desktop/src/app/chat/composer/reasoning-pill";
import { registerFloatingComposer } from "../vendor/hermes/apps/desktop/src/app/chat/composer/floating-target";
import { $floatingComposerOwner } from "../vendor/hermes/apps/desktop/src/app/chat/composer/floating-state";
import { installMobile } from "../src/desktop/mobile";
import { setCurrentReasoningEffort } from "../vendor/hermes/apps/desktop/src/store/session";

const stops: (() => void)[] = [];
afterEach(() => {
  cleanup();
  stops.splice(0).reverse().forEach(stop => stop());
  $floatingComposerOwner.set(null);
  delete document.documentElement.dataset.androidTouch;
  vi.unstubAllGlobals();
});
function setup() {
  vi.stubGlobal("matchMedia", () => ({ matches: true, addEventListener() {}, removeEventListener() {} }));
  stops.push(installMobile());
  setCurrentReasoningEffort("high");
  render(<div data-tree-group="qa" data-chat-surface data-composer-surface-id="qa">
    <div data-composer-owner="qa"><form data-slot="composer-root">
      <div contentEditable data-slot="composer-rich-input" suppressContentEditableWarning>draft text</div>
      <ReasoningPill disabled={false} model={{ canSwitch: true, model: "qa", provider: "qa", reasoningMenuContent: <div role="menuitem">Medium</div> }} />
    </form></div>
    <button aria-label="Outside toolbar">Toolbar</button>
  </div>);
  stops.push(registerFloatingComposer("qa", { groupId: "qa", target: "main" }));
}
it("a touch opens the genuine reasoning dropdown and leaves its choices visible", async () => {
  setup();
  const pill = screen.getByTestId("reasoning-pill");
  await act(async () => {
    fireEvent.pointerDown(pill, { pointerType: "touch", button: 0, pointerId: 1 });
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.pointerUp(pill, { pointerType: "touch", button: 0, pointerId: 1 });
    fireEvent(pill, new PointerEvent("click", { bubbles: true, pointerType: "touch", button: 0 }));
  });
  expect(screen.queryByRole("menu")).not.toBeNull();
  expect(screen.queryByText("Medium")).not.toBeNull();
});
it("Android focus after touch release stays on the tapped control instead of jumping to the composer", () => {
  setup();
  const button = screen.getByRole("button", { name: "Outside toolbar" });
  act(() => {
    fireEvent.pointerDown(button, { pointerType: "touch", button: 0 });
    fireEvent.pointerUp(button, { pointerType: "touch", button: 0 });
    button.focus();
  });
  expect(document.activeElement).toBe(button);
});
