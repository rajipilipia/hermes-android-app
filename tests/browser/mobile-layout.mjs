// TEST ONLY. Drives the real production renderer in a phone-sized Chromium against a
// synthetic wire peer. It proves layout and touch behavior of the web layer, not the
// Android WebView, IME, insets or any live Hermes backend.
//   DESKTOP_TEST_ORIGIN=http://127.0.0.1:18767 node tests/browser/mobile-layout.mjs [outDir]
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
const origin = process.env.DESKTOP_TEST_ORIGIN ?? "http://127.0.0.1:18767";
const out = process.argv[2] ?? ".cache/mobile-layout/run";
mkdirSync(out, { recursive: true });

export const VIEWPORTS = [
  { name: "narrow-320x640", width: 320, height: 640, dpr: 3 },
  { name: "small-360x640", width: 360, height: 640, dpr: 3 },
  { name: "phone-393x852", width: 393, height: 852, dpr: 3 },
  { name: "tall-412x915", width: 412, height: 915, dpr: 2.6 },
  { name: "landscape-852x393", width: 852, height: 393, dpr: 3 },
  { name: "fold-inner-884x1104", width: 884, height: 1104, dpr: 2.2 },
];
const only = process.env.ONLY?.split(",");

const MESSAGES = [
  { role: "user", text: "Summarize the Q3 estimate for the Englewood project and list the open RFIs." },
  {
    role: "assistant",
    text:
      "Here is the **Q3 summary**. The total is $1,284,500 across 14 divisions.\n\n" +
      "| Division | Budget | Variance |\n|---|---:|---:|\n| 03 Concrete | $212,400 | +$4,100 |\n| 05 Metals | $338,900 | -$2,250 |\n| 09 Finishes | $96,300 | +$800 |\n\n" +
      "```ts\nexport function variance(budget: number, actual: number): number {\n  return Math.round((actual - budget) * 100) / 100;\n}\n```\n\n" +
      "Open RFIs:\n\n1. RFI-014 slab edge detail at the east stair\n2. RFI-019 door hardware set 4 conflicts with schedule\n3. RFI-022 curtain wall anchor spacing\n\n" +
      "A very long unbroken token to test wrapping: https://example.com/a/really/long/path/that/keeps/going/and/going/and/going/forever/and/ever/index.html",
  },
  { role: "user", text: "Thanks. Draft an email to the GC about RFI-019." },
  { role: "assistant", text: "Sure. Here is a short draft:\n\n> Hi team, RFI-019 shows door hardware set 4 conflicting with the schedule. Please confirm the intended set by Friday.\n\nWant me to add the drawing references?" },
];

const sessions = Array.from({ length: 12 }, (_, i) => ({
  id: `stored-${i + 1}`,
  title: i === 0 ? "Englewood Q3 estimate review with a deliberately long title" : `Conversation ${i + 1}`,
  preview: "Summarize the Q3 estimate",
  message_count: 4,
  started_at: 1_790_000_000 - i * 3600,
  last_active: 1_790_000_000 - i * 3600,
  source: "desktop",
  model: "synthetic/test",
}));

/** Hermes's own REST (what the native HermesApi bridge returns), synthetic fixtures. */
const layoutProfiles = (multi) => [{ name: "default", is_active: true, is_default: true },
  ...(multi ? Array.from({ length: Number(process.env.LAYOUT_PROFILE_COUNT ?? 10) - 1 }, (_, i) => ({ name: `layout-profile-${i + 1}-long-name`, is_active: false, is_default: false })) : [])];
