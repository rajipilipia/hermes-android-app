// DEVICE DIAGNOSTIC (local tester only). Attaches to the debug APK's WebView over its DevTools
// socket (raw WebSocket, see cdp.mjs) and records the structural event sequence of taps:
// which element got pointer/touch/click/dblclick, focus moves, whether a text selection existed, and whether the sent-message
// edit box is open. It records NO text content, URLs, tokens or input values.
//
//   adb -H 127.0.0.1 -P 5041 -s emulator-6000 shell "cat /proc/net/unix | grep webview_devtools_remote"
//   adb -H 127.0.0.1 -P 5041 -s emulator-6000 forward tcp:9333 localabstract:webview_devtools_remote_<pid>
//   node tests/device/tap-trace.mjs 9333 25 > .cache/r3-tap-trace.json
//   (during the 25 s, tap with `adb ... shell input tap <x> <y>`, see TO-TESTER.md)
//   adb -H 127.0.0.1 -P 5041 -s emulator-6000 forward --remove tcp:9333
import { attachPage } from "./cdp.mjs";

const port = Number(process.argv[2] ?? 9333);
const seconds = Number(process.argv[3] ?? 25);
const page = await attachPage(port);
try {
  await page.evaluate(() => {
    if (window.__tapTrace) return;
    const log = [];
    window.__tapTrace = log;
    const t0 = performance.now();
    const describe = (el) => {
      if (!(el instanceof Element)) return String(el?.nodeName ?? "none");
      const slot = el.closest("[data-slot]")?.getAttribute("data-slot") ?? "";
      const label = el.closest("[aria-label]")?.getAttribute("aria-label") ?? "";
      // aria-labels of message bubbles may contain message text: keep only a fixed-size hash.
      let h = 0;
      for (const ch of label) h = (h * 31 + ch.charCodeAt(0)) | 0;
      return `${el.tagName.toLowerCase()} slot=${slot} label#=${label ? (h >>> 0).toString(16) : "-"}`;
    };
    const state = () => ({
      editOpen: document.querySelectorAll('[data-slot="aui_edit-composer-root"]').length,
      active: describe(document.activeElement),
      inputmode: document.activeElement?.getAttribute?.("inputmode") ?? null,
      selection: (() => {
        const s = getSelection();
        return s ? (s.isCollapsed ? "collapsed" : "range") : "none";
      })(),
    });
    for (const type of ["touchstart", "touchend", "pointerdown", "pointerup", "click", "dblclick", "contextmenu", "focusin", "focusout"])
      document.addEventListener(
        type,
        (e) => {
          const entry = { t: Math.round(performance.now() - t0), type, target: describe(e.target), detail: e.detail ?? null, prevented: e.defaultPrevented, ...state() };
          log.push(entry);
          // Re-read the state after React commits, to see what the event changed.
          setTimeout(() => log.push({ t: Math.round(performance.now() - t0), type: `${type}+150ms`, ...state() }), 150);
        },
        true,
      );
  });
  console.error(`Recording for ${seconds} s. Tap now.`);
  await new Promise((r) => setTimeout(r, seconds * 1000));
  console.log(JSON.stringify(await page.evaluate(() => window.__tapTrace), null, 1));
} finally {
  // Only drop the DevTools connection; never close the app's WebView.
  page.close();
}
