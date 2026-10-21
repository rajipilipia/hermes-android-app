// @vitest-environment jsdom
import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { installSignInControl } from "../src/desktop/auth-control";
import { installPcAccountSettings } from "../src/desktop/account-settings";
import { registry } from "../vendor/hermes/apps/desktop/src/contrib/registry";
import {
  pluginSettingsEntries,
  resolvePluginSettingsTarget,
  SETTINGS_PLUGINS_AREA,
} from "../vendor/hermes/apps/desktop/src/contrib/settings-pages";

let unregister: (() => void) | undefined;
afterEach(() => {
  cleanup();
  unregister?.();
  unregister = undefined;
  document.body.replaceChildren();
});

it("exposes local logout through the genuine Settings registry, not over the composer", async () => {
  let acknowledge!: () => void;
  const auth = {
    signIn: vi.fn(async () => {}),
    ticket: vi.fn(async () => "fresh"),
    signOut: vi.fn(() => new Promise<void>((resolve) => { acknowledge = resolve; })),
  };
  const restart = vi.fn();
  const control = installSignInControl({ auth, restart, nativeAvailable: true });
  control.authenticated();
  expect(document.body.textContent).not.toContain("Sign out of this PC");
  unregister = installPcAccountSettings(control);
  const entries = pluginSettingsEntries({
    contributions: registry.getArea(SETTINGS_PLUGINS_AREA),
    rows: [],
    configTitle: "Agent settings",
  });
  const target = resolvePluginSettingsTarget(entries, { plugin: "android.pc-connection" });
  expect(target?.entry.title).toBe("PC connection");
  expect(target?.entry.pluginId).toBeUndefined();
  render(<StrictMode>{target!.entry.render!()}</StrictMode>);
  expect(document.querySelector(".hermes-android-signin")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Sign out of this PC" }));
  expect(auth.signOut).toHaveBeenCalledOnce();
  expect(restart).not.toHaveBeenCalled();
  acknowledge();
  await vi.waitFor(() => expect(restart).toHaveBeenCalledOnce());
  cleanup();
  expect(auth.signOut).toHaveBeenCalledOnce();
  control.dispose();
});