export function restReply(params, calls = [], multiProfile = false) {
  const op = params.operation;
  calls.push(op);
  if (op === "GET /api/profiles/active") return { status: 200, body: { active: "default", current: "default" } };
  const body =
    op === "GET /api/profiles" ? { profiles: layoutProfiles(multiProfile), active_profile: "default" }
    : op === "GET /api/config" ? { display: { language: "en", skin: "nous" }, agent: { max_turns: 90 }, compression: { enabled: true } }
    : op === "GET /api/config/schema" ? { fields: {} }
    : op === "GET /api/config/defaults" ? {}
    : op === "GET /api/model/options" ? { providers: [], current: { model: "gpt-5", provider: "openai" } }
    : op === "GET /api/model/auxiliary" ? { main: { model: "gpt-5", provider: "openai" }, tasks: [] }
    : op === "GET /api/model/moa" ? { enabled: false, presets: {}, default_preset: "", active_preset: "", reference_models: [], aggregator: { model: "gpt-5", provider: "openai" } }
    : op === "GET /api/sessions" || op === "GET /api/profiles/sessions" ? { sessions, total: sessions.length, has_more: false }
    : op === "GET /api/profiles/sessions/sidebar" ? { recents: { sessions: sessions.map((r) => ({ ...r, profile: "default" })), profiles_truncated: { default: false }, profiles_usage: {} }, cron: { sessions: [], total: 0 }, messaging: { sessions: [], total: 0 }, errors: [], storage: {} }
    : op === "GET /api/sessions/{session_id}" ? { ...(sessions.find(s => s.id === params.pathParams?.session_id) ?? sessions[0]), profile: "default" }
    : op === "GET /api/sessions/{session_id}/messages" ? { session_id: params.pathParams?.session_id ?? "stored-1", profile: "default", messages: MESSAGES.map((m) => ({ role: m.role, content: m.text })), pagination: { limit: 120, offset: 0, order: "latest", has_more: false } }
    : op === "GET /api/model/info" ? { model: "synthetic/test", provider: "test", context_length: 32768 }
    : op === "GET /api/cron/jobs" ? { jobs: [] }
    : op === "GET /api/skills" ? { skills: [] }
    : op === "GET /api/tools/terminal/backends" ? { backends: [] }
    : op === "GET /api/mcp/servers" ? { servers: [] }
    : op === "GET /api/tools/toolsets" ? { toolsets: [] }
    : {};
  return { status: 200, body };
}

function peerFor(calls, detailed = false, multiProfile = false) {
  return (ws) => {
    let created = 0;
    ws.onMessage((text) => {
      const frame = JSON.parse(String(text));
      if (!frame.method || frame.id == null) return;
      calls.push(frame.method);
      let result = {};
      // Native only: Desktop features use Hermes's REST (window.HermesApi), never a PC add-on RPC.
      if (frame.method.startsWith("desktop.")) calls.push(`UNEXPECTED ${frame.method}`);
      else if (frame.method === "session.list") result = { sessions, total: sessions.length, has_more: false };
      else if (frame.method === "profiles.list") result = { profiles: layoutProfiles(multiProfile), active_profile: "default" };
      else if (frame.method === "commands.catalog") result = { commands: [{ name: "help", description: "Help", desktop: "client" }] };
      else if (frame.method === "session.events.since") result = { events: [], count: 0, latest_seq: 0, epoch: "synthetic", open_requests: [] };
      else if (frame.method === "setup.status") result = { provider_configured: true, ready: true };
      else if (frame.method === "setup.runtime_check") result = { ok: true, model: "synthetic/test", provider: "test" };
      else if (frame.method === "model.options") result = { providers: [], current: { model: detailed ? "gpt-5" : "synthetic/test", provider: detailed ? "openai" : "test" } };
      else if (frame.method === "session.active_list") result = { sessions: [] };
      else if (frame.method === "onboarding.state") result = { eligible: false, run: false, run_id: null, session_id: null };
      else if (frame.method === "i18n.languages") result = { languages: [] };
      else if (frame.method === "i18n.catalog") result = { locale: "en", messages: {} };
      else if (frame.method === "free_tier.status") result = { enabled: false, notice_pending: false };
      else if (frame.method === "models.list") result = { models: [] };
      else if (frame.method === "session.resume")
        result = { session_id: "runtime-1", stored_session_id: frame.params?.session_id ?? "stored-1", messages: MESSAGES, message_count: MESSAGES.length, info: { desktop_contract: 8 }, running: false };
      else if (frame.method === "session.history") result = { count: MESSAGES.length, messages: MESSAGES };
      if (detailed && frame.method === "session.resume") Object.assign(result.info, { model: "gpt-5", provider: "openai", reasoning_effort: "high" });
      if (detailed && frame.method === "session.control.read") result = {control:{goal:null,loop:null,heartbeat:null,revision:"layout-fixture",updated_at:1790000000}};
      if (detailed && frame.method === "session.create") result = {
        session_id: `runtime-new-${++created}`, stored_session_id: `stored-new-${created}`, messages: [],
        info: { desktop_contract: 8, model: frame.params.model ?? "gpt-5", provider: frame.params.provider ?? "openai", reasoning_effort: frame.params.reasoning_effort ?? "high" },
      };
      ws.send(JSON.stringify({ jsonrpc: "2.0", id: frame.id, result }));
    });
  };
}

