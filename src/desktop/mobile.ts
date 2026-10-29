// Phone behavior for the pinned Hermes Desktop renderer (2026-10-18).
// DOM-only: nothing here edits vendor/ or widens the native bridge. It is installed
// after bootstrap, once the renderer's own modules are loaded (see src/main.tsx).
//
// 1. Keyboard guard: only a touch on a text field, or inside the composer, may raise the
//    on-screen keyboard. Programmatic focus (opening a chat, tapping a sent message
//    which opens its edit box, dialogs, autofocus) is made keyboard-less with
//    inputmode="none" until the next direct touch.
// 2. The narrow sessions overlay closes when the chat area is tapped or the route changes.
// 3. A focused text field is blurred when the app is paused, so returning from Home does not
//    bring the keyboard back on its own. Sending from the composer also closes the keyboard.
// 4. One tap on a sent message opens its edit box (touch focus fix, see installBubbleTapFocus).
// 5. A finger long-press on text gets Android's own selection and clipboard bar, not Desktop's
//    right-click menu (see installNativeTextSelection).
// 6. Back closes Desktop's browser pane on a phone once its page has no more history (installPaneBack).

import { installSingleScreenLayout } from "./single-screen.ts";

const TEXT_INPUT = new Set(["", "text", "search", "url", "email", "tel", "password", "number"]);
/** Composer chrome (editor, attach, mic, send). A touch here counts as keyboard intent.
 *  Not `[data-composer-target]`: that wraps the whole chat surface, so every tap on chat text
 *  counted as composer intent (found by the round 3 tap trace). */
const COMPOSER_FORM = 'form[data-slot="composer-root"]';
const COMPOSER = `${COMPOSER_FORM}, [data-slot="composer-rich-input"]`;
const INTENT_MS = 800;
const REVEAL_EVENT = "hermes:pane-toggle-reveal";
const BUBBLE = '[data-slot="aui_user-bubble-actions"]';
const EDIT_ROOT = '[data-slot="aui_edit-composer-root"]';

export function isTextEntry(node: unknown): node is HTMLElement {
  const el = node as HTMLElement | null;
  if (!el || el.nodeType !== 1) return false;
  if (el.tagName === "TEXTAREA") return true;
  if (el.tagName === "INPUT") return TEXT_INPUT.has((el as HTMLInputElement).type);
  if (typeof el.isContentEditable === "boolean") return el.isContentEditable;
  return ["", "true", "plaintext-only"].includes(el.getAttribute("contenteditable") ?? "false");
}

export function installKeyboardGuard(win: Window & typeof globalThis = window, now: () => number = () => Date.now()): () => void {
  const doc = win.document;
  const saved = new WeakMap<HTMLElement, string | null>();
  let intentUntil = 0;
  const suppress = (el: HTMLElement) => {
    if (saved.has(el)) return;
    saved.set(el, el.getAttribute("inputmode"));
    el.setAttribute("inputmode", "none");
  };
  const restore = (el: HTMLElement) => {
    if (!saved.has(el)) return;
    const original = saved.get(el);
    saved.delete(el);
    if (original === null || original === undefined) el.removeAttribute("inputmode");
    else el.setAttribute("inputmode", original);
  };
  const onTouch = (event: Event) => {
    const target = event.target instanceof win.Element ? event.target : null;
    if (!target) return;
    const field = target.closest<HTMLElement>('textarea, input, [contenteditable]');
    const direct = isTextEntry(field) ? field : null;
    if (direct || target.closest(COMPOSER)) intentUntil = now() + INTENT_MS;
    if (direct) restore(direct);
    else {
      // A tap on the composer's padding focuses the editor from script; allow it.
      const editor = target.closest(COMPOSER)?.querySelector<HTMLElement>('[data-slot="composer-rich-input"]');
      if (editor) restore(editor);
    }
  };
  const nativeFocus = win.HTMLElement.prototype.focus;
  win.HTMLElement.prototype.focus = function (this: HTMLElement, ...args: Parameters<HTMLElement["focus"]>) {
    if (isTextEntry(this) && doc.activeElement !== this && now() >= intentUntil) suppress(this);
    return nativeFocus.apply(this, args);
  };
  // autofocus and focus paths that bypass focus(): best effort.
  const onFocusIn = (event: Event) => {
    const el = event.target;
    if (isTextEntry(el) && now() >= intentUntil) suppress(el);
  };
  // Send (or Stop) from the composer closes the keyboard (2026-10-18). The send tap itself
  // counted as composer intent, so clear it; upstream's refocus after sending then lands
  // keyboard-less. Deferred so the renderer reads the message before focus moves.
  const onSubmit = (event: Event) => {
    const form = event.target instanceof win.Element ? event.target : null;
    if (!form?.matches(COMPOSER_FORM)) return;
    intentUntil = 0;
    const drop = () => {
      const el = doc.activeElement;
      if (isTextEntry(el) && form.contains(el)) {
        suppress(el);
        el.blur();
      }
    };
    for (const ms of [0, 150, 400]) win.setTimeout(drop, ms);
  };
  doc.addEventListener("pointerdown", onTouch, true);
  doc.addEventListener("touchstart", onTouch, { capture: true, passive: true });
  doc.addEventListener("focusin", onFocusIn, true);
  doc.addEventListener("submit", onSubmit, true);
  return () => {
    win.HTMLElement.prototype.focus = nativeFocus;
    doc.removeEventListener("pointerdown", onTouch, true);
    doc.removeEventListener("touchstart", onTouch, true);
    doc.removeEventListener("focusin", onFocusIn, true);
    doc.removeEventListener("submit", onSubmit, true);
  };
}

