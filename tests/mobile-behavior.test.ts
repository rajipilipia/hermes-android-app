// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installBubbleTapFocus, installKeyboardGuard, installNativeTextSelection, installOverlayDismiss, installPaneBack, installPauseBlur, isTextEntry } from "../src/desktop/mobile";
import { contextMenuEdit } from "../src/desktop/clipboard";

const win = window as Window & typeof globalThis;
let stop: () => void;
let clock = 1_000;
const now = () => clock;
beforeEach(() => {
  clock = 1_000;
  document.body.innerHTML = "";
});
afterEach(() => stop?.());

const touch = (el: Element) => el.dispatchEvent(new Event("pointerdown", { bubbles: true }));

it("recognizes text fields and contenteditable, not buttons or checkboxes", () => {
  const make = (html: string) => {
    document.body.innerHTML = html;
    return document.body.firstElementChild;
  };
  expect(isTextEntry(make("<textarea></textarea>"))).toBe(true);
  expect(isTextEntry(make('<input type="search">'))).toBe(true);
  expect(isTextEntry(make('<input type="checkbox">'))).toBe(false);
  expect(isTextEntry(make('<div contenteditable="true"></div>'))).toBe(true);
  expect(isTextEntry(make('<div contenteditable="false"></div>'))).toBe(false);
  expect(isTextEntry(make("<button></button>"))).toBe(false);
});

it("script focus on a text field is keyboard-less until the user touches a field", () => {
  stop = installKeyboardGuard(win, now);
  document.body.innerHTML = '<textarea id="a"></textarea>';
  const a = document.getElementById("a") as HTMLTextAreaElement;
  a.focus();
  expect(document.activeElement).toBe(a);
  expect(a.getAttribute("inputmode")).toBe("none");
  // The user taps the field itself: the keyboard is allowed again, original attribute restored.
  touch(a);
  expect(a.hasAttribute("inputmode")).toBe(false);
});

it("restores a field's own inputmode instead of dropping it", () => {
  stop = installKeyboardGuard(win, now);
  document.body.innerHTML = '<input id="n" inputmode="numeric">';
  const n = document.getElementById("n") as HTMLInputElement;
  n.focus();
  expect(n.getAttribute("inputmode")).toBe("none");
  touch(n);
  expect(n.getAttribute("inputmode")).toBe("numeric");
});

it("a touch inside the composer allows the focus it triggers, a touch on chat text does not", () => {
  // Fixture mirrors the real DOM: the composer is form[data-slot=composer-root]; the chat surface
  // ([data-composer-target]) around the thread must NOT count as the composer.
  stop = installKeyboardGuard(win, now);
  document.body.innerHTML =
    '<div data-composer-target="main"><p id="text">reply</p></div><form data-slot="composer-root"><button id="send"></button><div data-slot="composer-rich-input" contenteditable="true" id="ed"></div></form><textarea id="edit"></textarea>';
  touch(document.getElementById("text")!);
  const edit = document.getElementById("edit") as HTMLTextAreaElement;
  edit.focus();
  expect(edit.getAttribute("inputmode")).toBe("none");
  edit.blur();
  clock += 2_000;
  touch(document.getElementById("send")!);
  const ed = document.getElementById("ed")!;
  ed.focus();
  expect(ed.hasAttribute("inputmode")).toBe(false);
});

it("intent expires, and refocusing the already-focused field never hides a live keyboard", () => {
  stop = installKeyboardGuard(win, now);
  document.body.innerHTML = '<textarea id="a"></textarea><textarea id="b"></textarea>';
  const [a, b] = ["a", "b"].map((id) => document.getElementById(id) as HTMLTextAreaElement);
  touch(a);
  a.focus();
  expect(a.hasAttribute("inputmode")).toBe(false);
  a.focus(); // already focused: untouched
  expect(a.hasAttribute("inputmode")).toBe(false);
  clock += 5_000;
  b.focus();
  expect(b.getAttribute("inputmode")).toBe("none");
});

