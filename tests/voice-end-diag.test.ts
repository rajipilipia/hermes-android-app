import { describe, expect, it } from "vitest";
import fs from "node:fs";
import { patchVoiceEndDiagnostics } from "../src/desktop/voice-end-diag";

const vendor = (rel: string) => {
  const id = `/x/vendor/hermes/apps/desktop/src/${rel}`;
  return { id, code: fs.readFileSync(`vendor/hermes/apps/desktop/src/${rel}`, "utf8") };
};

describe("voice call end diagnostics", () => {
  it("names the toggle and the end control, and adds only log lines", () => {
    const { id, code } = vendor("app/chat/composer/hooks/use-composer-voice.ts");
    const out = patchVoiceEndDiagnostics(id, code)!;
    expect(out).toContain("voice_end source=toggle");
    expect(out).toContain("voice_end source=end_control");
    // Besides log lines, the only addition is the Android notification End listener (own block).
    const before = code.split("\n");
    const block = out.slice(out.indexOf("  useEffect(() => {\n    if (target !== 'main') {return}\n\n    const onAndroidEnd"));
    const listener = block.slice(0, block.indexOf("[endConversation, target])") + "[endConversation, target])".length).split("\n");
    const added = out.split("\n").filter((line) => !before.includes(line) && !listener.includes(line));
    expect(added.length).toBeGreaterThan(0);
    expect(added.every((line) => line.includes("[hermes-diag] voice_end"))).toBe(true);
  });

  it("names a stop phrase that reached the chat as text", () => {
    const { id, code } = vendor("app/chat/composer/hooks/use-middleware-submit.ts");
    expect(patchVoiceEndDiagnostics(id, code)).toContain("voice_end source=stop_phrase_text");
  });

  it("copies every Codex Live event to logcat before the PC debug opt-in check", () => {
    const { id, code } = vendor("lib/voice-live-debug.ts");
    const out = patchVoiceEndDiagnostics(id, code)!;
    expect(out.indexOf("[hermes-diag] live ")).toBeLessThan(out.indexOf("if (!this.connection || this.closing"));
    // The call on/off report also runs before that opt-in check (it must work with the sink off).
    expect(out.indexOf("androidVoiceCall(true)")).toBeLessThan(out.indexOf("if (!this.connection || this.closing"));
  });

  it("logs and ends a call that native refused to start", () => {
    const { id, code } = vendor("lib/voice-live-debug.ts");
    const out = patchVoiceEndDiagnostics(id, code)!;
    expect(out).toContain("[hermes-diag] voice_call start_refused");
    expect(out).toContain("window.dispatchEvent(new Event('hermes:android-voice-end'))");
  });

  it("fails the build when the pinned Desktop source moves", () => {
    const { id } = vendor("app/chat/composer/hooks/use-middleware-submit.ts");
    expect(() => patchVoiceEndDiagnostics(id, "export const x = 1")).toThrow(/pinned Desktop source changed/);
  });
});
