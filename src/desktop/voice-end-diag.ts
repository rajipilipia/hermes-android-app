// Android build adapter for voice calls. (1) Names which Desktop path ended a call: Desktop's
// Codex Live log records every user-side end as "requested", so the End button, the voice toggle
// and a stop phrase that reached the chat as text look the same. (2) Copies every Codex Live
// lifecycle event to logcat. Closed-vocabulary words and numbers only (no text, no ids).
// (3) Background calls: tells native when a Codex Live call really opened / ended (native then
// runs the microphone service with the "Hermes call" notification), and lets that notification's
// End action end the call through Desktop's own end control. Vendor bytes stay unchanged and
// exact-match guards fail the build if Desktop moves.
function replaceOnce(code: string, before: string, after: string, label: string): string {
  if (code.split(before).length !== 2) throw new Error(`Android ${label} adapter: pinned Desktop source changed.`);
  return code.replace(before, after);
}

// Counts open calls so a late stop of an old session never ends a newer call. Native replies
// {"ok":true} when the microphone service runs. A not-ok reply to "start" ends the call.
const ANDROID_CALL_HELPER = `let androidCalls = 0
function androidVoiceCall(active: boolean): void {
  androidCalls = Math.max(0, androidCalls + (active ? 1 : -1))

  if (androidCalls !== (active ? 1 : 0)) {return}

  try {
    const reply = window.prompt('hermes.android.call.v1', JSON.stringify({ active }))
    const ok = String(reply ?? '').includes('true')
    console.log('[hermes-diag] voice_call active=' + active + ' ok=' + ok)

    // Native refused (Hermes left the foreground): end the call, do not leave it open but deaf.
    // A null reply means no native bridge at all, so the call keeps working.
    if (active && reply !== null && !ok) {
      console.log('[hermes-diag] voice_call start_refused')
      window.dispatchEvent(new Event('hermes:android-voice-end'))
    }
  } catch {
    // Native unavailable: the call still works in the foreground.
  }
}
`;

// The "Hermes call" notification End action: native dispatches this window event.
const ANDROID_END_LISTENER = `  useEffect(() => {
    if (target !== 'main') {return}

    const onAndroidEnd = () => {
      console.log('[hermes-diag] voice_end source=android_notification')
      endConversation()
    }

    window.addEventListener('hermes:android-voice-end', onAndroidEnd)

    return () => window.removeEventListener('hermes:android-voice-end', onAndroidEnd)
  }, [endConversation, target])
`;

export function patchVoiceEndDiagnostics(id: string, source: string): string | undefined {
  const file = id.replaceAll("\\", "/").split("?")[0];
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/chat/composer/hooks/use-composer-voice.ts")) {
    let code = replaceOnce(source, `    if (voiceConversationActive) {
      setVoiceConversationActive(false)
      void conversation.end()`, `    if (voiceConversationActive) {
      console.log('[hermes-diag] voice_end source=toggle')
      setVoiceConversationActive(false)
      void conversation.end()`, "voice end toggle diag");
    code = replaceOnce(code, `  const endConversation = useCallback(() => {
    setVoiceConversationActive(false)`, `  const endConversation = useCallback(() => {
    console.log('[hermes-diag] voice_end source=end_control')
    setVoiceConversationActive(false)`, "voice end control diag");
    code = replaceOnce(code, `  const handleToggleAutoSpeak = useCallback(() => {`, `${ANDROID_END_LISTENER}
  const handleToggleAutoSpeak = useCallback(() => {`, "voice end notification action");
    return code;
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/lib/voice-live-debug.ts")) {
    // Every Codex Live event (closed vocabulary only) also goes to logcat, even when the PC's
    // debug sink is off, so a phone call can always be traced.
    let code = replaceOnce(source, `    if (!this.connection || this.closing || this.queue.length >= 100) {return}
    const event = metadata(input)`, `    const androidEvent = metadata(input)
    if (androidEvent) {console.log('[hermes-diag] live ' + Object.entries(androidEvent).map(([key, value]) => key + '=' + String(value)).join(' '))}
    if (androidEvent?.event === 'data_channel.state' && androidEvent.state === 'open' && !this.androidCall) {this.androidCall = true; androidVoiceCall(true)}
    if (androidEvent?.event === 'lifecycle.stop' && this.androidCall) {this.androidCall = false; androidVoiceCall(false)}
    if (!this.connection || this.closing || this.queue.length >= 100) {return}
    const event = metadata(input)`, "voice live event diag");
    code = replaceOnce(code, `  private closing = false
`, `  private closing = false
  private androidCall = false
`, "voice live call flag");
    return replaceOnce(code, `const EVENTS = new Set([`, `${ANDROID_CALL_HELPER}
const EVENTS = new Set([`, "voice live call helper");
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/chat/composer/hooks/use-middleware-submit.ts")) {
    return replaceOnce(source, `        voiceStop.end()
`, `        console.log('[hermes-diag] voice_end source=stop_phrase_text')
        voiceStop.end()
`, "voice end stop phrase diag");
  }
  return undefined;
}
