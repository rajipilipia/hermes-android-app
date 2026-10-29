import { readFileSync } from "node:fs";
import { expect, it } from "vitest";

const read = (path: string) => readFileSync(path, "utf8");
const pane = read("android/src/us/pilipia/hermes/prototype/BrowserPane.java");
const activity = read("android/src/us/pilipia/hermes/prototype/MainActivity.java");

it("in-app browser guests get no bridge, no file/content access, platform TLS and no permissions (R1 stage 1)", () => {
  expect(pane).not.toContain("addJavascriptInterface");
  expect(pane).not.toContain("setDownloadListener");
  for (const rule of [
    "setAllowFileAccess(false)", "setAllowContentAccess(false)", "MIXED_CONTENT_NEVER_ALLOW",
    "setSupportMultipleWindows(true)", "setGeolocationEnabled(false)", "setAcceptThirdPartyCookies(view,false)",
    "handler.cancel();", "request.deny();", "callback.invoke(origin,false,false);", "callback.onReceiveValue(null);return true;",
    "NativeHostPolicy.allowGuest(url)", "if(document!=null||sameServer(url))",
    "setBlockNetworkLoads(true)", "setDomStorageEnabled(false)", "sandbox allow-scripts; ",
  ]) expect(pane).toContain(rule);
  expect(pane).not.toMatch(/handler\.proceed|\.grant\(/);
  expect(pane).toMatch(/onCreateWindow[\s\S]*return false;/);
  expect(pane).toContain("NativeHostPolicy.requiresExternalAuthentication(url)");
  expect(pane).toContain("version==loadVersion");
});

it("the activity routes guest requests, destroys guests with the document and gives Back to the visible page first", () => {
  expect(activity).toContain('"guest".equals(operation)');
  expect(activity).toContain("browser.request(value)");
  expect(activity).toMatch(/chrome\.documentChanged\(\);if\(browser!=null\)browser\.destroyAll\(\);/);
  const back = activity.slice(activity.indexOf("private void handleBack(){"));
  expect(back.indexOf("browser.back()")).toBeGreaterThan(back.indexOf("Type.ime()"));
  expect(back.indexOf("browser.back()")).toBeLessThan(back.indexOf("hermes:native-back"));
  // Only the bundled page's existing BrowserBridge reaches the pane; still no new JS interface.
  expect(activity.match(/addJavascriptInterface/g)).toHaveLength(4);
});

it("the sign-in page can bring Hermes back: one browsable app link that only resumes the app", () => {
  const manifest = read("android/AndroidManifest.xml");
  expect(manifest.match(/android\.intent\.category\.BROWSABLE/g)).toHaveLength(1);
  expect(manifest).toContain('<data android:scheme="hermes-prototype" android:host="signed-in"/>');
  // The return intent carries no data the app reads: onNewIntent only hands intents to notifications.
  const onNewIntent = activity.slice(activity.indexOf("protected void onNewIntent"), activity.indexOf("// System bars"));
  expect(onNewIntent).not.toMatch(/getData|getExtras|getStringExtra/);
  const auth = read("android/src/us/pilipia/hermes/prototype/NativeAuth.java");
  expect(auth).toContain('RETURN_LINK="intent://signed-in#Intent;scheme=hermes-prototype;package=us.pilipia.hermes.prototype;end"');
  expect(auth).not.toMatch(/RETURN_PAGE=[^;]*<script/);
});

it("stage 1 gives links back to Desktop's own pane once, and installs the tag before the renderer", () => {
  const main = read("src/main.tsx");
  expect(main).toContain('localStorage.removeItem("hermes.desktop.alwaysExternalLinks.v1")');
  expect(main).not.toContain('localStorage.setItem("hermes.desktop.alwaysExternalLinks.v1", "true")');
  expect(main.indexOf("installWebviewTag(window")).toBeLessThan(main.indexOf('import("../vendor/hermes/apps/desktop/src/main")'));
});
