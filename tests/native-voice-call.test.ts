import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import { patchVoiceEndDiagnostics } from "../src/desktop/voice-end-diag";

const vendor = (rel: string) => {
  const id = `/x/vendor/hermes/apps/desktop/src/${rel}`;
  return { id, code: readFileSync(`vendor/hermes/apps/desktop/src/${rel}`, "utf8") };
};

function lifecycleWindow() {
  const stops: number[] = [];
  let pauses = 0;
  const callbacks: Record<string, () => void> = {};
  const events: string[] = [];
  let next = 0;
  const window: any = {
    navigator: { mediaDevices: { getUserMedia: () => Promise.resolve({ getTracks: () => { const id = next++; return [{ stop: () => { stops.push(id); }, addEventListener: () => {} }]; } }) } },
    document: { visibilityState: "visible", querySelectorAll: () => [{ pause: () => { pauses++; } }], addEventListener: (name: string, fn: () => void) => { callbacks[name] = fn; } },
    speechSynthesis: { cancel: () => {} },
    dispatchEvent: (e: any) => { events.push(e.options.detail.state); },
    CustomEvent: class { constructor(public type: string, public options: any) {} },
    DOMException,
  };
  window.window = window; window.top = window;
  vm.runInNewContext(readFileSync("android/assets/native-lifecycle.js", "utf8"), window);
  return { window, stops, callbacks, events, pauses: () => pauses };
}

describe("background Codex Live call: native lifecycle", () => {
  it("keeps the microphone and audio during a call, then applies the pause rules when it ends", async () => {
    const t = lifecycleWindow();
    t.window.__hermesNativeLifecycle("resume");
    await t.window.navigator.mediaDevices.getUserMedia({ audio: true });
    t.window.__hermesNativeLifecycle("call-on");
    t.window.__hermesNativeLifecycle("pause");
    t.window.document.visibilityState = "hidden"; t.callbacks.visibilitychange();
    expect(t.stops).toEqual([]);
    expect(t.pauses()).toBe(0);
    // Other code still hears pause, and new recordings are still refused in the background.
    expect(t.events).toEqual(["resume", "pause", "pause"]);
    await expect(t.window.navigator.mediaDevices.getUserMedia({ audio: true })).rejects.toMatchObject({ name: "NotAllowedError" });
    t.window.__hermesNativeLifecycle("call-off");
    expect(t.stops).toEqual([0]);
    expect(t.pauses()).toBe(1);
  });

  it("without a call, pause still stops the microphone (privacy rule unchanged)", async () => {
    const t = lifecycleWindow();
    t.window.__hermesNativeLifecycle("resume");
    await t.window.navigator.mediaDevices.getUserMedia({ audio: true });
    t.window.__hermesNativeLifecycle("pause");
    expect(t.stops).toEqual([0]);
    expect(t.pauses()).toBe(1);
  });

  it("a call that ends in the foreground keeps the microphone rules for the next pause", async () => {
    const t = lifecycleWindow();
    t.window.__hermesNativeLifecycle("resume");
    t.window.__hermesNativeLifecycle("call-on");
    t.window.__hermesNativeLifecycle("call-off");
    await t.window.navigator.mediaDevices.getUserMedia({ audio: true });
    expect(t.stops).toEqual([]);
    t.window.__hermesNativeLifecycle("pause");
    expect(t.stops).toEqual([0]);
  });

  it("ignores unknown states and does not fire lifecycle events for call flags", () => {
    const t = lifecycleWindow();
    t.window.__hermesNativeLifecycle("resume");
    t.window.__hermesNativeLifecycle("call-on");
    t.window.__hermesNativeLifecycle("bogus");
    expect(t.events).toEqual(["resume"]);
  });
});

