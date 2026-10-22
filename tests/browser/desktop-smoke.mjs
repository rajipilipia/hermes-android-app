// TEST ONLY. A synthetic wire peer exercises the real production renderer.
// This does not authenticate to, contact or assert live Hermes backend parity.
import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { restReply } from "./mobile-layout.mjs";
const origin = process.env.DESKTOP_TEST_ORIGIN ?? "http://127.0.0.1:18767";
const out = ".cache/desktop-browser";
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ channel: "msedge", headless: true });
const report = [];
try {
  for (const viewport of [
    { width: 393, height: 852 },
    { width: 820, height: 1180 },
  ]) {
    const context = await browser.newContext({
      viewport,
      colorScheme: "light",
      reducedMotion: "reduce",
    });
    const page = await context.newPage();
    const errors = [],
      calls = [];
    page.on("pageerror", (error) => errors.push(error.stack ?? error.message));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    // Native HermesApi bridge: Hermes's own REST from the shared synthetic fixtures.
    await page.exposeFunction("__hermesRestFixture", (request) => restReply(JSON.parse(request)));
    await page.addInitScript(() => {
      window.HermesApi = {
        call(id, request) {
          window.__hermesRestFixture(request).then((reply) =>
            window.__hermesApiResult?.(id, true, JSON.stringify({ status: reply.status, body: JSON.stringify(reply.body) })));
        },
      };
    });
    await page.addInitScript(() => {
      window.HermesPc = {
        request(id, operation) {
          queueMicrotask(() =>
            window.__hermesPcResult?.(
              id,
              true,
              operation === "ticket" ? "synthetic-test-ticket" : "",
            ),
          );
        },
      };
    });
    // The app dials its own page origin (the chosen server) since native gateways phase 1.
    await page.routeWebSocket(
      /\/api\/ws(\?|$)/,
      (ws) => {
        ws.onMessage((text) => {
          const frame = JSON.parse(String(text));
          if (!frame.method || frame.id == null) return;
          calls.push({ method: frame.method, params: frame.params });
          let result = {};
          // Native only: Desktop features use Hermes's REST (window.HermesApi below).
          assert.ok(!frame.method.startsWith("desktop."), `PC add-on RPC ${frame.method}`);
          if (frame.method === "session.list")
            result = { sessions: [], total: 0, has_more: false };
          else if (frame.method === "profiles.list")
            result = {
              profiles: [{ name: "default", is_active: true }],
              active_profile: "default",
            };
          else if (frame.method === "commands.catalog")
            result = {
              commands: [
                { name: "help", description: "Help", desktop: "client" },
                { name: "skin", description: "Theme", desktop: "client" },
              ],
            };
          else if (frame.method === "session.events.since")
            result = {
              events: [],
              count: 0,
              latest_seq: 0,
              epoch: "synthetic",
              open_requests: [],
            };
          else if (frame.method === "setup.status")
            result = { provider_configured: true, ready: true };
          else if (frame.method === "setup.runtime_check")
            result = { ok: true, model: "synthetic/test", provider: "test" };
          else if (frame.method === "model.options")
            result = {
              providers: [],
              current: { model: "synthetic/test", provider: "test" },
            };
          else if (frame.method === "session.active_list")
            result = { sessions: [] };
          else if (frame.method === "onboarding.state")
            result = {
              eligible: false,
              run: false,
              run_id: null,
              session_id: null,
            };
          else if (frame.method === "i18n.languages")
            result = { languages: [] };
          else if (frame.method === "i18n.catalog")
            result = { locale: "en", messages: {} };
          else if (frame.method === "free_tier.status")
            result = { enabled: false, notice_pending: false };
          else if (frame.method === "models.list") result = { models: [] };
          ws.send(JSON.stringify({ jsonrpc: "2.0", id: frame.id, result }));
        });
      },
    );
    await page.goto(origin, { waitUntil: "networkidle" });
    await expect(page.locator("[data-contrib-shell]")).toBeVisible();
    await expect(page.locator("textarea").first()).toBeVisible();
    await page
      .locator("textarea")
      .first()
      .fill("Synthetic unsent Android draft");
    await expect(page.locator("textarea").first()).toHaveValue(
      "Synthetic unsent Android draft",
    );
    await page.screenshot({
      path: `${out}/initial-${viewport.width}.png`,
      fullPage: true,
    });
    await page.keyboard.press("Control+k");
    await expect(page.locator("[cmdk-input]")).toBeVisible();
    await page.locator("[cmdk-input]").fill("theme");
    await expect(page.locator("[cmdk-item]").first()).toBeVisible();
    await page.screenshot({
      path: `${out}/palette-${viewport.width}.png`,
      fullPage: true,
    });
    const paletteText = await page.locator("[cmdk-root]").innerText();
    await page.keyboard.press("Escape");
    await expect(page.locator("textarea").first()).toHaveValue(
      "Synthetic unsent Android draft",
    );
    await page.emulateMedia({ colorScheme: "dark" });
    await expect(page.locator("html")).toHaveClass(/dark/);
    await page.screenshot({
      path: `${out}/dark-${viewport.width}.png`,
      fullPage: true,
    });
    await page.emulateMedia({ colorScheme: "light" });
    await expect(page.locator("html")).not.toHaveClass(/dark/);
    const text = await page.locator("body").innerText();
    report.push({
      viewport,
      paletteText,
      errors,
      calls,
      text,
      buttons: await page.getByRole("button").allTextContents(),
      dimensions: await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        width: innerWidth,
      })),
    });
    await context.close();
    assert.equal(report.at(-1).dimensions.scroll, viewport.width);
    assert.deepEqual(
      errors.filter(
        (error) =>
          !error.includes(
            "This Desktop capability is unavailable or has invalid arguments on this Android connection.",
          ),
      ),
      [],
    );
  }
} finally {
  await browser.close();
  writeFileSync(`${out}/report.json`, JSON.stringify(report, null, 2));
}
console.log(
  JSON.stringify(
    report.map(({ viewport, errors, dimensions, paletteText }) => ({
      viewport,
      dimensions,
      passed: [
        "real ContribController shell",
        "composer unsent draft",
        "Ctrl+K real command palette and theme search",
        "draft survives palette close",
        "system light→dark→light",
        "no horizontal overflow",
      ],
      knownCapabilityDenials: errors.length,
      paletteMatched: paletteText,
    })),
    null,
    2,
  ),
);
