import { readFileSync } from "node:fs";
import { chromium, type Browser, type Page } from "@playwright/test";
import { afterAll, afterEach, beforeAll, expect, it } from "vitest";

// Real Android stylesheet against the pinned renderer's split/keep-alive DOM.
// Synthetic content only; no server, existing browser, device or credentials.
const css = readFileSync(new URL("../src/desktop/mobile.css", import.meta.url), "utf8");
let browser: Browser;
let page: Page;
beforeAll(async () => { browser = await chromium.launch({ channel: "msedge", headless: true }); }, 30_000);
afterEach(async () => { await page?.close(); });
afterAll(async () => { await browser?.close(); }, 30_000);

async function openFile(chatId: string, width = 540, inactivePreview = false, inlineKind?: "pdf" | "text" | "image") {
  page = await browser.newPage({ viewport: { width, height: 900 } });
  await page.setContent(`<style>body{margin:0}[data-tree-split]{display:flex;width:100%;height:100vh;overflow:hidden}</style>
    <div data-tree-split="root">
      <div data-testid="chat" style="flex:1 1 0;min-width:320px">
        <div data-tree-tab="${chatId}" aria-selected="true">Chat tab</div>
        ${inactivePreview ? '<div data-tree-tab="preview-tile:old" aria-selected="false">Old file tab</div>' : ''}
      </div>
      <div data-testid="file" style="flex:1 1 0;min-width:352px">
        <div data-tree-tab="preview-tile:file:synthetic" aria-selected="true">File tab</div>
        ${inlineKind === "pdf" ? '<canvas aria-label="Synthetic PDF"></canvas>' : inlineKind === "text" ? '<pre>Synthetic text</pre>' : inlineKind === "image" ? '<img alt="Synthetic image">' : ''}
      </div>
    </div>
    <!-- KeepAlivePanes mounts hosts OUTSIDE the grid; tab slots own layout geometry. -->
    <div data-pane-host="${chatId}">Synthetic chat</div>
    ${inactivePreview ? '<div data-pane-host="preview-tile:old" inert></div>' : ''}
    ${inlineKind ? '' : '<div data-pane-host="preview-tile:file:synthetic">Synthetic file</div>'}`);
  await page.addStyleTag({ content: css });
}

for (const [name, id, inactive] of [
  ["workspace", "workspace", false],
  ["session-only group", "session-tile:synthetic", false],
  ["chat with an inactive file tab", "workspace", true],
] as const) {
  it(`gives an open phone file the full width beside ${name}`, async () => {
    await openFile(id, 540, inactive);
    expect(await page.getByTestId("chat").isVisible()).toBe(false);
    const bounds = await page.getByTestId("file").boundingBox();
    expect(bounds?.x).toBe(0);
    expect(bounds?.width).toBeGreaterThanOrEqual(539);
    await page.getByTestId("file").evaluate(element => element.remove());
    await page.locator('[data-pane-host="preview-tile:file:synthetic"]').evaluate(element => element.remove());
    expect(await page.getByTestId("chat").isVisible()).toBe(true);
    expect((await page.getByTestId("chat").boundingBox())?.width).toBeGreaterThanOrEqual(539);
  });
}

for (const kind of ["pdf", "text", "image"] as const) {
  it(`gives an in-grid ${kind} preview full phone width without a keep-alive host`, async () => {
    await openFile("session-tile:synthetic", 443, false, kind);
    expect(await page.locator('[data-pane-host^="preview-tile:"]').count()).toBe(0);
    expect(await page.getByTestId("chat").isVisible()).toBe(false);
    const bounds = await page.getByTestId("file").boundingBox();
    expect(bounds?.x).toBe(0);
    expect(bounds?.width).toBeGreaterThanOrEqual(442);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByTestId("file").evaluate(element => element.remove());
    expect(await page.getByTestId("chat").isVisible()).toBe(true);
    expect((await page.getByTestId("chat").boundingBox())?.width).toBeGreaterThanOrEqual(442);
  });
}

it("preserves the unfolded two-pane layout", async () => {
  await openFile("session-tile:synthetic", 884);
  expect(await page.getByTestId("chat").isVisible()).toBe(true);
  expect(await page.getByTestId("file").isVisible()).toBe(true);
  expect((await page.getByTestId("chat").boundingBox())?.width).toBeGreaterThan(300);
});

it("preserves unfolded in-grid previews", async () => {
  await openFile("session-tile:synthetic", 884, false, "pdf");
  expect(await page.getByTestId("chat").isVisible()).toBe(true);
  expect(await page.getByTestId("file").isVisible()).toBe(true);
  expect((await page.getByTestId("chat").boundingBox())?.width).toBeGreaterThan(300);
});

it("keeps all inline guest placement probes clear of the phone timeline", async () => {
  page = await browser.newPage({ viewport: { width: 443, height: 850 } });
  await page.setContent(`<style>body{margin:0}webview{display:block;width:100%;height:280px}</style>
    <div style="margin:226px 0 0 36px;width:375px"><span data-android-inline-preview style="display:block"><webview></webview></span></div>
    <div data-slot="thread-timeline-ticks" style="position:fixed;left:395px;top:480px;width:48px;height:40px"><button style="width:48px;height:40px">tick</button></div>`);
  await page.addStyleTag({ content: css });
  expect(await page.evaluate(() => {
    const g = document.querySelector("webview")!, r = g.getBoundingClientRect(), d = 12;
    return [[r.x+r.width/2,r.y+r.height/2],[r.x+d,r.y+d],[r.right-d,r.y+d],[r.x+d,r.bottom-d],[r.right-d,r.bottom-d]]
      .every(([x,y]) => document.elementFromPoint(x,y) === g);
  })).toBe(true);
});