/** Closes the narrow sessions overlay (a pinned drawer upstream) on a chat-area tap or navigation. */
export function installOverlayDismiss(win: Window & typeof globalThis = window): () => void {
  const doc = win.document;
  const close = () => {
    const overlay = doc.querySelector<HTMLElement>("[data-narrow-overlay]");
    const id = overlay?.dataset.narrowOverlay;
    if (id) win.dispatchEvent(new win.CustomEvent(REVEAL_EVENT, { detail: { id, mode: "close" } }));
  };
  const onPointerDown = (event: Event) => {
    const target = event.target instanceof win.Element ? event.target : null;
    // Only the chat/tree area dismisses. Menus and dialogs opened from the drawer are portaled elsewhere.
    if (target?.closest("[data-tree-split]") && !target.closest("[data-narrow-overlay]")) close();
  };
  let where = win.location.pathname + win.location.search + win.location.hash;
  const onRoute = () => {
    const next = win.location.pathname + win.location.search + win.location.hash;
    if (next === where) return;
    where = next;
    close();
  };
  const history = win.history;
  const push = history.pushState, replace = history.replaceState;
  history.pushState = function (this: History, ...a: Parameters<History["pushState"]>) {
    const r = push.apply(this, a);
    queueMicrotask(onRoute);
    return r;
  };
  history.replaceState = function (this: History, ...a: Parameters<History["replaceState"]>) {
    const r = replace.apply(this, a);
    queueMicrotask(onRoute);
    return r;
  };
  doc.addEventListener("pointerdown", onPointerDown, true);
  win.addEventListener("popstate", onRoute);
  win.addEventListener("hashchange", onRoute);
  return () => {
    history.pushState = push;
    history.replaceState = replace;
    doc.removeEventListener("pointerdown", onPointerDown, true);
    win.removeEventListener("popstate", onRoute);
    win.removeEventListener("hashchange", onRoute);
  };
}

/** Home or another app: drop focus from a text field so Android does not bring the keyboard back by
 *  itself on return (the emulator saw this 2 of 2 times). The draft stays in the field. */
export function installPauseBlur(win: Window & typeof globalThis = window): () => void {
  const doc = win.document;
  const blur = () => {
    const el = doc.activeElement;
    if (isTextEntry(el)) (el as HTMLElement).blur();
  };
  const onLifecycle = (event: Event) => {
    if ((event as CustomEvent<{ state?: string }>).detail?.state === "pause") blur();
  };
  const onVisibility = () => {
    if (doc.visibilityState === "hidden") blur();
  };
  win.addEventListener("hermes:native-lifecycle", onLifecycle);
  doc.addEventListener("visibilitychange", onVisibility);
  win.addEventListener("pagehide", blur);
  return () => {
    win.removeEventListener("hermes:native-lifecycle", onLifecycle);
    doc.removeEventListener("visibilitychange", onVisibility);
    win.removeEventListener("pagehide", blur);
  };
}

