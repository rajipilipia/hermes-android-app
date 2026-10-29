// Android-only build adapter: lets the phone keyboard (Gboard and others) work natively in the
// Desktop composers. Vendor bytes stay unchanged; exact-match guards fail the build if the
// Desktop source moves. Every change is gated on html[data-android-touch] (set by installMobile
// before the renderer starts), so mouse/keyboard Desktop behavior is byte-for-byte the same.
//   - spellcheck, autocorrect and sentence capitals ON: Gboard underlines and suggests words.
//   - enterkeyhint="enter" and Enter inserts a new line; the Send button sends (phone pattern).
//   - Gboard keeps the current word "composing" until a space. Desktop skipped every input event
//     while composing, so the Send button stayed hidden after one word. On touch the plain text
//     is synced to state during composition (no DOM rewrite, so the IME is not disturbed), and a
//     Send tap commits the word first (main composer: blur, so Chromium ends the composition;
//     edit box: it closes on blur, so the flag is cleared and the visible word is sent).
const TOUCH = 'document.documentElement.hasAttribute("data-android-touch")';

function replaceOnce(code: string, before: string, after: string, label: string): string {
  if (code.split(before).length !== 2) throw new Error(`Android ${label} adapter: pinned Desktop source changed.`);
  return code.replace(before, after);
}

const nativeTypingAttributes = (code: string, indent: string, ariaLabel: string, label: string) => {
  code = replaceOnce(code, `${indent}aria-label={${ariaLabel}}\n${indent}autoCapitalize="off"\n`,
    `${indent}aria-label={${ariaLabel}}\n${indent}autoCapitalize={${TOUCH} ? 'sentences' : 'off'}\n`, `${label} capitals`);
  code = replaceOnce(code, `${indent}autoCorrect={isMacPlatform() ? 'on' : 'off'}`, `${indent}autoCorrect={${TOUCH} || isMacPlatform() ? 'on' : 'off'}`, `${label} autocorrect`);
  return replaceOnce(code, `${indent}spellCheck={false}\n${indent}suppressContentEditableWarning`,
    `${indent}enterKeyHint={${TOUCH} ? 'enter' : undefined}\n${indent}spellCheck={${TOUCH}}\n${indent}suppressContentEditableWarning`, `${label} spellcheck`);
};

export function patchComposerNativeSource(id: string, source: string): string | undefined {
  const file = id.replaceAll("\\", "/").split("?")[0];
  let code = source;
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/chat/composer/index.tsx")) {
    code = nativeTypingAttributes(code, "        ", "t.composer.message", "composer");
    code = replaceOnce(code, "    if (event.key === 'Enter' && !event.shiftKey) {\n      event.preventDefault()\n\n      // Decide from the DOM",
      `    if (event.key === 'Enter' && !event.shiftKey && !${TOUCH}) {\n      event.preventDefault()\n\n      // Decide from the DOM`, "composer enter");
    code = replaceOnce(code, `    if (composingRef.current) {
      return
    }

    scheduleFlushEditorToDraft(event.currentTarget)`, `    if (composingRef.current) {
      if (${TOUCH}) {
        const composingDraft = sanitizeComposerInput(composerPlainText(event.currentTarget))

        if (composingDraft !== draftRef.current) {
          draftRef.current = composingDraft
          setComposerText(composingDraft)
        }
      }

      return
    }

    scheduleFlushEditorToDraft(event.currentTarget)`, "composer composing sync");
    return replaceOnce(code, `            onSubmit={e => {
              e.preventDefault()

              if (composingRef.current) {`, `            onSubmit={e => {
              e.preventDefault()

              if (composingRef.current && ${TOUCH}) {
                editorRef.current?.blur()
              }

              if (composingRef.current) {`, "composer send commit");
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/components/assistant-ui/thread/user-edit-composer.tsx")) {
    code = nativeTypingAttributes(code, "              ", "copy.editMessage", "edit composer");
    code = replaceOnce(code, `    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submitEdit(event.currentTarget)`, `    if (event.key === 'Enter' && !event.shiftKey && !${TOUCH}) {
      event.preventDefault()
      submitEdit(event.currentTarget)`, "edit composer enter");
    return replaceOnce(code, `  const submitEdit = (editor: HTMLDivElement) => {
    if (composingRef.current) {`, `  const submitEdit = (editor: HTMLDivElement) => {
    // The edit box closes on blur, so commit by hand: the preedit word is visible text here.
    if (composingRef.current && ${TOUCH}) {
      composingRef.current = false
    }

    if (composingRef.current) {`, "edit composer send commit");
  }
  return undefined;
}