it("uninstall puts the original focus() back", () => {
  const original = HTMLElement.prototype.focus;
  const off = installKeyboardGuard(win, now);
  expect(HTMLElement.prototype.focus).not.toBe(original);
  off();
  expect(HTMLElement.prototype.focus).toBe(original);
  stop = () => {};
});

it("tapping the chat area closes the sessions drawer; tapping inside it does not", () => {
  stop = installOverlayDismiss(win);
  document.body.innerHTML =
    '<div data-tree-split><p id="chat">chat</p></div><div data-narrow-overlay="sessions"><button id="row">row</button></div>';
  const seen = vi.fn();
  win.addEventListener("hermes:pane-toggle-reveal", (e) => seen((e as CustomEvent).detail));
  touch(document.getElementById("row")!);
  expect(seen).not.toHaveBeenCalled();
  touch(document.getElementById("chat")!);
  expect(seen).toHaveBeenCalledWith({ id: "sessions", mode: "close" });
});

it("a route change closes the drawer", async () => {
  stop = installOverlayDismiss(win);
  document.body.innerHTML = '<div data-narrow-overlay="sessions"></div>';
  const seen = vi.fn();
  win.addEventListener("hermes:pane-toggle-reveal", (e) => seen((e as CustomEvent).detail));
  history.pushState({}, "", "/#/stored-9");
  await Promise.resolve();
  expect(seen).toHaveBeenCalledWith({ id: "sessions", mode: "close" });
  history.replaceState({}, "", "/");
});

it("pausing the app drops focus from a text field so Home-and-back cannot raise the keyboard", () => {
  stop = installPauseBlur(win);
  document.body.innerHTML = '<textarea id="a">draft</textarea><button id="b"></button>';
  const a = document.getElementById("a") as HTMLTextAreaElement;
  a.focus();
  expect(document.activeElement).toBe(a);
  win.dispatchEvent(new CustomEvent("hermes:native-lifecycle", { detail: { state: "resume" } }));
  expect(document.activeElement).toBe(a);
  win.dispatchEvent(new CustomEvent("hermes:native-lifecycle", { detail: { state: "pause" } }));
  expect(document.activeElement).not.toBe(a);
  expect(a.value).toBe("draft");
  // A non-text control keeps its focus.
  const b = document.getElementById("b") as HTMLButtonElement;
  b.focus();
  win.dispatchEvent(new CustomEvent("hermes:native-lifecycle", { detail: { state: "pause" } }));
  expect(document.activeElement).toBe(b);
});

it("Send from the composer closes the keyboard, even though the send tap counted as composer intent", () => {
  vi.useFakeTimers();
  try {
    stop = installKeyboardGuard(win, now);
    document.body.innerHTML =
      '<form data-slot="composer-root"><div data-slot="composer-rich-input" contenteditable="true" id="ed"></div><button type="submit" id="send"></button></form>';
    const ed = document.getElementById("ed")!;
    const form = document.querySelector("form")!;
    form.addEventListener("submit", (e) => e.preventDefault());
    touch(ed);
    ed.focus();
    expect(document.activeElement).toBe(ed);
    touch(document.getElementById("send")!);
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    // The renderer still sees the focused editor while it handles the submit.
    expect(document.activeElement).toBe(ed);
    vi.advanceTimersByTime(0);
    expect(document.activeElement).not.toBe(ed);
    // An upstream refocus right after sending lands keyboard-less.
    ed.focus();
    expect(ed.getAttribute("inputmode")).toBe("none");
    vi.advanceTimersByTime(400);
    expect(document.activeElement).not.toBe(ed);
  } finally {
    vi.useRealTimers();
  }
});

it("a touch on a sent message does not move focus (mousedown cancelled); mouse input is untouched", () => {
  stop = installBubbleTapFocus(win, now);
  document.body.innerHTML = '<div data-slot="aui_user-bubble-actions"><button id="bubble"><span id="t">hi</span></button></div>';
  const mouse = () => {
    const e = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
    document.getElementById("t")!.dispatchEvent(e);
    return e.defaultPrevented;
  };
  expect(mouse()).toBe(false);
  document.getElementById("t")!.dispatchEvent(new Event("touchstart", { bubbles: true }));
  expect(mouse()).toBe(true);
  clock += 5_000;
  expect(mouse()).toBe(false);
});

