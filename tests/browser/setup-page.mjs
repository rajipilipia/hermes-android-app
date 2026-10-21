// TEST ONLY. First launch with no server: serves the built app at the setup origin (as Android
// does, from local files) and drives Hermes' own remote-setup panel against a fake native bridge.
// Proves the web layer only: not the Android WebView, the native dialog, TLS or a real server.
//   npm run build && node tests/browser/setup-page.mjs [outDir]
import { chromium } from "@playwright/test";
import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { extname, join, normalize } from "node:path";

const SETUP = "https://setup.hermes-android.invalid";
const out = process.argv[2] ?? ".cache/setup-page/run";
mkdirSync(out, { recursive: true });
const types = { ".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".wasm": "application/wasm" };
const results = [];
const gate = (id, pass, detail) => { results.push({ id, pass, detail }); console.log(`${pass ? "PASS" : "FAIL"} ${id} ${detail}`); };

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" });
for (const scheme of ["light", "dark"]) {
  const context = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.6, hasTouch: true, isMobile: true, colorScheme: scheme });
  await context.route(`${SETUP}/**`, route => {
    const path = new URL(route.request().url()).pathname;
    const file = normalize(join("dist", path.replace(/^\/assets\//, "")));
    if (!path.startsWith("/assets/") || !file.startsWith("dist") || !existsSync(file)) return route.fulfill({ status: 404, body: "" });
    route.fulfill({ status: 200, contentType: types[extname(file)] ?? "application/octet-stream", body: readFileSync(file) });
  });
  await context.route(/^(?!https:\/\/setup\.hermes-android\.invalid\/).*/, route => route.abort());
  const page = await context.newPage();
  await page.addInitScript(() => {
    // Fake native ServerBridge: records calls, answers like MainActivity would.
    window.__calls = [];
    window.HermesServer = {
      request(id, operation, value) {
        window.__calls.push([operation, value]);
        const reply = (ok, v) => setTimeout(() => window.__hermesServerResult?.(id, ok, v), 50);
        if (operation === "probe") reply(true, JSON.stringify({ baseUrl: "https://gateway.example.com", reachable: true, authMode: "oauth", providers: [{ name: "nous", displayName: "Nous Research", supportsPassword: false }], version: "0.22.0", error: null }));
        else if (operation === "signIn" || operation === "test") reply(true, "https://gateway.example.com");
        else if (operation === "apply") reply(true, "https://gateway.example.com");
        else reply(false, "unexpected");
      },
    };
  });
  const errors = [];
  page.on("pageerror", e => errors.push(String(e)));
  await page.goto(`${SETUP}/assets/index.html`);
  const title = page.getByText("Connect to existing Hermes");
  await title.waitFor({ timeout: 15000 });
  gate(`${scheme}:panel`, true, "Hermes first-run remote setup panel rendered");
  const back = page.getByRole("button", { name: "Back" });
  gate(`${scheme}:back-hidden`, !(await back.isVisible()), "Desktop's Back (local install) is not offered");
  const sideways = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  gate(`${scheme}:no-sideways`, sideways <= 0, `scrollWidth-innerWidth=${sideways}`);
  await page.waitForTimeout(500);
  // Painted colors, not just the class: page backdrop, card and heading must match the scheme and read.
  const paint = await page.evaluate(() => {
    // Computed colors arrive as rgb(0-255) or color(srgb 0-1).
    const rgb = s => { const n = (s.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number); return s.startsWith("color(srgb") ? n.map(v => v * 255) : n; };
    const lum = ([r, g, b]) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
    const heading = [...document.querySelectorAll("h2")].find(h => h.textContent.includes("Connect to existing Hermes"));
    let card = heading; while (card && getComputedStyle(card).backgroundColor.match(/rgba?\([^)]*,\s*0\)$|transparent/)) card = card.parentElement;
    const bg = getComputedStyle(document.body).backgroundColor;
    const c = lum(rgb(getComputedStyle(card).backgroundColor)), h = lum(rgb(getComputedStyle(heading).color)), b = lum(rgb(bg));
    return { page: b, contrast: (Math.max(c, h) + 0.05) / (Math.min(c, h) + 0.05) };
  });
  const darkPage = paint.page < 0.2;
  gate(`${scheme}:theme`, darkPage === (scheme === "dark"), `page luminance ${paint.page.toFixed(3)}`);
  gate(`${scheme}:contrast`, paint.contrast >= 4.5, `heading/card contrast ${paint.contrast.toFixed(2)}:1`);
  const input = page.locator("input").first();
  await input.fill("gateway.example.com");
  await page.waitForFunction(() => window.__calls.some(c => c[0] === "probe"), null, { timeout: 10000 });
  const signIn = page.getByRole("button", { name: /sign in/i }).first();
  await signIn.waitFor({ timeout: 10000 });
  await page.screenshot({ path: `${out}/setup-${scheme}-probed.png` });
  await signIn.click();
  await page.waitForFunction(() => window.__calls.some(c => c[0] === "signIn"), null, { timeout: 10000 });
  // After a successful sign-in the app runs Test itself, so Apply turns on without a hidden step.
  const autoTested = await page.waitForFunction(() => window.__calls.some(c => c[0] === "test"), null, { timeout: 10000 }).then(() => true, () => false);
  gate(`${scheme}:auto-test`, autoTested, "Test connection ran by itself after sign-in");
  const apply = page.getByRole("button", { name: "Apply and reconnect" });
  await page.waitForFunction(el => !el.disabled, await apply.elementHandle(), { timeout: 10000 });
  await apply.click();
  await page.waitForFunction(() => window.__calls.some(c => c[0] === "apply"), null, { timeout: 10000 });
  const calls = await page.evaluate(() => window.__calls.map(c => c[0]));
  const order = calls.filter(c => c !== "probe").join(",");
  gate(`${scheme}:flow`, order === "signIn,test,apply", `native calls ${calls.join(",")}`);
  // Desktop coerces a bare host to http://; native receives that and upgrades to https.
  const values = await page.evaluate(() => [...new Set(window.__calls.map(c => c[1]))]);
  gate(`${scheme}:values`, values.every(v => /^https?:\/\/gateway\.example\.com\/?$/.test(v)), `values ${values.join(" ")}`);
  await page.screenshot({ path: `${out}/setup-${scheme}-applied.png` });
  gate(`${scheme}:errors`, errors.length === 0, errors.join(" | ") || "no page errors");
  await context.close();
}
await browser.close();
writeFileSync(`${out}/results.json`, JSON.stringify(results, null, 2));
const failed = results.filter(r => !r.pass).length;
console.log(`${results.length - failed} PASS, ${failed} FAIL`);
process.exit(failed ? 1 : 0);