/** One tap on a sent message must open its edit box (emulator round 2: it took two taps).
 *  On touch the bubble <button> takes focus only after pointerup. Upstream's composer focus
 *  tracker has already forgotten the pointer by then, treats the focus as stray and moves it to
 *  the main composer; that steal makes the new edit box cancel itself ~80 ms later. Cancelling
 *  the touch-generated mousedown keeps focus where it is; the click (which opens the edit box)
 *  still fires. Mouse input is untouched. */
export function installBubbleTapFocus(win: Window & typeof globalThis = window, now: () => number = () => Date.now()): () => void {
  const doc = win.document;
  let lastTouch = -Infinity;
  const onTouch = (event: Event) => {
    if (event.type !== "touchstart" && (event as PointerEvent).pointerType !== "touch") return;
    lastTouch = now();
    // After a composer keyboard session (tap composer, Back), the composer still holds focus and
    // Android could bring the keyboard back with the edit box (emulator round 4, S3: 3 of 6).
    // Drop that focus first so the edit box starts clean. The draft text stays.
    const target = event.target instanceof win.Element ? event.target : null;
    const active = doc.activeElement;
    if (target?.closest(BUBBLE) && !target.closest(EDIT_ROOT) && isTextEntry(active) && !active.closest(EDIT_ROOT)) active.blur();
  };
  const onMouseDown = (event: Event) => {
    if (now() - lastTouch > 1000) return;
    const target = event.target instanceof win.Element ? event.target : null;
    if (target?.closest(BUBBLE) && !target.closest(EDIT_ROOT))
      event.preventDefault();
  };
  doc.addEventListener("touchstart", onTouch, { capture: true, passive: true });
  doc.addEventListener("pointerdown", onTouch, true);
  doc.addEventListener("mousedown", onMouseDown, true);
  return () => {
    doc.removeEventListener("touchstart", onTouch, true);
    doc.removeEventListener("pointerdown", onTouch, true);
    doc.removeEventListener("mousedown", onMouseDown, true);
  };
}

/** Desktop surfaces whose long-press menu or picker works on a phone: links (open/copy link),
 *  images, the Star Map and terminal canvases, the sent-message reaction picker. */
const DESKTOP_HOLD = "a[href], img, canvas, .xterm, [data-context-menu-skip]";
/** Desktop's explicit row/tab/status menus (session rows and the like). */
const DESKTOP_MENU = '[data-hermes-context-menu-trigger], [data-slot="context-menu-trigger"]';

/** Shared by the native contextmenu guard and Radix's separately scheduled touch timer. */
export function nativeTextSelectionTarget(target: EventTarget | null, win: Window & typeof globalThis = window): boolean {
  if (!(target instanceof win.Element)) return false;
  if (isTextEntry(target.closest<HTMLElement>("textarea, input, [contenteditable]"))) return true;
  // A selected word in a sent bubble is still text, not a request for reactions.
  // Test intersection so an unrelated selection cannot swallow a tab/row menu.
  const selection = win.getSelection();
  if (selection && !selection.isCollapsed && selection.rangeCount > 0 &&
      Array.from({ length: selection.rangeCount }, (_, i) => selection.getRangeAt(i)).some(range => range.intersectsNode(target))) return true;
  if (target.closest(DESKTOP_HOLD)) return false;
  const menu = target.closest(DESKTOP_MENU);
  // Pane-body menus are fallbacks; explicit row/tab/status menus retain their gestures.
  return !menu || menu.hasAttribute("data-zone-body");
}

/** A finger long-press on a text field, the composer or chat text gets Android's own text
 *  selection: handles plus the Cut/Copy/Paste/Select all bar and the keyboard's clipboard
 *  (NG-4, 2026-10-20). Android sends that long-press as a contextmenu event; Desktop's app-wide
 *  menu took it (a right-click menu), covered Android's bar, and its Cut/Copy/Paste ran an
 *  Electron main-process edit. This listener runs before Desktop's (installed first, same
 *  window capture phase) and stops the event without preventDefault, so Android's default
 *  action runs. Android owns text menus regardless of the reported pointer kind:
 *  WebView/selection handles can emit mouse-like or delayed contextmenu events.
 *  Non-Android mouse previews and explicit non-text Desktop menus are preserved. */