it("a touch on a sent message drops focus left in the composer after a keyboard session", () => {
  stop = installBubbleTapFocus(win, now);
  document.body.innerHTML =
    '<div data-slot="aui_user-bubble-actions"><button><span id="t">hi</span></button></div><form data-slot="composer-root"><textarea id="c">draft</textarea></form>';
  const composer = document.getElementById("c") as HTMLTextAreaElement;
  composer.focus();
  document.getElementById("t")!.dispatchEvent(new Event("touchstart", { bubbles: true }));
  expect(document.activeElement).not.toBe(composer);
  expect(composer.value).toBe("draft");
});

describe("long-press text selection (NG-4)", () => {
  // Desktop's app-wide menu listens on window capture after ours (installed later).
  let desktopMenu: ReturnType<typeof vi.fn<(event: Event) => void>>;
  const desktop = (event: Event) => desktopMenu(event);
  beforeEach(() => {
    desktopMenu = vi.fn<(event: Event) => void>();
    stop = installNativeTextSelection(win, now);
    win.addEventListener("contextmenu", desktop, true);
    document.body.innerHTML = `
      <div data-tree-group="g" data-zone-body data-hermes-context-menu-trigger>
        <p id="text">assistant reply</p>
        <form data-slot="composer-root"><div id="composer" contenteditable="true">draft</div></form>
        <a id="link" href="https://example.org">link</a>
        <div data-context-menu-skip><button id="bubble">sent</button></div>
      </div>
      <div data-slot="context-menu-trigger"><span id="row">session row</span></div>`;
  });
  afterEach(() => win.removeEventListener("contextmenu", desktop, true));
  const hold = (id: string, pointerType?: string) => {
    const el = document.getElementById(id)!;
    if (pointerType === undefined) el.dispatchEvent(new Event("touchstart", { bubbles: true }));
    const event = Object.assign(new MouseEvent("contextmenu", { bubbles: true, cancelable: true }), pointerType ? { pointerType } : {});
    el.dispatchEvent(event);
    el.dispatchEvent(new Event("touchend", { bubbles: true }));
    return event;
  };

  it("a finger long-press on the composer or chat text goes to Android, not Desktop's menu", () => {
    for (const id of ["composer", "text"]) {
      const event = hold(id);
      expect(event.defaultPrevented).toBe(false);
    }
    expect(hold("composer", "touch").defaultPrevented).toBe(false);
    expect(desktopMenu).not.toHaveBeenCalled();
  });

  it("links, the reaction picker and row menus keep Desktop's long-press; a mouse right-click keeps Desktop's menu", () => {
    for (const id of ["link", "bubble", "row"]) hold(id);
    expect(desktopMenu).toHaveBeenCalledTimes(3);
    clock += 5_000;
    hold("composer", "mouse");
    expect(desktopMenu).toHaveBeenCalledTimes(4);
  });

  it("a right-click long after the last touch is a mouse", () => {
    document.getElementById("text")!.dispatchEvent(new Event("touchstart", { bubbles: true }));
    document.getElementById("text")!.dispatchEvent(new Event("touchend", { bubbles: true }));
    clock += 5_000;
    document.getElementById("text")!.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
    expect(desktopMenu).toHaveBeenCalledTimes(1);
  });

  it("Android owns text menus even when WebView reports a mouse pointer or no recent touch", () => {
    document.documentElement.dataset.androidTouch = "";
    try {
      clock += 5_000;
      hold("composer", "mouse");
      document.getElementById("text")!.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
      expect(desktopMenu).not.toHaveBeenCalled();
      hold("row", "touch");
      expect(desktopMenu).toHaveBeenCalledTimes(1);
    } finally {
      delete document.documentElement.dataset.androidTouch;
    }
  });

  it("selected text inside a sent-message reaction wrapper also belongs to Android", () => {
    document.documentElement.dataset.androidTouch = "";
    const bubble = document.getElementById("bubble")!;
    const range = document.createRange();
    range.selectNodeContents(bubble);
    window.getSelection()!.addRange(range);
    try {
      expect(hold("bubble", "touch").defaultPrevented).toBe(false);
      expect(desktopMenu).not.toHaveBeenCalled();
    } finally {
      window.getSelection()!.removeAllRanges();
      delete document.documentElement.dataset.androidTouch;
    }
  });
});

