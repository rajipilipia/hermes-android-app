import { describe, expect, it } from "vitest";
import fs from "node:fs";
import { patchComposerNativeSource } from "../src/desktop/composer-native";

const vendor = (rel: string) => {
  const id = `/x/vendor/hermes/apps/desktop/src/${rel}`;
  return { id, code: fs.readFileSync(`vendor/hermes/apps/desktop/src/${rel}`, "utf8") };
};
const TOUCH = 'document.documentElement.hasAttribute("data-android-touch")';

describe("native phone typing in the Desktop composers", () => {
  for (const rel of ["app/chat/composer/index.tsx", "components/assistant-ui/thread/user-edit-composer.tsx"]) {
    it(`turns on spellcheck, autocorrect, capitals and Enter-for-newline on touch only: ${rel}`, () => {
      const { id, code } = vendor(rel);
      const out = patchComposerNativeSource(id, code)!;
      expect(out).toContain(`spellCheck={${TOUCH}}`);
      expect(out).toContain(`autoCorrect={${TOUCH} || isMacPlatform() ? 'on' : 'off'}`);
      expect(out).toContain(`autoCapitalize={${TOUCH} ? 'sentences' : 'off'}`);
      expect(out).toContain(`enterKeyHint={${TOUCH} ? 'enter' : undefined}`);
      expect(out).toContain(`event.key === 'Enter' && !event.shiftKey && !${TOUCH}`);
      // Nothing else in the file changes: only lines carrying the touch gate differ.
      const before = code.split("\n");
      const changed = out.split("\n").filter((line) => !before.includes(line));
      expect(changed.length).toBeGreaterThan(0);
      expect(changed.every((line) => line.includes(TOUCH) || /^\s*(\}|editorRef|composingRef|const composingDraft|if \(composingDraft|draftRef|setComposerText|\/\/|$)/.test(line))).toBe(true);
    });
  }

  it("keeps the main composer's Send working while Gboard is still composing a word", () => {
    const { id, code } = vendor("app/chat/composer/index.tsx");
    const out = patchComposerNativeSource(id, code)!;
    expect(out).toMatch(/if \(composingRef\.current\) \{\n\s+if \(document\.documentElement\.hasAttribute\("data-android-touch"\)\) \{\n\s+const composingDraft = sanitizeComposerInput\(composerPlainText\(event\.currentTarget\)\)/);
    expect(out).toContain(`if (composingRef.current && ${TOUCH}) {\n                editorRef.current?.blur()`);
  });

  it("fails the build when the pinned Desktop source moves", () => {
    const { id } = vendor("app/chat/composer/index.tsx");
    expect(() => patchComposerNativeSource(id, "export const x = 1")).toThrow(/pinned Desktop source changed/);
  });

  it("leaves every other file alone", () => {
    expect(patchComposerNativeSource("/x/vendor/hermes/apps/desktop/src/app/other.tsx", "x")).toBeUndefined();
  });
});