export function installNativeTextSelection(win: Window & typeof globalThis = window, now: () => number = () => Date.now()): () => void {
  const doc = win.document;
  let touching = false;
  let lastTouch = -Infinity;
  const onTouchStart = () => {
    touching = true;
    lastTouch = now();
  };
  const onTouchEnd = () => {
    touching = false;
  };
  const onContextMenu = (event: Event) => {
    const pointer = (event as PointerEvent).pointerType;
    const fromTouch = pointer ? pointer === "touch" : touching || now() - lastTouch < 1500;
    if (!fromTouch && !doc.documentElement.hasAttribute("data-android-touch")) return;
    if (!nativeTextSelectionTarget(event.target, win)) return;
    event.stopImmediatePropagation();
  };
  doc.addEventListener("touchstart", onTouchStart, { capture: true, passive: true });
  doc.addEventListener("touchend", onTouchEnd, { capture: true, passive: true });
  doc.addEventListener("touchcancel", onTouchEnd, { capture: true, passive: true });
  win.addEventListener("contextmenu", onContextMenu, true);
  return () => {
    doc.removeEventListener("touchstart", onTouchStart, true);
    doc.removeEventListener("touchend", onTouchEnd, true);
    doc.removeEventListener("touchcancel", onTouchEnd, true);
    win.removeEventListener("contextmenu", onContextMenu, true);
  };
}

/** Phone Enter in a Desktop composer makes a new line (the Send button sends; see
 *  composer-native.ts). The keyboard's Enter arrives as a native insertParagraph, which
 *  Desktop's editor cleanup drops as an empty block, so it is turned into the same line break
 *  Desktop already inserts for Shift+Enter. Mouse/keyboard Desktop never reaches this. */
export function installComposerNewline(win: Window & typeof globalThis = window): () => void {
  const onBeforeInput = (event: Event) => {
    // A non-cancelable event (mid-composition) keeps its own break; adding one would double it.
    if ((event as InputEvent).inputType !== "insertParagraph" || !event.cancelable) return;
    const target = event.target as Element | null;
    if (!target?.closest?.('[data-slot="composer-rich-input"]')) return;
    event.preventDefault();
    win.document.execCommand("insertLineBreak");
  };
  win.document.addEventListener("beforeinput", onBeforeInput, true);
  return () => win.document.removeEventListener("beforeinput", onBeforeInput, true);
}

/** Android Back on a phone with a Desktop preview open (browser, HTML, file, PDF or image; it fills
 *  the screen there): after the page's own history (native goes back first), Back closes the
 *  preview with Desktop's own Close button, like closing a sheet, instead of leaving the app. A menu, dialog or drawer open over it
 *  closes first (Escape, as before). Wide screens keep Desktop's behavior. */
export function installPaneBack(win: Window & typeof globalThis = window): () => void {
  const onBack = (event: Event) => {
    if (win.innerWidth >= 640) return;
    const doc = win.document;
    if (doc.querySelector('[role="dialog"], [role="menu"], [role="listbox"], [data-narrow-overlay]')) return;
    // Browser/HTML panes carry their own Close in the pane bar. File, PDF and image previews have
    // none inside the pane: their Close is the "x" of the active preview tab in the tab strip.
    const closeIn = (root: Element | null) =>
      [...(root?.querySelectorAll<HTMLElement>("button") ?? [])].find((button) => button.querySelector(".codicon-close"));
    const close =
      closeIn(doc.querySelector('[data-pane-host^="preview-tile:"]:not([inert])')) ??
      closeIn(doc.querySelector('[data-tree-tab^="preview-tile:"][aria-selected="true"]'));
    if (!close) return;
    event.preventDefault();
    close.click();
  };
  win.addEventListener("hermes:native-back", onBack);
  return () => win.removeEventListener("hermes:native-back", onBack);
}

export function installMobile(win: Window & typeof globalThis = window): () => void {
  const touch = !!win.matchMedia?.("(any-pointer: coarse)").matches;
  if (!touch) return () => {};
  win.document.documentElement.dataset.androidTouch = "";
  const stops = [installSingleScreenLayout(win), installKeyboardGuard(win), installOverlayDismiss(win), installPauseBlur(win), installBubbleTapFocus(win), installNativeTextSelection(win), installPaneBack(win), installComposerNewline(win)];
  return () => stops.forEach((stop) => stop());
}
