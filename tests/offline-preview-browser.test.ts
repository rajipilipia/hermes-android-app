import { readFileSync, mkdirSync } from "node:fs";
import { resolve, join } from "node:path";
import { spawnSync } from "node:child_process";
import { chromium, type Browser, type Page } from "@playwright/test";
import { afterAll, beforeAll, expect, it } from "vitest";
import { androidRemoteHtmlPreviewDocument } from "../src/desktop/full-html-preview";

let browser: Browser;
let page: Page;
let outbound = 0;
beforeAll(async () => {
  const out = resolve(".cache/offline-preview-tests");
  mkdirSync(out, { recursive: true });
  const java = process.env.JAVA_HOME || "C:/Program Files/Microsoft/jdk-21.0.8.9-hotspot";
  const source = "android/src/us/pilipia/hermes/prototype/";
  const compile = spawnSync(join(java, "bin/javac.exe"), ["-encoding", "UTF-8", "--release", "8", "-d", out,
    source + "OfflinePreview.java", source + "NativeHostPolicy.java", source + "ServerOrigin.java", "tests/OfflinePreviewHostTest.java"], { encoding: "utf8" });
  expect(compile.status, compile.stderr).toBe(0);
  const fixture = join(out, "synthetic.html");
  const run = spawnSync(join(java, "bin/java.exe"), ["-cp", out, "us.pilipia.hermes.prototype.OfflinePreviewHostTest", fixture], { encoding: "utf8" });
  expect(run.status, run.stdout + run.stderr).toBe(0);
  const native = readFileSync(source + "OfflinePreview.java", "utf8");
  const policy = native.match(/static final String CSP="([^"]+)";/)?.[1];
  expect(policy).toBeTruthy();
  browser = await chromium.launch({ channel: "msedge", headless: true });
  page = await browser.newPage({ viewport: { width: 540, height: 900 } });
  await page.route("**/*", route => {
    if (route.request().isNavigationRequest() && route.request().url() === "https://hermes-offline-preview.invalid/")
      return route.fulfill({ body: androidRemoteHtmlPreviewDocument("data:text/html;base64," + readFileSync(fixture).toString("base64"))!, contentType: "text/html", headers: { "Content-Security-Policy": "sandbox allow-scripts; " + policy } });
    outbound++; return route.abort();
  });
  await page.goto("https://hermes-offline-preview.invalid/");
}, 30_000);
afterAll(async () => { await page?.close(); await browser?.close(); }, 30_000);

it("runs a real button interaction and keyboard input in the native-generated document", async () => {
  await page.locator("#counter").click();
  expect(await page.locator("#counter").textContent()).toBe("1");
  await page.locator("#filter").fill("გამარჯობა");
  expect(await page.locator("#filter").inputValue()).toBe("გამარჯობა");
});
it("gives guest scripts no persistent app storage, credentials or network", async () => {
  const result = await page.evaluate(async () => {
    const errors = [() => localStorage.setItem("probe", "1"), () => sessionStorage.setItem("probe", "1"), () => indexedDB.open("probe"), () => document.cookie].map(action => {
      try { action(); return "allowed"; } catch (error) { return (error as Error).name; }
    });
    let blocked = false;
    try { await fetch("https://gateway.example.com/api/fs/list"); } catch { blocked = true; }
    return { errors, blocked, nativeBridge: "HermesApi" in window || "HermesPc" in window || "HermesBrowser" in window };
  });
  expect(result.errors).toEqual(["SecurityError", "SecurityError", "SecurityError", "SecurityError"]);
  expect(result.blocked).toBe(true);
  expect(result.nativeBridge).toBe(false);
  expect(outbound).toBe(0);
});
