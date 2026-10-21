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

it("app icon is the Hermes Agent portrait as an adaptive icon at every density", () => {
  const manifest = read("android/AndroidManifest.xml");
  expect(manifest).toContain('android:icon="@mipmap/ic_launcher"');
  expect(manifest).toContain('android:roundIcon="@mipmap/ic_launcher_round"');
  for (const d of ["mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi"])
    expect(existsSync(`android/res/mipmap-${d}/ic_launcher_foreground.png`)).toBe(true);
  for (const n of ["ic_launcher.xml", "ic_launcher_round.xml"])
    expect(read(`android/res/mipmap-anydpi-v26/${n}`)).toContain("@mipmap/ic_launcher_foreground");
});
