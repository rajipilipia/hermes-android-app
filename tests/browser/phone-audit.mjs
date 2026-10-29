// TEST ONLY. Phone layout audit on the real production renderer with synthetic data.
// Measures the defects found on the real phone (docs/CODER-HANDOVER-2026-10-26.md, A1-A10)
// in a 443x850 phone viewport (Pixel cover screen). Proves the web layer only.
//   DESKTOP_TEST_ORIGIN=http://127.0.0.1:18767 node tests/browser/phone-audit.mjs [outDir]
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { openPage } from "./mobile-layout.mjs";

const out = process.argv[2] ?? ".cache/phone-audit/run";
mkdirSync(out, { recursive: true });
const vp = { name: "phone-443x850", width: Number(process.env.W ?? 443), height: Number(process.env.H ?? 850), dpr: 2.44 };

const rect = (el) => { const r = el.getBoundingClientRect(); return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height), r: Math.round(r.right), b: Math.round(r.bottom) }; };

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM });
const report = { vp: vp.name, steps: {} };
try {
  const { page, errors, calls } = await openPage(browser, vp, { detailed: true });
  report.errors = errors;
  report.calls = calls;
  const titlebar = () => page.evaluate((rectSrc) => {
    const rect = new Function(`return ${rectSrc}`)();
    const header = document.querySelector("[data-panel-header]");
    const buttons = [...document.querySelectorAll("[data-titlebar-cluster] button, [data-panel-header] button")]
      .filter((b) => b.getBoundingClientRect().width > 0)
      .map((b) => ({ label: b.getAttribute("aria-label") ?? b.textContent.trim().slice(0, 20), ...rect(b) }));
    const tabs = [...document.querySelectorAll('[data-slot="pane-tab"]')].filter((t) => t.getBoundingClientRect().width > 0)
      .map((t) => { const label = t.querySelector(".truncate, span") ?? t; const cs = getComputedStyle(label); return { text: t.textContent.trim().slice(0, 30), ...rect(t), scrollW: label.scrollWidth, clientW: label.clientWidth, ellipsis: cs.textOverflow, mask: getComputedStyle(t).maskImage }; });
    return { innerW: innerWidth, header: header ? rect(header) : null, buttons, tabs };
  }, rect.toString());
  report.steps.titlebarStart = await titlebar();
  await page.screenshot({ path: `${out}/01-start.png` });

  // Open extra session tabs with the "+" in the tab strip, like the real phone test.
  for (let i = 0; i < 4; i++) {
    const plus = page.locator('[data-zone-tabstrip] button[aria-label*="New"], [data-panel-header] button[aria-label*="New"]').last();
    if (!(await plus.count())) break;
    await plus.tap({ timeout: 3000 }).catch(() => {});
    await page.waitForTimeout(400);
  }
  report.steps.titlebarMany = await titlebar();
  await page.screenshot({ path: `${out}/02-many-tabs.png` });

  // A9: the composer card must be opaque so chat text never shows through it.
  report.steps.composer = await page.evaluate(() => {
    const surface = document.querySelector('[data-slot="composer-surface"]') ?? document.querySelector('form[data-slot="composer-root"]');
    const chain = [];
    for (let el = surface; el && chain.length < 6; el = el.parentElement) chain.push({ slot: el.dataset?.slot ?? el.tagName, bg: getComputedStyle(el).backgroundColor, backdrop: getComputedStyle(el).backdropFilter });
    return chain;
  });

  // A3/A4: visible controls, their size and whether an icon-only one has an accessible name.
  const controls = (scope) => page.evaluate((sel) => [...document.querySelectorAll(`${sel} button, ${sel} [role="button"], ${sel} [role="switch"], ${sel} [role="tab"]`)]
    .filter((b) => { const r = b.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
    .map((b) => {
      const r = b.getBoundingClientRect();
      const after = getComputedStyle(b, "::after");
      const name = b.getAttribute("aria-label") || b.getAttribute("title") || b.textContent.trim();
      return { name: name.slice(0, 30), w: Math.round(r.width), h: Math.round(r.height), hit: after.content !== "none" && after.position === "absolute" };
    }), scope);
  report.steps.chatControls = await controls("body");

  // Send path: one word typed without a space must reach prompt.submit through the new routing.
  const editor = page.locator('[data-slot="composer-rich-input"]:visible').first();
  await editor.tap().catch(() => {});
  await page.keyboard.type("hello");
  report.steps.editorAttrs = await page.evaluate(() => {
    const e = document.activeElement;
    return { slot: e?.dataset?.slot, spellcheck: e?.getAttribute("spellcheck"), autocorrect: e?.getAttribute("autocorrect"), autocapitalize: e?.getAttribute("autocapitalize"), enterkeyhint: e?.getAttribute("enterkeyhint") };
  });
  await page.keyboard.press("Enter");
  await page.waitForTimeout(300);
  await page.keyboard.type("world");
  await page.keyboard.press("Shift+Enter");
  await page.keyboard.type("shift");
  // Several tabs each keep a composer; read the one that has focus.
  report.steps.afterEnter = await page.evaluate(() => { const e = document.activeElement; return `${e?.dataset?.slot} ${JSON.stringify(e?.innerText)}`; });
  report.steps.enterInsertedNewline = await page.evaluate(() => /^hello\n+world\n+shift$/.test((document.activeElement?.innerText ?? "").trim()));
  report.steps.submitBeforeSend = calls.filter((c) => c === "prompt.submit").length;
  await page.locator('form[data-slot="composer-root"] button[type="submit"]').first().tap({ timeout: 3000 }).catch((e) => { report.steps.sendTapError = String(e).slice(0, 200); });
  await page.waitForTimeout(1500);
  report.steps.submitAfterSend = calls.filter((c) => c === "prompt.submit").length;
  report.steps.toasts = await page.evaluate(() => [...document.querySelectorAll('[data-sonner-toast], [role="alert"], [role="status"]')].map((t) => t.textContent.trim().slice(0, 120)).filter(Boolean));
  await page.screenshot({ path: `${out}/02b-after-send.png` });
  await page.getByRole("button", { name: "Open settings" }).tap().catch(() => {});
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${out}/03-settings.png` });
  report.steps.settings = await page.evaluate(() => {
    const dialog = document.querySelector('[data-overlay-surface]');
    return { role: dialog?.getAttribute("role") ?? null, ariaModal: dialog?.getAttribute("aria-modal") ?? null, rect: dialog ? (({ x, y, width, height }) => ({ x, y, width, height }))(dialog.getBoundingClientRect()) : null };
  });
  report.steps.settingsControls = await controls("[data-overlay-surface]");
  report.steps.unnamed = report.steps.settingsControls.filter((c) => !c.name);

  // Phone rules that Desktop CSS of equal strength used to override (0.3.0: mobile.css loads BEFORE the
  // Desktop styles). Probe elements use Desktop's own selectors, so a future Desktop CSS change that wins
  // again shows up here as a computed-style mismatch, not as a silent regression on the phone.
  report.steps.winningRules = await page.evaluate(() => {
    const host = document.createElement("div");
    host.innerHTML = '<div data-slot="composer-status-stack"><div class="status-row"><div class="status-row-actions"><button type="button">Details</button></div></div></div>' +
      '<div data-slot="aui_msg-actions"><button type="button">Copy</button></div>';
    document.body.append(host);
    const actions = getComputedStyle(host.querySelector(".status-row-actions"));
    const reply = host.querySelector('[data-slot="aui_msg-actions"] button').getBoundingClientRect();
    const result = { statusRowGridColumn: actions.gridColumnStart, statusRowGridRow: actions.gridRowStart, replyActionW: Math.round(reply.width), replyActionH: Math.round(reply.height) };
    host.remove();
    return result;
  });
  // F8 / F16: invisible 40px tap areas (measured with elementFromPoint, so a covered or clipped area counts as lost)
  // and no text under 12px on the single-screen phone. Run on the main screen, settings closed.
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);
  report.steps.touchAndText = await page.evaluate(() => {
    const vertical = (el) => {
      const r = el.getBoundingClientRect(), cx = r.x + r.width / 2, cy = r.y + r.height / 2;
      const owns = (y) => { const t = document.elementFromPoint(cx, y); return !!t && (t === el || el.contains(t)); };
      let top = cy, bottom = cy;
      while (owns(top - 1) && cy - top < 60) top--;
      while (owns(bottom + 1) && bottom - cy < 60) bottom++;
      return Math.round(bottom - top);
    };
    const pick = (sel) => [...document.querySelectorAll(sel)].find((e) => e.getBoundingClientRect().width > 0);
    const hit = (sel) => { const el = pick(sel); return el ? vertical(el) : null; };
    let small = 0;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n; (n = walker.nextNode());) {
      const el = n.parentElement;
      if (!n.textContent.trim() || !el) continue;
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0 && parseFloat(getComputedStyle(el).fontSize) < 12) small++;
    }
    return { titlebarHitH: hit('[data-size="icon-titlebar"]'), statusbarHitH: hit('footer[data-slot="statusbar"] button'), smallTextNodes: small };
  });

  // 48dp tap targets (the author, 2026-10-28) and 12px menu text. A hit area is measured with elementFromPoint along
  // the control's centre lines, so an area that is covered, clipped or overlapped by a neighbour counts as lost.
  // Android's minimum is 48. Hit areas are invisible and must not overlap a neighbour or leave a clipping parent, so
  // some controls are physically limited (touching icons, the 34px tab strip, the 41px session rows, the card edge).
  // Those entries carry their own lower number and a reason ("why"); every other number is the full 47 (48 minus 1px
  // of sub-pixel rounding). Nothing may be below 40 without a reason: that is checked first, below.
  await page.evaluate(() => {
    window.__hit = (el) => {
      const r = el.getBoundingClientRect(), cx = r.x + r.width / 2, cy = r.y + r.height / 2;
      const owns = (x, y) => { const t = document.elementFromPoint(x, y); return !!t && (t === el || el.contains(t)); };
      if (!owns(cx, cy)) { const t = document.elementFromPoint(cx, cy); return { w: 0, h: 0, cover: t ? `${t.tagName}[${t.dataset.slot ?? ""}${t.getAttribute("aria-label") ? ":" + t.getAttribute("aria-label") : ""}]` : "none" }; }
      let l = cx, rr = cx, t = cy, b = cy;
      while (owns(l - 1, cy) && cx - l < 80) l--;
      while (owns(rr + 1, cy) && rr - cx < 80) rr++;
      while (owns(cx, t - 1) && cy - t < 80) t--;
      while (owns(cx, b + 1) && b - cy < 80) b++;
      return { w: Math.round(rr - l) + 1, h: Math.round(b - t) + 1 };
    };
    window.__pick = (sel, nth = 0) => {
      const all = [...document.querySelectorAll(sel)].filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
      return all[nth < 0 ? all.length + nth : nth] ?? null;
    };
    window.__smallText = (rootSel) => {
      const root = document.querySelector(rootSel);
      if (!root) return -1;
      let small = 0;
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      for (let n; (n = walker.nextNode());) {
        const el = n.parentElement;
        if (!n.textContent.trim() || !el) continue;
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0 && parseFloat(getComputedStyle(el).fontSize) < 12) small++;
      }
      return small;
    };
  });
  const measureTargets = (state, list) => page.evaluate(({ state, list }) => list.map((t) => {
    const el = window.__pick(t.sel, t.nth ?? 0);
    const m = el ? window.__hit(el) : { w: 0, h: 0 };
    const r = el?.getBoundingClientRect();
    return { state, id: t.id, found: !!el, ...m, box: r ? `${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)}` : "" };
  }), { state, list });
  const targets = [];
  const expected = {};
  const expect = (id, w, h, why) => { expected[id] = { w, h, why }; };
  const run = async (state, list) => {
    for (const t of list) expect(t.id, t.w ?? 47, t.h ?? 47, t.why);
    targets.push(...(await measureTargets(state, list.map(({ id, sel, nth }) => ({ id, sel, nth })))));
  };
  const tapBy = (name) => page.getByRole("button", { name }).first().tap({ timeout: 3000 }).catch(() => {});
  const closeMenu = async () => { await page.keyboard.press("Escape"); await page.waitForTimeout(300); };

  // Main screen: titlebar, tab strip, composer, status bar.
  await run("main", [
    { id: "titlebar left toggle", sel: '[data-titlebar-cluster="left"] [data-size="icon-titlebar"]' },
    { id: "titlebar settings", sel: 'button[aria-label="Open settings"]', w: 23, why: "w: icons touch (24px pitch) and the tab strip + can touch it" },
    { id: "titlebar right sidebar", sel: '[data-titlebar-cluster="right"] [data-size="icon-titlebar"]:last-child', w: 36, why: "w: icons touch (24px pitch); the last one grows only to the screen edge" },
    { id: "tab strip +", sel: '[data-zone-tabstrip] button[aria-label="New session tab"], [data-zone-tabstrip] button[aria-label="New tab"]', nth: -1, w: 28, h: 33, why: "w: with many tabs it touches Settings (painted on top); h: the tab strip is 34px tall and clips its children" },
    { id: "composer +", sel: 'form[data-slot="composer-root"] button[aria-label="Add context"]' },
    { id: "composer model", sel: 'form[data-slot="composer-root"] button[aria-label^="Model"]', w: 47 },
    { id: "composer effort", sel: 'form[data-slot="composer-root"] button[aria-label^="Effort"]' },
    { id: "composer voice", sel: 'form[data-slot="composer-root"] button[aria-label="Voice"], form[data-slot="composer-root"] button[aria-label="Voice dictation"]' },
    { id: "composer send/voice", sel: 'form[data-slot="composer-root"] button[type="submit"], form[data-slot="composer-root"] button[aria-label="Start voice conversation"]', w: 41, why: "w: the composer card edge clips it 7px right of the button" },
    { id: "status command center", sel: 'footer[data-slot="statusbar"] [data-android-statusbar-item="command-center"]', w: 28, h: 41, why: "w: 28px icon between the screen edge and its neighbour; h: the composer keeps the 8px above" },
    { id: "status item 2", sel: 'footer[data-slot="statusbar"] button:not([data-android-statusbar-item="command-center"])', nth: 0, h: 41, why: "h: the composer keeps the 8px above the bar" },
    { id: "status item last", sel: 'footer[data-slot="statusbar"] button:not([data-android-statusbar-item="command-center"])', nth: -1, h: 41, why: "h: the composer keeps the 8px above the bar" },
  ]);

  // Composer "+" menu: text at least 12px (F16).
  await tapBy("Add context");
  await page.waitForTimeout(500);
  report.steps.plusMenu = await page.evaluate(() => ({ items: document.querySelectorAll('[data-slot="dropdown-menu-content"] [role="menuitem"]').length, smallText: window.__smallText('[data-slot="dropdown-menu-content"]') }));
  await page.screenshot({ path: `${out}/04-plus-menu.png` });
  await closeMenu();

  // Effort menu: the Thinking switch.
  await tapBy("Effort");
  await page.waitForTimeout(500);
  await run("effort menu", [{ id: "thinking switch", sel: '[data-slot="dropdown-menu-content"] [role="switch"]', h: 39, why: "h: menu rows are 40px (39 after sub-pixel rounding); a taller area toggles from the next row" }]);
  report.steps.effortMenuSmallText = await page.evaluate(() => window.__smallText('[data-slot="dropdown-menu-content"]'));
  await closeMenu();

  // Command Center: Pin / Export / Delete icons of a session row.
  await tapBy("Open Command Center");
  await page.waitForTimeout(700);
  await run("command center", [
    { id: "row pin", sel: 'li button[title="Pin session"], li button[aria-label="Pin session"], li button[title="Unpin session"], li button[aria-label="Unpin session"]', w: 32, why: "w: grows left to the row title only" },
    { id: "row export", sel: 'li button[title="Export session"], li button[aria-label="Export session"]', w: 25, why: "w: icons are 26px apart" },
    { id: "row delete", sel: 'li button[title="Delete session"], li button[aria-label="Delete session"]', w: 24, why: "w: its right side is clipped by the row strip" },
  ]);
  await closeMenu();
  await page.waitForTimeout(400);

  // Settings breadcrumb, then the sessions drawer (footer, session rows).
  await tapBy("Open settings");
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${out}/05-settings-breadcrumb.png` });
  await run("settings", [{ id: "settings breadcrumb", sel: 'nav[aria-label] > button[data-size="inline"]', w: 47, h: 40, why: "h: the settings title row is right above it" }]);
  await closeMenu();
  await tapBy("Show sidebar");
  await page.waitForTimeout(700);
  await run("drawer", [
    { id: "drawer titlebar toggle", sel: '[data-titlebar-cluster="left"] [data-size="icon-titlebar"]', h: 39, why: "h: the open drawer's first row starts at y=34 under the toggle (40px kept there)" },
    { id: "session actions", sel: 'button[aria-label="Session actions"]', h: 40, why: "h: session rows are 41px apart" },
    { id: "reorder handle", sel: 'span[aria-label^="Reorder"]', w: 27, h: 40, why: "w: the sidebar clips 10px from its edge and the row title starts 6px right; h: rows are 41px apart" },
    { id: "footer avatar", sel: '[data-slot="profile-rail"] button:not([aria-label="New profile"]):not([aria-label^="Import profile"]):not([aria-label^="Manage profiles"]):not([aria-label^="Manage gateways"])', w: 47, h: 39, why: "h: 40px band between the session list and the status bar" },
    { id: "footer new profile", sel: '[data-slot="profile-rail"] button[aria-label="New profile"]', w: 46, h: 39, why: "h: 40px band" },
    { id: "footer import", sel: '[data-slot="profile-rail"] button[aria-label^="Import profile"]', w: 20, h: 39, why: "w: icons are 22-26px apart; h: 40px band" },
    { id: "footer manage profiles", sel: '[data-slot="profile-rail"] button[aria-label^="Manage profiles"]', w: 24, h: 36, why: "w: icons are 22-26px apart; h: a session row action area can end right above the band" },
    { id: "footer manage gateways", sel: '[data-slot="profile-rail"] button[aria-label^="Manage gateways"]', w: 24, h: 36, why: "w: icons touch the drawer edge; h: a session row action area can end right above the band" },
  ]);
  await page.keyboard.press("Escape");

  // Controls that are not on screen in the fixture: read the invisible area from their ::after rule.
  report.steps.probeAreas = await page.evaluate(() => {
    const host = document.createElement("div");
    host.innerHTML = '<button aria-label="Dismiss notification" data-size="icon-xs" type="button" style="width:24px;height:24px"></button>';
    document.body.append(host);
    const area = (el) => { const a = getComputedStyle(el, "::after"); return { w: Math.round(parseFloat(a.width)), h: Math.round(parseFloat(a.height)), pos: a.position }; };
    const dismiss = area(host.firstChild);
    host.remove();
    // A closeable tab is not always in the strip (on the phone Terminal opens as a slide-over): probe the rule then.
    let close = document.querySelector('[data-slot="pane-tab"] button[aria-label="Close"]');
    const tabHost = document.createElement("div");
    if (!close) {
      tabHost.innerHTML = '<div data-slot="pane-tab"><button aria-label="Close" type="button" style="width:24px;height:34px;position:relative"></button></div>';
      document.body.append(tabHost);
      close = tabHost.querySelector("button");
    }
    const tabClose = area(close);
    tabHost.remove();
    return { dismiss, tabClose };
  });
  expect("dismiss notification", 48, 48);
  expect("tab close", 36, 34, "h: the tab strip is 34px tall and clips its children");
  targets.push({ id: "dismiss notification", state: "probe", found: report.steps.probeAreas.dismiss.pos === "absolute", w: report.steps.probeAreas.dismiss.w, h: report.steps.probeAreas.dismiss.h });
  targets.push({ id: "tab close", state: "probe", found: !!report.steps.probeAreas.tabClose, w: report.steps.probeAreas.tabClose?.w ?? 0, h: report.steps.probeAreas.tabClose?.h ?? 0 });
  report.steps.tapTargets = targets;
  report.steps.tapExpected = expected;
} finally {
  await browser.close();
  writeFileSync(`${out}/report.json`, JSON.stringify(report, null, 2));
}
console.log(JSON.stringify(report, null, 1));
// Gates for the defects fixed in 0.3.0. Layout numbers that are Desktop design stay report-only.
const s = report.steps;
const tb = s.titlebarMany;
const plus = tb?.buttons.find((b) => b.label === "New session tab");
const gear = tb?.buttons.find((b) => b.label === "Open settings");
// Tap targets: a number under 40 is allowed only when its entry explains the physical limit ("why"); a measured area
// below its number fails.
const tapFailures = [];
for (const [id, e] of Object.entries(s.tapExpected ?? {})) {
  if ((e.w < 40 || e.h < 40) && !e.why) tapFailures.push(`tap target "${id}" allows ${e.w}x${e.h} without a reason`);
  const m = s.tapTargets?.find((t) => t.id === id);
  if (!m?.found) tapFailures.push(`tap target "${id}" not found`);
  else if (m.w < e.w || m.h < e.h) tapFailures.push(`tap target "${id}" is ${m.w}x${m.h}${m.cover ? ` (covered by ${m.cover})` : ""} [box ${m.box}], needs ${e.w}x${e.h}${e.why ? ` (${e.why})` : ""}`);
}
const failures = [
  report.errors?.length && `page errors: ${report.errors.join("; ")}`,
  (!plus || plus.r > tb.innerW || (gear && plus.r > gear.x)) && `"+" off screen or under Settings (${JSON.stringify({ plus, gear })})`,
  s.unnamed?.length && `icon-only Settings buttons without a name: ${s.unnamed.length}`,
  JSON.stringify(s.editorAttrs) !== JSON.stringify({ slot: "composer-rich-input", spellcheck: "true", autocorrect: "on", autocapitalize: "sentences", enterkeyhint: "enter" }) && `composer keyboard attributes ${JSON.stringify(s.editorAttrs)}`,
  !s.enterInsertedNewline && `Enter did not make a new line (${s.afterEnter})`,
  s.submitBeforeSend !== 0 && "Enter sent the message",
  s.submitAfterSend !== 1 && "Send did not submit exactly once",
  (s.winningRules?.statusRowGridColumn !== "3" || s.winningRules?.statusRowGridRow !== "2") && `status-row buttons are not on their own line (Desktop CSS won): ${JSON.stringify(s.winningRules)}`,
  !(s.touchAndText?.titlebarHitH >= 47) && `titlebar icon tap area is under 48dp: ${JSON.stringify(s.touchAndText)}`,
  !(s.touchAndText?.statusbarHitH >= 40) && `status bar item tap area is under 40px: ${JSON.stringify(s.touchAndText)}`,
  ...tapFailures,
  !(s.plusMenu?.items >= 3) && `composer "+" menu did not open (${JSON.stringify(s.plusMenu)})`,
  s.plusMenu?.smallText !== 0 && `composer "+" menu has text under 12px: ${s.plusMenu?.smallText} nodes`,
  s.effortMenuSmallText !== 0 && `effort menu has text under 12px: ${s.effortMenuSmallText} nodes`,
  s.touchAndText?.smallTextNodes !== 0 && `text under 12px on the phone screen: ${s.touchAndText?.smallTextNodes} nodes`,
  (s.winningRules?.replyActionW !== 32 || s.winningRules?.replyActionH !== 32) && `reply action buttons are not 32px (Desktop CSS won): ${JSON.stringify(s.winningRules)}`,
].filter(Boolean);
console.log(failures.length ? `FAIL\n${failures.join("\n")}` : "PASS: phone audit gates");
process.exitCode = failures.length ? 1 : 0;
