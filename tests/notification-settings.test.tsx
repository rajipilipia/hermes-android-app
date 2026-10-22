// @vitest-environment jsdom
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { installPcAccountSettings } from "../src/desktop/account-settings";
import { registry } from "../vendor/hermes/apps/desktop/src/contrib/registry";
import { pluginSettingsEntries, resolvePluginSettingsTarget, SETTINGS_PLUGINS_AREA } from "../vendor/hermes/apps/desktop/src/contrib/settings-pages";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("offers explicit Android consent and displays denial without repeated prompts or claimed delivery", async () => {
  let requested = 0, permission = "not-requested";
  vi.stubGlobal("prompt", vi.fn((_message: string, payload: string) => {
    const { operation } = JSON.parse(payload);
    if (operation === "request") { requested++; permission = "denied"; }
    return JSON.stringify({ ok: true, permission });
  }));
  const unregister = installPcAccountSettings({ mountSettings: () => () => {} });
  try {
    const entries = pluginSettingsEntries({ contributions: registry.getArea(SETTINGS_PLUGINS_AREA), rows: [], configTitle: "Settings" });
    const target = resolvePluginSettingsTarget(entries, { plugin: "android.pc-connection" });
    render(target!.entry.render!());
    const allow = await screen.findByRole("button", { name: "Allow Android notifications" });
    fireEvent.click(allow);
    expect(requested).toBe(1);
    expect(screen.getByText(/Android notification permission: denied/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Allow Android notifications" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Refresh notification permission" }));
    expect(requested).toBe(1);
  } finally { unregister(); }
});
