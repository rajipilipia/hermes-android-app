// TEST ONLY. A layout saved on a wide screen (Terminal beside the chat, chat weight near 0) must not squeeze the
// chat on a one-screen phone. Synthetic data, the real production renderer, a 443x850 viewport.
//   DESKTOP_TEST_ORIGIN=http://127.0.0.1:18772 CHROMIUM=<edge> node tests/browser/phone-saved-layout.mjs [outDir]
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { openPage } from "./mobile-layout.mjs";

const out = process.argv[2] ?? ".cache/phone-saved-layout";
mkdirSync(out, { recursive: true });
// The phone's real saved tree (10/28), group ids only, no session data.
const tree = { type: "split", id: "spl-root", orientation: "row", children: [
  { type: "group", id: "grp-sessions", panes: ["sessions", "hermes-bots:pane", "terminal"], active: "hermes-bots:pane", minimized: false },
  { type: "group", id: "grp-main", panes: ["workspace"], active: "workspace" },
  { type: "group", id: "g-routines", panes: ["hermes-bots:routines"], active: "hermes-bots:routines", minimized: true },
  { type: "group", id: "grp-review", panes: ["review"], active: "review" },
  { type: "group", id: "grp-files", panes: ["files"], active: "files" },
], weights: [1, 0.001138631311125126, 0.0022772626222502517, 0.5681818181818181, 0.6818181818181818] };

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM });
const vp = { name: "phone-443x850", width: 443, height: 850, dpr: 2.44 };
const { context, page, errors } = await openPage(browser, vp, { detailed: true });
// DEFAULT=1 keeps Desktop's default layout (Terminal docked at the bottom) for the same checks.
if (!process.env.DEFAULT) await page.evaluate((t) => { localStorage.setItem("hermes.desktop.layoutTree.v2", JSON.stringify(t)); localStorage.setItem("hermes.desktop.layoutPreset.active", "custom"); }, tree);
await page.reload({ waitUntil: "networkidle" });
await page.locator("[data-contrib-shell]").waitFor({ timeout: 60000 });
await page.waitForTimeout(1500);
const m = await page.evaluate(() => {
  const w = (sel) => { const e = [...document.querySelectorAll(sel)].find((x) => x.getBoundingClientRect().width > 0); return e ? Math.round(e.getBoundingClientRect().width) : 0; };
  const tabs = [...document.querySelectorAll('[data-slot="pane-tab"]')].filter((t) => t.getBoundingClientRect().width > 0).map((t) => (t.textContent || "").trim().slice(0, 20));
  return { composer: w('[data-slot="composer-root"]'), thread: w('[data-slot="aui_thread-viewport"], [data-slot="aui_thread-root"]'), tabs, scrollW: document.documentElement.scrollWidth, stored: localStorage.getItem("hermes.desktop.layoutTree.v2")?.includes("terminal") };
});
await page.screenshot({ path: `${out}/saved-layout.png` });
// Terminal must still open: as Desktop's own slide-over.
await page.evaluate(() => window.dispatchEvent(new CustomEvent("hermes:pane-toggle-reveal", { detail: { id: "terminal", mode: "open" } })));
await page.waitForTimeout(800);
const term = await page.evaluate(() => {
  const o = document.querySelector('[data-narrow-overlay]'); if (!o) return { open: false };
  const b = o.getBoundingClientRect();
  // Every tab in the slide-over must take its own tap (nothing from the titlebar on top of it).
  const tabs = [...o.querySelectorAll('[data-slot="pane-tab"]')].map((t) => { const r = t.getBoundingClientRect(); const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return { text: (t.textContent || "").trim(), own: !!hit && t.contains(hit), hit: hit ? `${hit.tagName}:${hit.getAttribute("aria-label") ?? ""}` : "" }; });
  return { open: true, id: o.dataset.narrowOverlay, box: [b.x, b.y, b.width, b.height].map(Math.round), tabs };
});
await page.screenshot({ path: `${out}/terminal-overlay.png` });
console.log(JSON.stringify({ ...m, terminalOpens: term, errors: errors.length }));
await context.close(); await browser.close();
const ok = m.composer >= 380 && m.scrollW === 443 && !m.tabs.some((t) => /terminal/i.test(t))
  && term.open && term.box[2] >= 240 && term.tabs.every((t) => t.own);
console.log(ok ? "PASS: chat keeps the phone width with a wide-screen saved layout" : "FAIL");
process.exit(ok ? 0 : 1);
