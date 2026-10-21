// DEVICE DIAGNOSTIC (local tester only). Attaches to the debug APK's WebView over its DevTools
// socket (raw WebSocket, see cdp.mjs) and prints layout measurements for the mobile gates:
// titlebar, composer row, composer status rows, theme state and keyboard-relevant focus.
// Measurements only: no text content.
//
//   adb -H 127.0.0.1 -P 5041 -s emulator-6000 forward tcp:9333 localabstract:webview_devtools_remote_<pid>
//   node tests/device/layout-probe.mjs 9333 > .cache/r3-probe-<label>.json
import { attachPage } from "./cdp.mjs";

const port = Number(process.argv[2] ?? 9333);
const page = await attachPage(port);
try {
  const result = await page.evaluate(() => {
    const rect = (el) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { left: Math.round(r.left), top: Math.round(r.top), right: Math.round(r.right), bottom: Math.round(r.bottom), w: Math.round(r.width), h: Math.round(r.height) };
    };
    const q = (s) => document.querySelector(s);
    const composer = q('form[data-slot="composer-root"]');
    const controls = ['button[aria-label="Add context"]', 'button[aria-label^="Model"]', 'button[aria-label="Voice dictation"]', 'button[type="submit"]', 'button[aria-label="Start voice conversation"]']
      .map((s) => [s, rect(composer?.querySelector(s))])
      .filter(([, r]) => r && r.w);
    const cys = controls.map(([, r]) => r.top + r.h / 2);
    const statusRows = [...document.querySelectorAll('[data-slot="composer-status-stack"] .status-row-actions')].map((a) => ({
      row: rect(a.closest('[data-slot="status-row"]')),
      buttons: [...a.querySelectorAll("button")].map(rect),
    }));
    const active = document.activeElement;
    return {
      viewport: { w: innerWidth, h: innerHeight, dpr: devicePixelRatio, scrollW: document.documentElement.scrollWidth },
      theme: { prefersDark: matchMedia("(prefers-color-scheme: dark)").matches, htmlDark: document.documentElement.classList.contains("dark") },
      titlebar: {
        header: rect(q("[data-panel-header]")),
        leftCluster: rect(q('[data-titlebar-cluster="left"]')),
        rightCluster: rect(q('[data-titlebar-cluster="right"]')),
        rightButtons: [...document.querySelectorAll('[data-titlebar-cluster="right"] button')].filter((b) => b.getBoundingClientRect().width).map((b) => b.getAttribute("aria-label")),
        plus: rect(q('button[aria-label="New session tab"]')),
      },
      composer: { root: rect(composer), controls: Object.fromEntries(controls), centerSpread: cys.length ? Math.round((Math.max(...cys) - Math.min(...cys)) * 10) / 10 : null },
      statusRows,
      focus: { slot: active?.dataset?.slot ?? active?.tagName ?? null, inputmode: active?.getAttribute?.("inputmode") ?? null, editOpen: document.querySelectorAll('[data-slot="aui_edit-composer-root"]').length },
    };
  });
  console.log(JSON.stringify(result, null, 1));
} finally {
  // Only drop the DevTools connection; never close the app's WebView.
  page.close();
}