export async function openPage(browser, vp, { dark = false, detailed = false } = {}) {
  const context = await browser.newContext({
    viewport: { width: vp.width, height: vp.height },
    deviceScaleFactor: vp.dpr,
    isMobile: true,
    hasTouch: true,
    colorScheme: dark ? "dark" : "light",
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  const { errors, calls } = await configureLayoutFixture(page, { detailed });
  await page.goto(origin, { waitUntil: "networkidle" });
  await page.locator("[data-contrib-shell]").waitFor({ timeout: 60000 }).catch(async (e) => {
    await page.screenshot({ path: `${out}/FAILED-${vp.name}.png` });
    console.log((await page.locator("body").innerText()).slice(0, 400), errors);
    throw e;
  });
  if (process.env.CSS) await page.addStyleTag({ path: process.env.CSS });
  return { context, page, errors, calls };
}

// Also used against the installed APK's WebView on the isolated emulator. Only
// synthetic layout data: no provider request, sign-in, real chat or paid call.
export async function configureLayoutFixture(page, { detailed = true, multiProfile = false } = {}) {
  const errors = [];
  const calls = [];
  page.on("pageerror", (e) => errors.push(e.message));
  if (process.env.DEBUG) page.on("console", (m) => m.type() === "error" && console.log("console.error:", m.text().slice(0, 300)));
  // Native HermesApi bridge: Hermes's own REST, answered from the fixtures above.
  await page.exposeFunction("__hermesRestFixture", (request) => restReply(JSON.parse(request), calls, multiProfile));
  await page.addInitScript(() => {
    window.HermesApi = {
      call(id, request) {
        window.__hermesRestFixture(request).then((reply) =>
          window.__hermesApiResult?.(id, true, JSON.stringify({ status: reply.status, body: JSON.stringify(reply.body) })));
      },
    };
  });
  await page.addInitScript(() => {
    // Fake native browser pane (R1 stage 1): records guest requests and plays back the events a
    // real BrowserPane sends for a load, so Desktop's real pane can be driven end to end.
    window.__guestOps = [];
    window.HermesBrowser = {
      request(id, operation, value) {
        const payload = operation === "guest" ? JSON.parse(value) : { op: operation, url: value };
        window.__guestOps.push(payload);
        setTimeout(() => {
          window.__hermesBrowserResult?.(id, true, "");
          if (payload.op === "load") {
            const detail = (extra) => JSON.stringify({ pageUrl: payload.url, pageTitle: "Example", canGoBack: false, canGoForward: false, ...extra });
            window.__hermesGuestEvent?.(payload.guest, "did-start-loading", detail({}));
            window.__hermesGuestEvent?.(payload.guest, "did-navigate", detail({ url: payload.url }));
            window.__hermesGuestEvent?.(payload.guest, "dom-ready", detail({}));
            window.__hermesGuestEvent?.(payload.guest, "page-title-updated", detail({}));
            window.__hermesGuestEvent?.(payload.guest, "did-stop-loading", detail({}));
          }
        }, 10);
      },
    };
    window.HermesPc = {
      request(id, operation) {
        queueMicrotask(() => window.__hermesPcResult?.(id, true, operation === "ticket" ? "synthetic-test-ticket" : ""));
      },
    };
    // Record every focus that lands on a text field, by any path, with its inputmode at that
    // moment. A field focused without inputmode="none" would raise the IME on a phone.
    window.__focusLog = [];
    document.addEventListener(
      "focusin",
      (e) => {
        const el = e.target;
        // Read inputmode after every other focus handler ran (the app may set it during focusin).
        if (el instanceof HTMLElement && el.matches("textarea,input,[contenteditable]:not([contenteditable=false])"))
          queueMicrotask(() => window.__focusLog.push({ tag: el.tagName, slot: el.dataset?.slot ?? "", mode: el.getAttribute("inputmode") ?? "", t: Math.round(performance.now()) }));
      },
      true,
    );
  });
  if (process.env.NOGUARD)
    // Negative control: make installMobile() see a mouse device so the keyboard guard stays off.
    await page.addInitScript(() => {
      const real = window.matchMedia.bind(window);
      window.matchMedia = (q) => (String(q).includes("any-pointer") ? { ...real("not all"), matches: false, media: q } : real(q));
    });
  // The app dials its own page origin (the chosen server) since native gateways phase 1.
  await page.routeWebSocket(/\/api\/ws(\?|$)/, peerFor(calls, detailed, multiProfile));
  return { errors, calls };
}

async function shot(page, vp, name) {
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${out}/${vp.name}-${name}.png` });
}
const overflowOf = (page) =>
  page.evaluate(() => {
    const w = innerWidth;
    const wide = [...document.querySelectorAll("body *")]
      .filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && (r.right > w + 1 || r.left < -1) && getComputedStyle(e).position !== "fixed"; })
      .slice(0, 8)
      .map((e) => `${e.tagName}.${String(e.className).slice(0, 60)} ${Math.round(e.getBoundingClientRect().left)}..${Math.round(e.getBoundingClientRect().right)}`);
    return { scrollW: document.documentElement.scrollWidth, innerW: w, wide };
  });

// Counts focus() calls on text fields that were NOT keyboard-less (inputmode="none").
// Each one would raise the on-screen keyboard on a phone.
const keyboardRaisers = (page, since) =>
  page.evaluate((n) => window.__focusLog.slice(n).filter((f) => f.mode !== "none"), since);

export async function scenario(browser, vp, opts = {}) {
  const { context, page, errors, calls } = await openPage(browser, vp, opts);
  const r = { vp: vp.name, dark: !!opts.dark, errors, steps: {}, keyboard: {} };
  Object.defineProperty(r, "calls", { value: calls, enumerable: false }); // Gate only, not in the report.
  const tag = opts.dark ? "dark-" : "";
  const name = (n) => tag + n;
  await shot(page, vp, name("1-home"));
  r.steps.home = await overflowOf(page);
  r.steps.titlebar = await page.evaluate(() => ({
    headerH: Math.round(document.querySelector("[data-panel-header]")?.getBoundingClientRect().height ?? -1),
    // "+" must end before the fixed right buttons start, or it is hidden under them.
    plusRight: Math.round(document.querySelector('button[aria-label="New session tab"]')?.getBoundingClientRect().right ?? -1),
    clusterLeft: Math.round(document.querySelector('[data-titlebar-cluster="right"]')?.getBoundingClientRect().left ?? -1),
  }));
  // Replica of the upstream "Share with Nous ... Details" bar (same classes and slots) to check its fit.
  r.steps.butterbar = await page.evaluate(() => {
    const bar = document.createElement("div");
    bar.className = "grid h-6 shrink-0 grid-cols-[1fr_minmax(0,max-content)_1fr] items-center gap-2 px-2.5 text-[0.6875rem] leading-4";
    bar.dataset.slot = "butterbar"; bar.dataset.tone = "info"; bar.dataset.variant = "soft";
    bar.innerHTML = '<span aria-hidden></span><div class="flex min-w-0 items-center justify-center gap-1.5"><div class="min-w-0 truncate">Share with Nous to help improve Hermes. <a href="#" id="bb-details">Details</a></div></div><div class="flex min-w-0 items-center justify-end gap-1"><button id="bb-close" class="size-5">x</button></div>';
    document.querySelector("[data-slot=sidebar-wrapper]").prepend(bar);
    const d = document.getElementById("bb-details").getBoundingClientRect(), c = document.getElementById("bb-close").getBoundingClientRect();
    const out = { detailsRight: Math.round(d.right), closeRight: Math.round(c.right), innerW: innerWidth, barH: Math.round(bar.getBoundingClientRect().height) };
    bar.remove();
    return out;
  });
  // Composer row: every control on one vertical center, thumb-sized on touch.
  r.steps.composerRow = await page.evaluate(() => {
    const sel = ['button[aria-label="Add context"]', 'button[aria-label^="Model"]', 'button[aria-label="Voice dictation"]', 'form[data-slot="composer-root"] button[type="submit"], button[aria-label="Start voice conversation"]'];
    const rects = sel.map((q) => document.querySelector(`form[data-slot="composer-root"] ${q.includes("form[") ? "" : ""}${q}`)?.getBoundingClientRect()).filter((r) => r && r.width);
    const cys = rects.map((r) => r.top + r.height / 2);
    return { count: rects.length, spread: Math.round((Math.max(...cys) - Math.min(...cys)) * 10) / 10, minSize: Math.round(Math.min(...rects.map((r) => Math.min(r.width, r.height)))) };
  });
  // Replica of the upstream composer status row used by the "Share usage stats?" consent strip
  // (same slots and classes as components/chat/status-row.tsx and consent-strip.tsx).
  r.steps.statusRow = await page.evaluate(() => {
    const stack = document.createElement("div");
    stack.dataset.slot = "composer-status-stack";
    stack.style.cssText = "position:fixed;left:0;right:0;bottom:120px;z-index:99";
    stack.innerHTML = '<div class="group/status-row status-row flex min-h-6 items-center gap-2 rounded-md px-1.5 py-1" data-slot="status-row" data-status-icon=""><span class="status-row-icon flex size-3.5 shrink-0 items-center justify-center">*</span><div class="status-row-content flex min-w-0 flex-1 items-center gap-2"><span class="min-w-0 truncate text-[0.73rem] leading-4"><span class="font-medium">Share usage stats?</span> Counts only. Never your messages or files.</span></div><div class="status-row-actions flex shrink-0 items-center gap-0.5"><button>Share with Nous</button><button>Keep on this computer</button><button>No thanks</button><button id="sr-details">Details</button></div></div>';
    document.body.append(stack);
    const btns = [...stack.querySelectorAll("button")].map((b) => b.getBoundingClientRect());
    const out = { maxRight: Math.round(Math.max(...btns.map((b) => b.right))), minLeft: Math.round(Math.min(...btns.map((b) => b.left))), innerW: innerWidth, rowH: Math.round(stack.firstElementChild.getBoundingClientRect().height) };
    stack.remove();
    return out;
  });
  const toggle = page.getByRole("button", { name: "Show sidebar" });
  if (await toggle.count()) await toggle.click();
  await shot(page, vp, name("2-sidebar"));
  r.steps.sidebar = await overflowOf(page);
  const row = page.getByText("Englewood Q3 estimate review").first();
  if (await row.count()) {
    const before = await page.evaluate(() => window.__focusLog.length);
    await row.click();
    await page.getByText("Q3 summary").first().waitFor({ timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(600);
    r.steps.drawerClosedAfterPick = (await page.locator("[data-narrow-overlay]").count()) === 0 || (await page.getByRole("button", { name: "Show sidebar" }).count()) === 0;
    r.keyboard.afterOpen = await keyboardRaisers(page, before);
    await shot(page, vp, name("3-chat"));
    r.steps.chat = await overflowOf(page);
    // Tap reading text: nothing may raise the keyboard.
    for (const [label, text] of [["userText", "Summarize the Q3 estimate"], ["assistantText", "RFI-014 slab edge detail"], ["quote", "Please confirm the intended set"], ["lastReply", "Want me to add the drawing"]]) {
      const mark = await page.evaluate(() => window.__focusLog.length);
      const el = page.getByText(text).first();
      if (await el.count()) await el.tap({ timeout: 4000 }).catch(() => {});
      await page.waitForTimeout(400);
      r.keyboard[label] = await keyboardRaisers(page, mark);
      if (label === "userText") r.steps.editOpenAfterOneTap = await page.evaluate(() => document.querySelectorAll('[data-slot="aui_edit-composer-root"]').length > 0);
    }
    // Home / app switch: a focused composer must lose focus so the keyboard cannot return alone.
    await page.locator('[data-slot="composer-rich-input"]').first().tap().catch(() => {});
    await page.evaluate(() => window.dispatchEvent(new CustomEvent("hermes:native-lifecycle", { detail: { state: "pause" } })));
    r.keyboard.blurredOnPause = await page.evaluate(() => !(document.activeElement && (document.activeElement.isContentEditable || /TEXTAREA|INPUT/.test(document.activeElement.tagName))));
    // Tap the composer: this one MUST be allowed to raise the keyboard.
    const mark = await page.evaluate(() => window.__focusLog.length);
    await page.evaluate(() => document.activeElement?.blur?.());
    await page.locator('[data-slot="composer-rich-input"]').first().tap().catch(() => {});
    await page.waitForTimeout(400);
    r.keyboard.composerTap = await page.evaluate((n) => window.__focusLog.slice(n).filter((f) => f.slot === "composer-rich-input").map((f) => f.mode), mark);
    r.keyboard.composerFocused = await page.evaluate(() => document.activeElement?.dataset?.slot === "composer-rich-input" && document.activeElement.getAttribute("inputmode") !== "none");
    // Type, then tap Send: the keyboard must close (no focused field, or a keyboard-less one).
    await page.keyboard.type("hello");
    await shot(page, vp, name("4b-typed"));
    const send = page.locator('form[data-slot="composer-root"] button[type="submit"]').first();
    if (await send.count()) {
      await send.tap().catch(() => {});
      await page.waitForTimeout(700);
      r.keyboard.closedAfterSend = await page.evaluate(() => {
        const a = document.activeElement;
        const field = a && (a.isContentEditable || /TEXTAREA|INPUT/.test(a.tagName));
        return !field || a.getAttribute("inputmode") === "none";
      });
    }
    // Keyboard up: the visible area shrinks (adjustResize). The composer must stay on screen.
    await page.setViewportSize({ width: vp.width, height: Math.round(vp.height * 0.55) });
    await shot(page, vp, name("4-keyboard-open"));
    r.steps.keyboardOpen = await page.evaluate(() => {
      const c = document.querySelector('[data-slot="composer-rich-input"]')?.getBoundingClientRect();
      return { composerBottom: c ? Math.round(c.bottom) : null, innerH: innerHeight };
    });
    // A phone held sideways with the keyboard up: the emulator measured 122 css px of page.
    if (vp.width > vp.height) {
      await page.locator('[data-slot="composer-rich-input"]').first().tap().catch(() => {});
      await page.setViewportSize({ width: vp.width, height: 122 });
      await shot(page, vp, name("4c-landscape-keyboard-122"));
      r.steps.landscapeKeyboard = await page.evaluate(() => {
        // The dock holds the status rows AND the composer; chat is visible only above the dock.
        const composer = (document.querySelector('[data-slot="composer-dock"]') ?? document.querySelector('form[data-slot="composer-root"]'))?.getBoundingClientRect();
        const header = document.querySelector("[data-panel-header]")?.getBoundingClientRect();
        return { innerH: innerHeight, chatRoom: composer ? Math.round(composer.top - Math.max(0, header?.bottom ?? 0)) : null, composerH: composer ? Math.round(composer.height) : null };
      });
    }
    await page.setViewportSize({ width: vp.width, height: vp.height });
  }
  // NG-4: a finger long-press (Android sends contextmenu) on the composer or chat text must not
  // open Desktop's right-click menu, so Android's own selection bar can show. A mouse
  // right-click on the composer still opens Desktop's menu (control: Desktop's listener is live).
  {
    const hold = (selector, pointerType) => page.evaluate(([sel, type]) => {
      const el = typeof sel === "string" && sel.startsWith("text=")
        ? [...document.querySelectorAll("p, li, td")].find((n) => n.textContent.includes(sel.slice(5)))
        : document.querySelector(sel);
      if (!el) return null;
      const box = el.getBoundingClientRect();
      if (type === "touch") el.dispatchEvent(new TouchEvent("touchstart", { bubbles: true }));
      el.dispatchEvent(new PointerEvent("contextmenu", { bubbles: true, cancelable: true, pointerType: type, clientX: box.x + 4, clientY: box.y + 4 }));
      if (type === "touch") el.dispatchEvent(new TouchEvent("touchend", { bubbles: true }));
      return true;
    }, [selector, pointerType]);
    const desktopMenu = async () => {
      await page.waitForTimeout(250);
      const open = await page.evaluate(() => document.querySelectorAll('[role="menu"]').length);
      await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(150);
      return open;
    };
    const composer = '[data-slot="composer-rich-input"]';
    r.steps.longPress = {
      composerTouch: (await hold(composer, "touch")) && (await desktopMenu()),
      textTouch: (await hold("text=RFI-014 slab edge", "touch")) && (await desktopMenu()),
      composerMouse: (await hold(composer, "mouse")) && (await desktopMenu()),
    };
  }
  if (!opts.dark) {
    await page.getByRole("button", { name: "Open settings" }).tap().catch(() => {});
    await shot(page, vp, name("5-settings"));
    r.steps.settings = await overflowOf(page);
    await page.keyboard.press("Escape");
  }
  if (vp.width < 640) {
    // In-app browser pane (Cmd/Ctrl-Shift-L): on a phone it takes the width; the chat is not squeezed.
    await page.keyboard.press("Escape").catch(() => {});
    await page.keyboard.press("Control+Shift+L");
    await page.waitForTimeout(1200);
    r.steps.browserPane = await page.evaluate(() => {
      const host = document.querySelector('[data-pane-host^="preview-tile:"]:not([inert])');
      const chat = document.querySelector('[data-tree-tab="workspace"]');
      const b = host?.getBoundingClientRect();
      return host ? { x: Math.round(b.x), w: Math.round(b.width), innerW: innerWidth, scrollW: document.documentElement.scrollWidth,
        chatVisible: !!chat && chat.getClientRects().length > 0 } : null;
    });
    await page.screenshot({ path: `${out}/${vp.name}${opts.dark ? "-dark" : ""}-browser-pane.png` });
    // R1 stage 1: type an address; Desktop's pane loads it through the native guest, which is
    // placed exactly over the pane's page area and hidden while Settings covers it.
    const address = page.getByRole("textbox", { name: /address/i }).first();
    if (await address.count()) {
      await address.fill("https://example.org/");
      await address.press("Enter");
      await page.waitForTimeout(900);
      r.steps.browserGuest = await page.evaluate(() => {
        const ops = window.__guestOps.filter((o) => o.op !== "external");
        const last = [...ops].reverse().find((o) => o.op === "bounds");
        const tag = document.querySelector("webview")?.getBoundingClientRect();
        return {
          created: ops.some((o) => o.op === "create"),
          loaded: [...ops].reverse().find((o) => o.op === "load")?.url ?? null,
          ops: ops.map((o) => o.op + (o.op === "bounds" ? (o.visible ? "+" : "-") : "")).join(","),
          visible: last?.visible ?? null,
          matches: !!(last && tag && Math.abs(last.x - Math.max(0, tag.left)) <= 1 && Math.abs(last.y - Math.max(0, tag.top)) <= 1 && last.w > 100 && last.h > 100),
        };
      });
      await page.getByRole("button", { name: "Open settings" }).first().click({ force: true }).catch(() => {});
      await page.waitForTimeout(700);
      r.steps.browserGuest.hiddenUnderSettings = await page.evaluate(() => [...window.__guestOps].reverse().find((o) => o.op === "bounds")?.visible === false);
      await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(500);
      // Android Back with the pane open and no page history: the pane closes (native destroys the guest).
      r.steps.browserGuest.backClosed = await page.evaluate(async () => {
        const event = new Event("hermes:native-back", { cancelable: true });
        window.dispatchEvent(event);
        await new Promise((resolve) => setTimeout(resolve, 600));
        return event.defaultPrevented && !document.querySelector('[data-pane-host^="preview-tile:"]:not([inert]) webview')
          && window.__guestOps.at(-1)?.op === "destroy";
      });
    } else r.steps.browserGuest = null;
  }
  await context.close();
  return r;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" });
  const report = [];
  try {
    for (const vp of VIEWPORTS.filter((v) => !only || only.some((o) => v.name.includes(o)))) {
      report.push(await scenario(browser, vp));
      if (process.env.DARK) report.push(await scenario(browser, vp, { dark: true }));
    }
  } finally {
    await browser.close();
    writeFileSync(`${out}/report.json`, JSON.stringify(report, null, 2));
  }
  console.log(JSON.stringify(report, null, 1));
  // Gate: no page error, no horizontal page scroll, drawer closes after a pick, only the composer
  // may raise the keyboard, and the composer stays visible with the keyboard up.
  const failures = [];
  for (const r of report) {
    const id = r.vp + (r.dark ? " dark" : "");
    if (r.errors.length) failures.push(`${id}: page errors`);
    if (r.calls?.some((c) => String(c).startsWith("UNEXPECTED desktop."))) failures.push(`${id}: the app used a PC add-on RPC`);
    if (r.calls && !r.calls.includes("GET /api/profiles/active")) failures.push(`${id}: Hermes's own REST was not used for the primary profile`);
    for (const [step, v] of Object.entries(r.steps))
      if (v && typeof v === "object" && "scrollW" in v && v.scrollW !== v.innerW) failures.push(`${id}: horizontal scroll at ${step}`);
    if (r.steps.drawerClosedAfterPick === false) failures.push(`${id}: drawer stayed open after picking a chat`);
    for (const [k, v] of Object.entries(r.keyboard))
      if (!["composerTap", "composerFocused", "blurredOnPause", "closedAfterSend"].includes(k) && Array.isArray(v) && v.length) failures.push(`${id}: ${k} raised the keyboard`);
    if (r.keyboard.closedAfterSend === false) failures.push(`${id}: keyboard stayed up after Send`);
    if (r.steps.editOpenAfterOneTap === false) failures.push(`${id}: one tap on a sent message did not keep its edit box open`);
    if (r.keyboard.blurredOnPause === false) failures.push(`${id}: text field stayed focused on pause`);
    const tb = r.steps.titlebar;
    if (tb && Number(/-(\d+)x/.exec(r.vp)?.[1]) < 640 && (tb.headerH > 40 || tb.plusRight > tb.clusterLeft)) failures.push(`${id}: titlebar not one row or "+" under the buttons (${JSON.stringify(tb)})`);
    const lk = r.steps.landscapeKeyboard;
    if (lk && (lk.chatRoom === null || lk.chatRoom < 40)) failures.push(`${id}: landscape keyboard leaves no readable chat (${JSON.stringify(lk)})`);
    const cr = r.steps.composerRow;
    if (cr && cr.count >= 3 && (cr.spread > 1.5 || cr.minSize < 32)) failures.push(`${id}: composer controls misaligned or small (${JSON.stringify(cr)})`);
    const sr = r.steps.statusRow;
    if (sr && (sr.maxRight > sr.innerW || sr.minLeft < 0)) failures.push(`${id}: status row buttons off screen (${JSON.stringify(sr)})`);
    const bb = r.steps.butterbar;
    if (bb && (bb.detailsRight > bb.innerW || bb.closeRight > bb.innerW)) failures.push(`${id}: butterbar cut off at the right edge (${JSON.stringify(bb)})`);
    if (r.keyboard.composerFocused === false) failures.push(`${id}: composer tap did not allow the keyboard`);
    const lp = r.steps.longPress;
    if (lp && (lp.composerTouch !== 0 || lp.textTouch !== 0)) failures.push(`${id}: a finger long-press opened Desktop's menu over Android's text selection (${JSON.stringify(lp)})`);
    if (lp && !(lp.composerMouse > 0)) failures.push(`${id}: mouse right-click control did not open Desktop's menu (${JSON.stringify(lp)})`);
    const bp = r.steps.browserPane;
    if (bp && (bp.x > 0 || bp.w < bp.innerW - 1 || bp.scrollW > bp.innerW || bp.chatVisible)) failures.push(`${id}: browser pane squeezes or shares the phone screen (${JSON.stringify(bp)})`);
    if (r.steps.browserPane === null) failures.push(`${id}: browser pane did not open`);
    const bg = r.steps.browserGuest;
    if (bg === null) failures.push(`${id}: browser pane has no address bar to drive`);
    else if (bg && !(bg.created && bg.loaded === "https://example.org/" && bg.visible === true && bg.matches && bg.hiddenUnderSettings && bg.backClosed))
      failures.push(`${id}: native browser page not created, loaded, placed over the pane, hidden under Settings or closed by Back (${JSON.stringify(bg)})`);
    const kb = r.steps.keyboardOpen;
    if (kb && (kb.composerBottom === null || kb.composerBottom > kb.innerH)) failures.push(`${id}: composer hidden with keyboard up`);
  }
  console.log(failures.length ? `FAIL\n${failures.join("\n")}` : "PASS: mobile layout gates");
  process.exitCode = failures.length ? 1 : 0;
}
