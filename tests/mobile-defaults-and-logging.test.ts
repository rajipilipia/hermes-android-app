import { it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { describeFailure, diag, safeText } from "../src/desktop/diag";
const read = (p: string) => readFileSync(p, "utf8");

it("profile rail is on by default and its choice is saved in localStorage", () => {
  const prefs = read("vendor/hermes/apps/desktop/src/store/profile-rail-prefs.ts");
  expect(prefs).toContain("persistentAtom('hermes.desktop.profileRailVisible', true, Codecs.bool)");
  expect(read("vendor/hermes/apps/desktop/src/store/interface-mode.ts")).toContain(
    "DEFAULT_INTERFACE_MODE: InterfaceMode = 'advanced'",
  );
});

it("web storage is on so every changed setting survives exit", () => {
  const main = read("android/src/us/pilipia/hermes/prototype/MainActivity.java");
  expect(main).toContain("setDomStorageEnabled(true)");
  expect(main).not.toContain("setDomStorageEnabled(false)");
  expect(main).toContain("setAllowFileAccess(false)");
  expect(main).toContain("setSaveFormData(false)");
});

it("native client copies page diagnostics and picker steps to logcat without private data", () => {
  const chrome = read("android/src/us/pilipia/hermes/prototype/DesktopChromeClient.java");
  expect(chrome).toContain('android.util.Log.i("HermesDiag",line)');
  expect(chrome).toContain("onConsoleMessage");
  for (const step of ["picker_request", "picker_result", "picker_staged", "picker_deliver", "picker_cancel", "picker_stage_failed"])
    expect(chrome).toContain(`event=${step}`);
  expect(chrome).not.toMatch(/log\([^)]*(getUri|getData\(\)|getPath|getName|toString\(\))/);
});

it("diagnostic lines redact secrets and keep structural fields only", () => {
  const token = "A".repeat(40);
  expect(safeText(`bearer ${token} ok`)).not.toContain(token);
  expect(safeText("line1\nline2 <b>")).toBe("line1?line2 ?b?");
  const text = describeFailure({ name: "RpcError", code: -32000, message: `bad ${token}` });
  expect(text).toContain("name=RpcError");
  expect(text).toContain("code=-32000");
  expect(text).not.toContain(token);
  expect(describeFailure({ name: "E", message: "secret words" }, false)).not.toContain("secret");
  const seen: string[] = [];
  const original = console.info;
  console.info = (line: string) => void seen.push(line);
  try {
    diag("media_rpc_failed", { method: "desktop.upload.begin", detail: token, empty: undefined });
  } finally {
    console.info = original;
  }
  expect(seen).toHaveLength(1);
  expect(seen[0]).toMatch(/^\[hermes-diag\] media_rpc_failed method=desktop\.upload\.begin/);
  expect(seen[0]).not.toContain(token);
});

it("PC reason detail goes to the log text only, never the visible error text", () => {
  const failure = { name: "Error", status: 403, detail: "attachment live session owner mismatch" };
  expect(describeFailure(failure)).toContain("detail=attachment live session owner mismatch");
  expect(describeFailure(failure, false)).not.toContain("owner mismatch");
  expect(describeFailure(failure, false)).toContain("status=403");
});

import { existsSync } from "node:fs";
import { patchStatusbarSource } from "../src/desktop/statusbar-defaults";

it("Version & updates and Backend version are hidden by default and can be turned on", () => {
  const prefsPath = "vendor/hermes/apps/desktop/src/store/statusbar-prefs.ts";
  const itemsPath = "vendor/hermes/apps/desktop/src/app/shell/hooks/use-statusbar-items.tsx";
  const prefs = patchStatusbarSource("/x/" + prefsPath, read(prefsPath))!;
  expect(prefs).toMatch(/STATUSBAR_HIDDEN_BY_DEFAULT: readonly string\[\] = \[\s+'version-backend',\s+'version-client',/);
  const items = patchStatusbarSource("/x/" + itemsPath, read(itemsPath))!;
  expect(items).toContain("lockedVisible: false,\n    onSelect: () => openUpdateOverlayFor(target),");
  expect(patchStatusbarSource("/x/vendor/hermes/apps/desktop/src/other.ts", "x")).toBeUndefined();
  expect(() => patchStatusbarSource("/x/" + prefsPath, "changed")).toThrow(/changed upstream/);
});

it("compact profile access ignores rail/drawer visibility without competing create dialogs", async () => {
  const { resolveConfig } = await import("vite");
  const { plugins } = await resolveConfig({}, "build");
  const order = plugins.map(plugin => plugin.name);
  expect(order.indexOf("android-statusbar-defaults")).toBeLessThan(order.indexOf("@rolldown/plugin-babel"));
  const base = "/vendor/hermes/apps/desktop/src/";
  const itemsPath = base + "app/shell/hooks/use-statusbar-items.tsx";
  const items = patchStatusbarSource(itemsPath, read(itemsPath.slice(1)))!;
  const hidden = new Function("compactProfilePicker", "sessionsShowing", "profileRailVisible",
    `return ${items.match(/hidden: (.*),\n\s+id: 'profile-switcher'/)![1]}`);
  const original = new Function("sessionsShowing", "profileRailVisible",
    `return ${read(itemsPath.slice(1)).match(/hidden: (.*),\n\s+id: 'profile-switcher'/)![1]}`);
  for (const compact of [true, false]) {
    for (const sessions of [true, false]) {
      for (const rail of [true, false]) {
        expect(hidden(compact, sessions, rail)).toBe(compact ? false : original(sessions, rail));
      }
    }
  }
  expect(items).toContain("const compactProfilePicker = useMediaQuery(");
  expect(items).toMatch(/\n\s+compactProfilePicker,\n/); // Recompute when folding/unfolding.
  const ownsCreateRequest = new Function("sessionsShowing", "profileRailVisible",
    `return ${items.match(/listenForCreateRequests=\{([^}]+)\}/)![1]}`);
  const pickerPath = base + "app/chat/sidebar/profile-dropdown-switcher.tsx";
  const picker = patchStatusbarSource(pickerPath, read(pickerPath.slice(1)))!;
  const create = new Function("listenForCreateRequests", "setCreateOpen",
    picker.match(/lastCreateRef.current = createRequest\n([\s\S]*?)\n\s*\}, \[createRequest/ )![1]);
  for (const sessions of [true, false]) {
    for (const rail of [true, false]) {
      const railOwns = sessions && rail;
      let dropdownOpens = false;
      create(ownsCreateRequest(sessions, rail), (open: boolean) => { dropdownOpens = open; });
      expect(dropdownOpens).toBe(!railOwns);
    }
  }
  expect(picker).toContain("listenForCreateRequests = true"); // Other/wide callers keep their behavior.
  expect(picker).toContain("[createRequest, listenForCreateRequests]");
});

it("app icon is the Hermes Agent portrait as an adaptive icon at every density", () => {
  const manifest = read("android/AndroidManifest.xml");
  expect(manifest).toContain('android:icon="@mipmap/ic_launcher"');
  expect(manifest).toContain('android:roundIcon="@mipmap/ic_launcher_round"');
  for (const d of ["mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi"])
    expect(existsSync(`android/res/mipmap-${d}/ic_launcher_foreground.png`)).toBe(true);
  for (const n of ["ic_launcher.xml", "ic_launcher_round.xml"])
    expect(read(`android/res/mipmap-anydpi-v26/${n}`)).toContain("@mipmap/ic_launcher_foreground");
});
