import { it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
const read = (name: string) => {
  try {
    return readFileSync(join(process.cwd(), "android", name), "utf8");
  } catch {
    return "";
  }
};
it("native shell is local-asset only with no file access, generic URL bridge or SSL bypass", () => {
  const java = read("src/us/pilipia/hermes/prototype/MainActivity.java");
  expect(java).toContain("web.loadUrl(NativeHostPolicy.appUrl());");
  expect(java).toContain("setAllowFileAccess(false)");
  expect(java).toContain("setAllowContentAccess(false)");
  expect(java).toContain("handler.cancel()");
  expect(java).not.toContain("handler.proceed");
  expect(java).toContain('web.addJavascriptInterface(new PcBridge(),"HermesPc")');
  // Server setup takes only a typed address, normalized natively; never a fetch, URL-open or header bridge.
  expect(java).toContain('web.addJavascriptInterface(new ServerBridge(),"HermesServer")');
  expect(java).toContain("String target=ServerOrigin.normalize(value);");
  expect(java).not.toMatch(/public.*(?:fetch|openUrl)\(/);
  // UI settings persist through localStorage (app-private, no backup).
  expect(java).toContain("setDomStorageEnabled(true)");
});
it("manifest disables backup and cleartext network policy grants only exact debug local hosts", () => {
  const manifest = read("AndroidManifest.xml"),
    policy = read("res/xml/network_security_config.xml");
  expect(manifest).toContain('android:allowBackup="false"');
  expect(manifest).toContain('android:usesCleartextTraffic="false"');
  expect(manifest).not.toContain("MANAGE_EXTERNAL_STORAGE");
  expect(policy).toContain('base-config cleartextTrafficPermitted="false"');
  expect(policy.match(/<domain includeSubdomains="false">/g)).toHaveLength(3);
  for (const host of ["localhost", "127.0.0.1", "10.0.2.2"])
    expect(policy).toContain(`>${host}</domain>`);
});
it("native stock-server REST uses the same capability contract as the page and the PC adapter", () => {
  const js = readFileSync("src/desktop/capability-contract.json");
  expect(readFileSync("android/assets/capability-contract.json").equals(js)).toBe(true);
  expect(readFileSync("pc/capability-contract.json").equals(js)).toBe(true);
  const java = read("src/us/pilipia/hermes/prototype/MainActivity.java");
  expect(java).toContain('web.addJavascriptInterface(new ApiBridge(),"HermesApi")');
  expect(java).toContain("call=api.prepare(request);");
});
it("in-app browser: system-browser links and the native pane are the only browser operations, both checked natively", () => {
  const java = read("src/us/pilipia/hermes/prototype/MainActivity.java");
  expect(java).toContain('web.addJavascriptInterface(new BrowserBridge(),"HermesBrowser")');
  // Stage 0 "external" plus stage 1 "guest" (BrowserPane); nothing else reaches native.
  expect(java).toContain('!("external".equals(operation)||"guest".equals(operation))||value==null||value.length()>("guest".equals(operation)?3*1024*1024:8192))return;');
  expect(java).toContain("if(!NativeHostPolicy.allowExternal(value))");
});
