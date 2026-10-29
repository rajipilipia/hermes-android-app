// Verbose, privacy-safe app logging for phone debugging (the author, 2026-10-28: "verbose logging for
// all"). Observe only. Lines go through diag() (logcat tag HermesDiag) and carry control names,
// route shapes, error names and numbers. Never chat text, session titles, paths or URLs:
// a control with visible text logs only its text length; route ids are masked.
import { describeFailure, diag } from "./diag";

const CONTROL = 'button, a[href], [role="button"], [role="menuitem"], [role="menuitemradio"], [role="menuitemcheckbox"], [role="tab"], [role="option"], [role="switch"], [role="checkbox"], summary';

/** Static name of a tapped control: aria-label only for icon-only controls (their label is
 *  fixed UI copy); text controls report their text length instead of the text. */
export function controlName(el: Element): Record<string, string | number | undefined> {
  const text = (el.textContent ?? "").trim();
  const label = el.getAttribute("aria-label") ?? el.getAttribute("title") ?? undefined;
  return {
    tag: el.tagName.toLowerCase(),
    role: el.getAttribute("role") ?? undefined,
    slot: el.getAttribute("data-slot") ?? undefined,
    testid: el.getAttribute("data-testid") ?? undefined,
    label: text ? undefined : label?.slice(0, 40),
    text_len: text ? text.length : undefined,
    disabled: el.matches(":disabled, [aria-disabled=\"true\"]") || undefined,
  } as Record<string, string | number | undefined>;
}

/** Route shape with ids masked: any segment holding a digit or longer than 24 chars becomes ":id". */
export function routeShape(win: Window): string {
  const raw = win.location.hash ? win.location.hash.replace(/^#/, "") : win.location.pathname;
  return (raw.split("?")[0] || "/")
    .split("/")
    .map(part => (/\d/.test(part) || part.length > 24 ? ":id" : part))
    .join("/")
    .slice(0, 80);
}

export function installVerboseLogging(win: Window & typeof globalThis = window): () => void {
  const doc = win.document;
  const onTap = (event: Event) => {
    const target = event.target instanceof Element ? event.target.closest(CONTROL) : null;
    if (target) diag("tap", controlName(target));
  };
  let route = routeShape(win);
  diag("route", { to: route });
  const onRoute = () => {
    const next = routeShape(win);
    if (next === route) return;
    diag("route", { from: route, to: next });
    route = next;
  };
  const history = win.history;
  const push = history.pushState;
  const replace = history.replaceState;
  history.pushState = function (...args: Parameters<History["pushState"]>) {
    push.apply(this, args);
    onRoute();
  };
  history.replaceState = function (...args: Parameters<History["replaceState"]>) {
    replace.apply(this, args);
    onRoute();
  };
  const onError = (event: ErrorEvent) => diag("js_error", { where: event.filename ? "script" : "unknown", line: event.lineno, detail: describeFailure(event.error ?? { message: event.message }) });
  const onRejection = (event: PromiseRejectionEvent) => diag("js_rejection", { detail: describeFailure(event.reason) });
  const onPage = (event: Event) => diag("page", { type: event.type, visible: doc.visibilityState });
  doc.addEventListener("click", onTap, true);
  win.addEventListener("popstate", onRoute);
  win.addEventListener("hashchange", onRoute);
  win.addEventListener("error", onError);
  win.addEventListener("unhandledrejection", onRejection);
  for (const type of ["pagehide", "pageshow", "freeze", "resume"]) win.addEventListener(type, onPage);
  return () => {
    doc.removeEventListener("click", onTap, true);
    win.removeEventListener("popstate", onRoute);
    win.removeEventListener("hashchange", onRoute);
    win.removeEventListener("error", onError);
    win.removeEventListener("unhandledrejection", onRejection);
    for (const type of ["pagehide", "pageshow", "freeze", "resume"]) win.removeEventListener(type, onPage);
    history.pushState = push;
    history.replaceState = replace;
  };
}
