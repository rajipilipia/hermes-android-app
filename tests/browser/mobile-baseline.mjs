// TEST ONLY. Synthetic wire peer + real production renderer at phone sizes.
// Takes screenshots and layout measurements. Not device acceptance.
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
const origin = process.env.DESKTOP_TEST_ORIGIN ?? "http://127.0.0.1:18767";
const tag = process.env.SHOT_TAG ?? "base";
const out = ".cache/mobile-layout";
mkdirSync(out, { recursive: true });
const sizes = [
  { name: "phone", width: 393, height: 852 },
  { name: "small", width: 360, height: 640 },
  { name: "fold-inner", width: 700, height: 840 },
];
const browser = await chromium.launch({ channel: "msedge", headless: true });
const report = [];
try {
  for (const s of sizes) {
    const context = await browser.newContext({
      viewport: { width: s.width, height: s.height },
      hasTouch: true,
      isMobile: true,
      deviceScaleFactor: 2.5,
      colorScheme: "dark",
      reducedMotion: "reduce",
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.addInitScript(() => {
      window.HermesPc = {
        request(id, op) {
          queueMicrotask(() =>
            window.__hermesPcResult?.(id, true, op === "ticket" ? "t" : ""),
          );
        },
      };
    });
    await page.routeWebSocket("wss://gateway.example.com/api/ws*", (ws) => {
      ws.onMessage((text) => {
        const f = JSON.parse(String(text));
        if (!f.method || f.id == null) return;
        let r = {};
        if (f.method === "desktop.call") {
          const op = f.params.operation;
          const body =
            op === "GET /api/profiles"
              ? { profiles: [{ name: "default", is_active: true, is_default: true }], active_profile: "default" }
              : op === "GET /api/config"
                ? { display: { language: "en", skin: "nous" }, agent: { max_turns: 90 }, compression: { enabled: true } }
                : op.includes("sessions")
                  ? { sessions: [], total: 0, has_more: false }
                  : op === "GET /api/model/info"
                    ? { model: "synthetic/test", provider: "test", context_length: 32768 }
                    : op === "GET /api/cron/jobs" ? { jobs: [] }
                    : op === "GET /api/skills" ? { skills: [] }
                    : op === "GET /api/tools/terminal/backends" ? { backends: [] }
                    : op === "GET /api/mcp/servers" ? { servers: [] }
                    : op === "GET /api/tools/toolsets" ? { toolsets: [] }
                    : {};
          r = { status: 200, body };
        } else if (f.method === "session.list") r = { sessions: [], total: 0, has_more: false };
        else if (f.method === "profiles.list") r = { profiles: [{ name: "default", is_active: true }], active_profile: "default" };
        else if (f.method === "commands.catalog") r = { commands: [{ name: "help", description: "Help", desktop: "client" }] };
        else if (f.method === "session.events.since") r = { events: [], count: 0, latest_seq: 0, epoch: "s", open_requests: [] };
        else if (f.method === "setup.status") r = { provider_configured: true, ready: true };
        else if (f.method === "setup.runtime_check") r = { ok: true, model: "synthetic/test", provider: "test" };
        else if (f.method === "model.options") r = { providers: [], current: { model: "synthetic/test", provider: "test" } };
        else if (f.method === "session.active_list") r = { sessions: [] };
        else if (f.method === "onboarding.state") r = { eligible: false, run: false, run_id: null, session_id: null };
        else if (f.method === "i18n.languages") r = { languages: [] };
        else if (f.method === "i18n.catalog") r = { locale: "en", messages: {} };
        else if (f.method === "free_tier.status") r = { enabled: false, notice_pending: false };
        else if (f.method === "models.list") r = { models: [] };
        ws.send(JSON.stringify({ jsonrpc: "2.0", id: f.id, result: r }));
      });
    });
    await page.goto(origin, { waitUntil: "networkidle" });
    await page.waitForSelector("[data-contrib-shell]", { timeout: 20000 });
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${out}/${tag}-${s.name}-home.png` });
    const m = await page.evaluate(() => {
      const vw = innerWidth;
      const over = [...document.querySelectorAll("body *")]
        .filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && (r.right > vw + 1 || r.left < -1); })
        .slice(0, 8)
        .map((e) => `${e.tagName.toLowerCase()}.${String(e.className).slice(0, 50)} r=${Math.round(e.getBoundingClientRect().right)}`);
      const small = [...document.querySelectorAll("button, a, [role=button], textarea, input, [contenteditable]")]
        .filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && (r.height < 32 || r.width < 32); })
        .length;
      return { vw, scrollW: document.documentElement.scrollWidth, over, smallTargets: small,
        active: document.activeElement?.tagName, fontSize: getComputedStyle(document.body).fontSize };
    });
    report.push({ size: s, ...m, errors: errors.length });
    await context.close();
  }
} finally {
  await browser.close();
  writeFileSync(`${out}/${tag}-report.json`, JSON.stringify(report, null, 2));
}
console.log(JSON.stringify(report, null, 2));