describe("background Codex Live call: renderer adapter", () => {
  it("reports call on at data channel open and off at stop, once per call, newest call wins", () => {
    const { id, code } = vendor("lib/voice-live-debug.ts");
    const out = patchVoiceEndDiagnostics(id, code)!;
    const js = ts.transpileModule(out, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
    const prompts: string[] = [];
    const sandbox: any = { exports: {}, console: { log: () => {} }, window: { prompt: (name: string, value: string) => { prompts.push(name + " " + value); return '{"ok":true}'; } } };
    vm.runInNewContext(js, sandbox);
    const { CodexLiveDiagnostics } = sandbox.exports;
    const first = new CodexLiveDiagnostics(false, async () => {});
    const second = new CodexLiveDiagnostics(false, async () => {});
    first.record({ event: "lifecycle.start" });
    first.record({ event: "data_channel.state", state: "connecting" });
    expect(prompts).toEqual([]);
    first.record({ event: "data_channel.state", state: "open" });
    first.record({ event: "data_channel.state", state: "open" });
    expect(prompts).toEqual(['hermes.android.call.v1 {"active":true}']);
    // A new call opens, then the old one stops late: the new call must stay on.
    second.record({ event: "data_channel.state", state: "open" });
    first.record({ event: "lifecycle.stop" });
    expect(prompts).toHaveLength(1);
    second.record({ event: "lifecycle.stop" });
    expect(prompts).toEqual(['hermes.android.call.v1 {"active":true}', 'hermes.android.call.v1 {"active":false}']);
    // A call that never opened sends nothing.
    const failed = new CodexLiveDiagnostics(false, async () => {});
    failed.record({ event: "lifecycle.stop" });
    expect(prompts).toHaveLength(2);
  });

  it("ends the call cleanly when native refuses to start the microphone service", () => {
    const { id, code } = vendor("lib/voice-live-debug.ts");
    const js = ts.transpileModule(patchVoiceEndDiagnostics(id, code)!, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
    const run = (reply: string | null) => {
      const logs: string[] = [];
      const events: string[] = [];
      const sandbox: any = {
        exports: {},
        Event: class { constructor(public type: string) {} },
        console: { log: (line: string) => { logs.push(line); } },
        window: { prompt: () => reply, dispatchEvent: (e: { type: string }) => { events.push(e.type); } },
      };
      vm.runInNewContext(js, sandbox);
      const call = new sandbox.exports.CodexLiveDiagnostics(false, async () => {});
      call.record({ event: "data_channel.state", state: "open" });
      return { logs, events };
    };
    const refused = run('{"ok":false}');
    expect(refused.events).toEqual(["hermes:android-voice-end"]);
    expect(refused.logs).toContain("[hermes-diag] voice_call start_refused");
    // Started fine, or no native bridge at all (null): the call is left alone.
    expect(run('{"ok":true}').events).toEqual([]);
    expect(run(null).events).toEqual([]);
  });

  it("a refused stop (active=false) never ends anything", () => {
    const { id, code } = vendor("lib/voice-live-debug.ts");
    const js = ts.transpileModule(patchVoiceEndDiagnostics(id, code)!, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
    const events: string[] = [];
    const sandbox: any = {
      exports: {},
      Event: class { constructor(public type: string) {} },
      console: { log: () => {} },
      window: { prompt: (_n: string, value: string) => (value.includes("true") ? '{"ok":true}' : '{"ok":false}'), dispatchEvent: (e: { type: string }) => { events.push(e.type); } },
    };
    vm.runInNewContext(js, sandbox);
    const call = new sandbox.exports.CodexLiveDiagnostics(false, async () => {});
    call.record({ event: "data_channel.state", state: "open" });
    call.record({ event: "lifecycle.stop" });
    expect(events).toEqual([]);
  });

  it("survives a missing native prompt", () => {
    const { id, code } = vendor("lib/voice-live-debug.ts");
    const js = ts.transpileModule(patchVoiceEndDiagnostics(id, code)!, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
    const sandbox: any = { exports: {}, console: { log: () => {} }, window: { prompt: () => { throw new Error("none"); } } };
    vm.runInNewContext(js, sandbox);
    const call = new sandbox.exports.CodexLiveDiagnostics(false, async () => {});
    expect(() => call.record({ event: "data_channel.state", state: "open" })).not.toThrow();
  });

  it("the notification End action ends the call through Desktop's own end control", () => {
    const { id, code } = vendor("app/chat/composer/hooks/use-composer-voice.ts");
    const out = patchVoiceEndDiagnostics(id, code)!;
    expect(out).toContain("window.addEventListener('hermes:android-voice-end', onAndroidEnd)");
    expect(out).toContain("window.removeEventListener('hermes:android-voice-end', onAndroidEnd)");
    // The listener sits after endConversation is defined (no use-before-define).
    expect(out.indexOf("const endConversation = useCallback")).toBeLessThan(out.indexOf("hermes:android-voice-end"));
    expect(out.match(/hermes:android-voice-end/g)!.length).toBe(2);
  });
});

describe("background Codex Live call: native wiring", () => {
  const java = readFileSync("android/src/us/pilipia/hermes/prototype/MainActivity.java", "utf8");
  const chrome = readFileSync("android/src/us/pilipia/hermes/prototype/DesktopChromeClient.java", "utf8");
  const service = readFileSync("android/src/us/pilipia/hermes/prototype/VoiceCallService.java", "utf8");
  const manifest = readFileSync("android/AndroidManifest.xml", "utf8");

  it("declares the microphone service only with its permission", () => {
    expect(manifest).toContain('android.permission.FOREGROUND_SERVICE_MICROPHONE');
    expect(manifest).toMatch(/<service android:name="\.VoiceCallService" android:exported="false" android:foregroundServiceType="microphone" android:stopWithTask="true"\/>/);
    expect(manifest).toContain("android.permission.RECORD_AUDIO");
  });

  it("starts the service from the page prompt, ends it on every exit path", () => {
    expect(chrome).toContain('"hermes.android.call.v1".equals(message)');
    expect(java).toContain("public boolean call(boolean active)");
    // Page replaced, Activity destroyed and the End action all stop the call.
    expect(java).toMatch(/work\.turn\(false,false\);stopCall\(\);/);
    expect(java).toMatch(/event=activity_destroy"\);stopCall\(\);/);
    expect(java).toContain("endCallFromNotification");
    // WebView.onPause() would mute the call audio, so it is skipped only while a call runs.
    expect(java).toContain("web.onPause();if(browser!=null)browser.pause();");
    expect(java).toContain("!(voiceCall!=null&&voiceCall.active()))web.onPause()");
  });

  it("the service is a microphone foreground service with an End action and no restart", () => {
    expect(service).toContain("FOREGROUND_SERVICE_TYPE_MICROPHONE");
    expect(service).toContain('"Hermes call"');
    expect(service).toContain('"End"');
    expect(service).toContain("START_NOT_STICKY");
    expect(service).toContain("onTaskRemoved");
  });
});

describe("F12: skills and plugins catalog host", () => {
  it("is allowed in connect-src in both page security rules and nowhere else", () => {
    const html = readFileSync("index.html", "utf8");
    const java = readFileSync("android/src/us/pilipia/hermes/prototype/MainActivity.java", "utf8");
    for (const source of [html, java]) {
      const rule = source.match(/connect-src[^;]*;/)![0];
      expect(rule).toContain("https://nousresearch.github.io");
      expect(rule).toContain("'self' wss:");
      expect(source.match(/nousresearch\.github\.io/g)!.length).toBe(1);
    }
    expect(html).toMatch(/default-src 'self'; script-src 'self' 'wasm-unsafe-eval'/);
  });
});