describe("Desktop's edit menu on Android (contextMenuEdit)", () => {
  it("copy and cut run the page's own edit command; paste inserts the clipboard text", async () => {
    const exec = vi.fn(() => true);
    const doc = { execCommand: exec } as unknown as Document;
    await contextMenuEdit("copy", doc);
    await contextMenuEdit("cut", doc);
    const clipboard = { readText: vi.fn(async () => "pasted") };
    Object.defineProperty(navigator, "clipboard", { value: clipboard, configurable: true });
    try {
      await contextMenuEdit("paste", doc);
      clipboard.readText.mockRejectedValueOnce(new Error("NotAllowedError"));
      await contextMenuEdit("paste", doc);
    } finally {
      Reflect.deleteProperty(navigator, "clipboard");
    }
    expect(exec.mock.calls).toEqual([["copy"], ["cut"], ["insertText", false, "pasted"]]);
  });
});

describe("Back closes the browser pane on a phone (R1 stage 1)", () => {
  const back = () => {
    const event = new Event("hermes:native-back", { cancelable: true });
    win.dispatchEvent(event);
    return event.defaultPrevented;
  };
  beforeEach(() => {
    stop = installPaneBack(win);
    Object.defineProperty(win, "innerWidth", { value: 412, configurable: true });
    document.body.innerHTML = '<div data-pane-host="preview-tile:t1"><button id="reload"><i class="codicon codicon-refresh"></i></button><button id="close"><i class="codicon codicon-close"></i></button></div>';
  });

  it("clicks Desktop's own Close button and claims Back", () => {
    const close = vi.fn();
    document.getElementById("close")!.addEventListener("click", close);
    expect(back()).toBe(true);
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("closes a file, PDF or image preview with the active preview tab's Close (no pane host)", () => {
    document.body.innerHTML =
      '<div data-tree-tab="preview-tile:old" aria-selected="false"><button id="old"><i class="codicon codicon-close"></i></button></div>' +
      '<div data-tree-tab="preview-tile:file1" aria-selected="true"><button id="tabclose"><i class="codicon codicon-close"></i></button></div>' +
      '<div data-tree-tab="workspace" aria-selected="false"><button id="other"><i class="codicon codicon-close"></i></button></div>';
    const closed = vi.fn(), other = vi.fn();
    document.getElementById("tabclose")!.addEventListener("click", closed);
    document.getElementById("old")!.addEventListener("click", other);
    document.getElementById("other")!.addEventListener("click", other);
    expect(back()).toBe(true);
    expect(closed).toHaveBeenCalledTimes(1);
    expect(other).not.toHaveBeenCalled();
    // No preview tab selected: Back is not claimed.
    document.querySelector('[data-tree-tab="preview-tile:file1"]')!.setAttribute("aria-selected", "false");
    expect(back()).toBe(false);
  });

  it("leaves Back alone with a menu or dialog open, a hidden pane, or a wide screen", () => {
    document.body.insertAdjacentHTML("beforeend", '<div role="menu"></div>');
    expect(back()).toBe(false);
    document.querySelector('[role="menu"]')!.remove();
    document.querySelector("[data-pane-host]")!.setAttribute("inert", "");
    expect(back()).toBe(false);
    document.querySelector("[data-pane-host]")!.removeAttribute("inert");
    Object.defineProperty(win, "innerWidth", { value: 900, configurable: true });
    expect(back()).toBe(false);
  });
});
