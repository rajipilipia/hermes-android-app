// Layout-only matrix. Synthetic REST/socket fixtures, never real sends or auth.
// Browser: DESKTOP_TEST_ORIGIN=... node tests/browser/single-screen-layout.mjs <out>
// Emulator: ANDROID_LAYOUT_CDP=http://127.0.0.1:9344 ANDROID_LAYOUT_ADB=<adb.exe>
//          (owned server 5041 / exact emulator-6000; never the physical phone).
import { chromium } from "@playwright/test";
import { _android } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { openPage, configureLayoutFixture } from "./mobile-layout.mjs";
import { bootApkLayoutFixture } from "./android-layout-bootstrap.mjs";
const out = process.argv[2] ?? ".cache/three-fixes-20261021/layout";
mkdirSync(out, { recursive: true });
const emulator = process.env.ANDROID_LAYOUT_CDP;
const adb = process.env.ANDROID_LAYOUT_ADB;
const target = ["-H", "127.0.0.1", "-P", "5041", "-s", "emulator-6000"];
const device = (...args) => execFileSync(adb, [...target, ...args], { timeout: 30000, maxBuffer: 16 * 1024 * 1024 });
const sizes = [
  [320, 640], [360, 640], [375, 812], [393, 852], [412, 915], [443, 976], [480, 960], [600, 960],
  [320, 480], [639, 900], [640, 900], [640, 360], [852, 393], [976, 443], [851, 850], [884, 1104],
];
const results = [];
const browser = emulator ? null : await chromium.launch({ channel: "msedge", headless: true });
let nativePage, nativeState, androidDevice, nativeFixture, nativeBoundsCache;
if (emulator) {
  androidDevice = (await _android.devices({host:"127.0.0.1",port:5041,omitDriverInstall:true})).find(d=>d.serial()==="emulator-6000");
  if (!androidDevice) throw new Error("Owned emulator is missing");
  nativePage = await (await androidDevice.webView({pkg:"us.pilipia.hermes.prototype"})).page();
  if (!nativePage) throw new Error("No emulator WebView target");
  nativePage.on("dialog", dialog=>dialog.dismiss().catch(()=>{}));
  nativeState = await nativePage.evaluate(() => ({ storage: { ...localStorage }, url: location.href }));
  nativeFixture = await configureLayoutFixture(nativePage, { multiProfile: true });
  // Reset before the original APK entry runs. Clearing after rendering races
  // persisted stores; the hash also otherwise reopens the prior settings modal.
  await nativePage.addInitScript(() => {
    localStorage.clear();
    history.replaceState(null, '', location.pathname + '#/');
  });
  nativePage.setDefaultTimeout(10000);
}
async function tap(locator, native = true) {
  if (!emulator) return locator.tap();
  await locator.waitFor({state:"visible",timeout:10000});
  await locator.evaluate(el=>el.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'}));
  await locator.page().evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const box = await locator.boundingBox();
  if (!box) throw new Error("Touch target has no bounds");
  // Long labels extend outside their clipped row. Native input must hit the
  // visible intersection, not the midpoint of invisible marquee text.
  const point = await locator.evaluate(el=>{
    const r=el.getBoundingClientRect();
    let left=Math.max(0,r.left),right=Math.min(innerWidth,r.right),top=Math.max(0,r.top),bottom=Math.min(innerHeight,r.bottom);
    for(let p=el.parentElement;p;p=p.parentElement){
      const c=getComputedStyle(p),b=p.getBoundingClientRect();
      if(/hidden|clip|auto|scroll/.test(c.overflowX)){left=Math.max(left,b.left);right=Math.min(right,b.right);}
      if(/hidden|clip|auto|scroll/.test(c.overflowY)){top=Math.max(top,b.top);bottom=Math.min(bottom,b.bottom);}
    }
    if(right<=left || bottom<=top) return null;
    const x=(left+right)/2,y=(top+bottom)/2,h=document.elementFromPoint(x,y);
    return {x,y,hit:h===el || el.contains(h)};
  });
  if(!point?.hit) throw new Error('Native touch target has no uncovered visible point');
  if (native) {
    const viewport = await locator.page().evaluate(()=>({width:innerWidth,height:innerHeight}));
    if (nativeBoundsCache?.width!==viewport.width || nativeBoundsCache?.height!==viewport.height) {
      device('shell','uiautomator','dump','/sdcard/hermes-layout-ui.xml');
      const xml = device('shell','cat','/sdcard/hermes-layout-ui.xml').toString();
      const node = xml.match(/<node[^>]*class="android.webkit.WebView"[^>]*>/)?.[0];
      const bounds = node?.match(/bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"/);
      if (!bounds) throw new Error('Foreground native WebView bounds unavailable');
      const [,left,top,right] = bounds.map(Number);
      nativeBoundsCache={...viewport,left,top,right};
    }
    const {left,top,right}=nativeBoundsCache;
    const scale = (right-left)/viewport.width;
    device('shell','input','tap',String(Math.round(left+point.x*scale)),String(Math.round(top+point.y*scale)));
    return;
  }
  const cdp = await locator.page().context().newCDPSession(locator.page());
  try {
    await cdp.send("Input.dispatchTouchEvent", {type:"touchStart",touchPoints:[{x:box.x+box.width/2,y:box.y+box.height/2}]});
    await cdp.send("Input.dispatchTouchEvent", {type:"touchEnd",touchPoints:[]});
  } finally { await cdp.detach(); }
}
async function measure(page, name, report) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(200);
  const value = await page.evaluate(() => {
    const visible = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !e.closest("[inert]"); };
    const box = e => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height, right: r.right, bottom: r.bottom }; };
    const controls = [...document.querySelectorAll('form[data-slot="composer-root"] button')].filter(visible)
      .map(e => ({ name: e.getAttribute("aria-label") || e.dataset.testid || e.textContent.slice(0, 20), ...box(e) }));
    const surfaces = [...document.querySelectorAll('[role="dialog"], [role="menu"], [data-slot="popover-content"], [data-narrow-overlay], [data-overlay-surface]')].filter(visible)
      .map(e => ({ name: e.getAttribute("role") || e.dataset.slot || "sidebar", ...box(e) }));
    const composer = [...document.querySelectorAll('form[data-slot="composer-root"]')].find(visible);
    const headerControls = [...document.querySelectorAll('button[aria-label="New session tab"], button[aria-label="Open settings"], button[aria-label="Show sidebar"]')].filter(visible).map(e => ({name:e.getAttribute('aria-label'), ...box(e)}));
    const overlaps = [];
    for (let i=0;i<controls.length;i++) for(let j=i+1;j<controls.length;j++) {
      const a=controls[i],b=controls[j];
      if (Math.min(a.right,b.right)-Math.max(a.x,b.x)>2 && Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y)>2) overlaps.push(`${a.name}/${b.name}`);
    }
    return { width: innerWidth, height: innerHeight, screen: [screen.width, screen.height], compact: document.documentElement.hasAttribute("data-android-compact"), headerControls, overlaps,
      scrollWidth: document.documentElement.scrollWidth, controls, surfaces, composer: composer ? box(composer) : null };
  });
  const failures = [];
  if (value.scrollWidth > value.width + 1) failures.push("document horizontal overflow");
  if (name === 'home') {
    const [requestedWidth, requestedHeight] = report.name.split('x').map(Number);
    if (Math.abs(value.width-requestedWidth)>1) failures.push('actual viewport differs from requested emulator width');
    if (value.compact !== (Math.min(requestedWidth, requestedHeight)<640)) failures.push('compact/unfolded classification mismatch');
  }
  if (['chat','keyboard','keyboard-long-draft','keyboard-dismissed','large-chat-text'].includes(name) && (!value.composer || value.controls.length<4)) failures.push('composer controls missing');
  if (['reasoning','models','composer-menu','profiles','settings'].includes(name) && !value.surfaces.length) failures.push('expected open surface missing');
  failures.push(...value.overlaps.map(x=>`overlapping composer controls: ${x}`));
  for (const e of [...value.controls, ...value.surfaces, ...value.headerControls]) {
    if (e.x < -1 || e.right > value.width + 1) failures.push(`${e.name}: horizontal clip`);
    if (e.y < -1 || e.bottom > value.height + 2) failures.push(`${e.name}: vertical clip`);
  }
  if (value.composer && name.startsWith("keyboard") && value.composer.bottom > value.height + 2) failures.push("composer behind keyboard");
  report.checks.push({ name, ...value, failures });
  writeFileSync(`${out}/results.json`, JSON.stringify(results, null, 2));
  if (emulator) writeFileSync(`${out}/${report.name}-${name}.png`, device("exec-out", "screencap", "-p"));
  else await page.screenshot({ path: `${out}/${report.name}-${name}.png` });
}
async function closeLayers(page) {
  const overlayClose = page.locator('[data-overlay-surface] button[aria-label="Close"]');
  if (await overlayClose.isVisible()) await overlayClose.click();
  for (let i = 0; i < 3; i++) await page.keyboard.press("Escape");
  await page.evaluate(() => document.activeElement?.blur?.());
  if (emulator) {
    const ime = device("shell", "dumpsys", "input_method").toString();
    // Never Back: the IME flag can lag blur, causing Back to finish Activity.
    if (/mInputShown=true|isInputViewShown=true/.test(ime)) device("shell", "input", "keyevent", "111");
    await page.waitForTimeout(250);
  }
}
try {
  for (const [width, height] of sizes) {
    if (process.env.ONLY && !process.env.ONLY.split(",").includes(`${width}x${height}`)) continue;
    const r = { name: `${width}x${height}`, platform: emulator ? "Android emulator WebView" : "desktop Chromium touch viewport", checks: [], errors: [] };
    results.push(r);
    let page, context;
    try {
      if (emulator) {
        // Real emulator display changes, not a desktop viewport pretending to be Android.
        device("shell", "wm", "size", `${width * 2}x${height * 2}`);
        device("shell", "wm", "density", "320");
        device('shell','am','start','-n','us.pilipia.hermes.prototype/.MainActivity');
        nativeBoundsCache=undefined;
        page = nativePage;
        // Independent synthetic cases: never hydrate a stored row from an older
        // incomplete fixture. Restore the emulator's original preferences below.
        await page.evaluate(() => localStorage.clear());
        await page.reload({ waitUntil: "networkidle", timeout: 60000 });
        await page.waitForFunction(w=>Math.abs(innerWidth-w)<=1,width,{timeout:15000});
        await bootApkLayoutFixture(page, process.env.ANDROID_LAYOUT_ASSETS);
      } else {
        ({ page, context, errors: r.errors } = await openPage(browser, { name: r.name, width, height, dpr: 2 }, { detailed: true }));
      }
      await page.locator("[data-contrib-shell]").waitFor({ timeout: 60000 });
      const settingsButton = page.getByRole('button', {name:'Open settings',exact:true});
      if (!(await settingsButton.isVisible())) r.errors.push('Top Settings entry hidden with keyboard closed');
      await measure(page, "home", r);
      const sidebar = page.getByRole("button", { name: "Show sidebar", exact: true });
      if (await sidebar.count()) await tap(sidebar);
      const sessionRow = page.locator('[data-sessions-mode]').getByText("Englewood Q3 estimate review", { exact: false }).first();
      await sessionRow.scrollIntoViewIfNeeded();
      await measure(page, "sidebar", r);
      const profile = page.locator('[data-slot="profile-dropdown"], [data-slot="profile-switcher"] button').first();
      if (await profile.isVisible()) {
        await tap(profile);
        await page.getByRole('menu').first().waitFor();
        await measure(page, 'profiles', r);
        await page.getByRole('menu').locator('[role="menuitemradio"]').last().scrollIntoViewIfNeeded();
        await measure(page, 'profiles-scrolled', r);
        await closeLayers(page);
      } else {
        const rail = page.locator('[data-slot="profile-rail"]');
        r.profilePicker = await rail.isVisible() ? 'Horizontal profile rail' : 'Profile rail missing';
        if (!(await rail.isVisible())) r.errors.push('Profile controls missing');
      }
      // Fixture navigation, not a touch-gesture acceptance test.
      if (!(await sessionRow.isVisible()) && await sidebar.isVisible()) await tap(sidebar);
      await tap(sessionRow);
      await page.getByText("Q3 summary", { exact: false }).first().waitFor({ timeout: 20000 });
      await measure(page, "chat", r);
      if (process.env.EXTRA_EDGES) {
        await page.locator('pre').first().scrollIntoViewIfNeeded();
        await measure(page,'rich-code-content',r);
        await page.locator('table').first().scrollIntoViewIfNeeded();
        await measure(page,'rich-table-content',r);
      }
      const reasoning = page.locator('[data-testid="reasoning-pill"]:visible').first();
      if (width < 640 && !(await reasoning.isVisible())) throw new Error("Reasoning entry point missing on compact screen");
      if (await reasoning.isVisible()) {
        await tap(reasoning);
        await page.getByRole("menu").first().waitFor();
        await measure(page, "reasoning", r);
        await closeLayers(page);
      }
      const model = page.locator('form[data-slot="composer-root"] button[aria-label^="Model"]').first();
      await tap(model);
      await page.getByRole("menu").first().waitFor();
      await measure(page, "models", r);
      await closeLayers(page);
      await tap(page.getByRole("button", { name: "Add context", exact: true }));
      await page.getByRole("menu").first().waitFor();
      await measure(page, "composer-menu", r);
      await closeLayers(page);
      const editor = page.locator('[data-slot="composer-rich-input"]:visible').first();
      await tap(editor, true);
      await editor.fill("Layout-only draft. Never send.\nLong line for wrapping: " + "sample-word ".repeat(40));
      if (emulator) {
        for (let attempt=0;attempt<10;attempt++) {
          r.keyboardShown = /mInputShown=true|isInputViewShown=true/.test(device("shell","dumpsys","input_method").toString());
          if (r.keyboardShown) break;
          await page.waitForTimeout(250);
        }
        if (!r.keyboardShown) r.errors.push("Native keyboard did not open; keyboard layout is unverified");
      }
      if (!emulator) await page.setViewportSize({ width, height: Math.max(160, Math.round(height * .55)) });
      await measure(page, "keyboard", r);
      await editor.fill('ქართულად — English — العربية 😀\n' + 'UnbrokenToken'.repeat(100) + '\n' + 'Long draft line\n'.repeat(80));
      await measure(page, 'keyboard-long-draft', r);
      await editor.fill("");
      await closeLayers(page);
      if (!emulator) await page.setViewportSize({ width, height });
      await measure(page, 'keyboard-dismissed', r);
      await page.evaluate(() => document.documentElement.style.setProperty('--chat-text-scale','1.75'));
      await measure(page, 'large-chat-text', r);
      await page.evaluate(() => document.documentElement.style.removeProperty('--chat-text-scale'));
      if (process.env.EXTRA_EDGES) {
        const plus = page.getByRole('button',{name:'New session tab',exact:true});
        if (await plus.isVisible()) {
          await editor.fill('Retained draft — ქართულად 😀');
          await closeLayers(page);
          const effort = await reasoning.innerText();
          const oldCount = await page.locator('[data-tree-tab]').count();
          await tap(plus);
          await page.waitForFunction(count=>document.querySelectorAll('[data-tree-tab]').length>count,oldCount);
          if ((await editor.innerText()).trim()) r.errors.push('New tab did not start with a blank draft');
          if (await reasoning.innerText() !== effort) r.errors.push('New tab did not retain reasoning selection');
          await measure(page,'new-tab',r);
          for (let n=0;n<4;n++) await tap(plus);
          await measure(page,'many-tabs',r);
          const priorTab = page.locator('[data-tree-tab]').filter({hasText:'Englewood Q3 estimate review'}).first();
          await tap(priorTab);
          await page.waitForFunction(()=>document.querySelector('[data-slot="composer-rich-input"]')?.textContent.includes('Retained draft'));
          await measure(page,'retained-tab-draft',r);
          await editor.fill('');
        } else r.errors.push('New-tab entry unavailable for tab edge tests');
      }
      if (await settingsButton.isVisible()) await tap(settingsButton);
      else {
        r.settingsNavigation = 'Fixture route fallback; touch entry remains a failure';
        await page.evaluate(()=>location.hash='#/settings');
      }
      await page.locator('[data-overlay-surface]').waitFor();
      await page.waitForFunction(() => !document.querySelector('[data-overlay-surface] .animate-pulse'));
      await measure(page, "settings", r);
      await closeLayers(page);
      await page.locator('[data-overlay-surface]').waitFor({state:'hidden'});
      await page.keyboard.press("Control+Shift+L");
      await page.locator('[data-pane-host^="preview-tile:"]:not([inert])').waitFor({ timeout: 10000 });
      await page.locator('[data-pane-host^="preview-tile:"]:not([inert]) input[inputmode="url"]').waitFor();
      await measure(page, "browser-pane", r);
      await closeLayers(page);
      if (width >= 640 && height >= 640) {
        // Wide layout must be identical with the new stylesheet enabled/disabled.
        r.wideUntouched = await page.evaluate(() => {
          const shapes = () => [...document.querySelectorAll('[data-slot="composer-root"],[data-zone-tabstrip],[data-slot="sidebar"]')]
            .map(e => { const r = e.getBoundingClientRect(); return [r.x,r.y,r.width,r.height,getComputedStyle(e).fontSize]; });
          const rules = [...document.styleSheets].filter(s => { try { return [...s.cssRules].some(r => r.cssText.includes("data-android-compact")); } catch { return false; } });
          const before = shapes();
          // Disable only the compact rules, never an entire combined production CSS file.
          const compactRules = [];
          for (const sheet of rules) for (let i=sheet.cssRules.length-1;i>=0;i--) if (sheet.cssRules[i].cssText.includes("data-android-compact")) {
            compactRules.push([sheet,i,sheet.cssRules[i].cssText]);sheet.deleteRule(i);
          }
          const after = shapes();
          for (const [sheet,i,rule] of compactRules.reverse()) sheet.insertRule(rule,i);
          return !document.documentElement.hasAttribute("data-android-compact") && JSON.stringify(before) === JSON.stringify(after);
        });
      }
    } catch (e) {
      r.errors.push(e.message);
      if (page) r.failureText = (await page.locator('body').innerText()).slice(0,1800);
      if (nativeFixture) r.fixtureCalls = nativeFixture.calls.slice(-40);
      if (emulator) writeFileSync(`${out}/${r.name}-failure.png`,device('exec-out','screencap','-p'));
    }
    finally { if (context) await context.close(); }
    writeFileSync(`${out}/results.json`, JSON.stringify(results, null, 2));
    console.log(JSON.stringify({ size: r.name, checks: r.checks.length, failures: r.checks.flatMap(c => c.failures).length, errors: r.errors, wideUntouched: r.wideUntouched }));
  }
} finally {
  if (emulator) {
    await nativePage.evaluate(state => { localStorage.clear(); for (const [k,v] of Object.entries(state.storage)) localStorage.setItem(k,v); history.replaceState(null,'',state.url); }, nativeState).catch(() => {});
    device("shell", "wm", "size", "reset"); device("shell", "wm", "density", "reset");
  }
  if (androidDevice) await androidDevice.close();
  if (browser) await browser.close();
}
const failed = results.some(r => r.errors.length || r.checks.some(c => c.failures.length) || r.wideUntouched === false);
console.log(JSON.stringify({ cases: results.length, checks: results.reduce((n,r)=>n+r.checks.length,0), failed, report: `${out}/results.json` }));
process.exitCode = failed ? 1 : 0;
