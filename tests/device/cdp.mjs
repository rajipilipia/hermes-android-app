// Minimal DevTools client for the debug APK's WebView (local tester only).
// Android WebView rejects Playwright's connectOverCDP ("Browser context management is not
// supported"), so this talks to one page target directly: GET /json/list, then a WebSocket with
// Runtime.evaluate. Needs Node 22+ (global fetch and WebSocket). No browser-level commands.
// The bundled page lives at the chosen server origin (or the setup origin before one is chosen).
export const APP_PAGE = /^https:\/\/[^/]+\/assets\/index\.html(?:#|$)/;

export async function attachPage(port, prefix = process.env.TRACE_PAGE_PREFIX) {
  const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const target = list.find((t) => t.type === "page" && (prefix ? String(t.url).startsWith(prefix) : APP_PAGE.test(String(t.url))));
  if (!target) throw new Error(`Hermes page not found on DevTools port ${port} (${list.length} targets)`);
  // WebView may report a host-less or device-local socket URL; always go through the forward.
  const ws = new WebSocket(`ws://127.0.0.1:${port}/devtools/page/${target.id}`);
  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", () => reject(new Error("DevTools WebSocket failed to open")), { once: true });
  });
  let nextId = 0;
  const pending = new Map();
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(String(event.data));
    const waiter = message.id != null && pending.get(message.id);
    if (!waiter) return;
    pending.delete(message.id);
    if (message.error) waiter.reject(new Error(message.error.message));
    else waiter.resolve(message.result);
  });
  const send = (method, params) =>
    new Promise((resolve, reject) => {
      const id = ++nextId;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
  return {
    /** Runs `fn` (a function with no free variables) in the page and returns its JSON value. */
    async evaluate(fn) {
      const result = await send("Runtime.evaluate", { expression: `(${fn.toString()})()`, returnByValue: true, awaitPromise: true });
      if (result.exceptionDetails) throw new Error(`Page error: ${result.exceptionDetails.exception?.description ?? result.exceptionDetails.text}`);
      return result.result.value;
    },
    close: () => ws.close(),
  };
}
