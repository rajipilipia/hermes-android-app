import { hermesApiAs, type OwnerScope, ownerScoped, profileScoped, resolveOwnerNow } from '@/api/client'
import { hermesApi } from '@/hermes'

import { type CodexLiveEvent, codexLiveResult, CodexLiveTranscript } from './voice-live-codex'
import { CodexLiveDiagnostics, type VoiceLiveCloseDetails } from './voice-live-debug'
import { codexContextChunks, type VoiceHandoff } from './voice-live-task'

/**
 * GPT-Live voice chat: the full-duplex voice frontend that DELEGATES to Hermes.
 *
 * `voice.voice_chat_mode: gpt-live` swaps the chained mic → STT → turn → TTS
 * loop for one OpenAI voice model (`gpt-live-1`) that listens and speaks at
 * the same time over WebRTC and has no tools of its own. Whenever the user
 * asks for real work it emits `session.delegation.created`; the desktop turns
 * that into an ordinary Hermes turn on the open session and streams the reply
 * back with `session.commentary.append`, which the voice paraphrases aloud.
 * Hermes keeps every capability — model choice, tools, memory, approvals.
 *
 * This module owns the transport only: session creation via the gateway
 * (the OpenAI key never reaches the renderer), the RTCPeerConnection, the
 * `oai-events` data channel, transcript accumulation and the command
 * surface the conversation hook drives. Vendor contract:
 * https://developers.openai.com/api/docs/guides/live-delegation
 */

export type VoiceChatMode = 'chained' | 'gpt-live' | 'codex-live'
export type VoiceLiveProtocol = Exclude<VoiceChatMode, 'chained'>

export function isLiveVoiceMode(mode: unknown): mode is VoiceLiveProtocol {
  return mode === 'gpt-live' || mode === 'codex-live'
}

export interface VoiceLiveStatus {
  mode: VoiceChatMode
  available: boolean
  reason: null | string
  model: string
  voice: string
  debug?: boolean
}

export interface LiveHistoryMessage {
  type: 'message'
  role: 'assistant' | 'developer' | 'user'
  content: Array<{ type: 'input_text' | 'output_text'; text: string }>
}

interface LiveServerEvent extends CodexLiveEvent {
  type: string
  event_id?: string
  client_event_id?: string
  delta?: string
  start_ms?: number
  end_ms?: number
  delegation?: { id: string; type: string; target: string }
  error?: { type?: string; code?: null | string; message?: string; client_event_id?: string }
  usage?: { seconds?: number }
  reason?: string
  session?: { id: string }
}

export interface LiveTranscriptFragment {
  /** Present for cumulative Codex turn snapshots, absent for GPT deltas. */
  turnId?: string
  final?: boolean
  speaker: 'assistant' | 'user'
  text: string
  startMs: number
  endMs: number
}

export interface VoiceLiveHandlers {
  /** GPT-Live asked the backend (Hermes) for help. `context` is the recent
   *  transcript window, newest last — the delegation itself carries no text. */
  onDelegation: (delegationId: string, context: LiveTranscriptFragment[], handoff?: VoiceHandoff) => void
  /** Vendor-side error. `fatal` when the session is gone. */
  onError: (message: string, fatal: boolean) => void
  /** `session.closed` arrived (or the transport dropped without it). */
  onClosed: (reason: string, usageSeconds: null | number) => void
  /** Transcript deltas, for captions / live UI. */
  onTranscript?: (fragment: LiveTranscriptFragment) => void
  /** Assistant audio output level hint: the remote track is speaking. */
  onSpeakingChange?: (speaking: boolean) => void
}

const CLOSE_TIMEOUT_MS = 15_000
const ICE_GATHER_TIMEOUT_MS = 10_000
// Vendor cap: 500 tokens per append. ~4 chars/token, keep headroom.
const APPEND_CHAR_LIMIT = 1_400
// How much conversation the backend receives per delegation.
const CONTEXT_WINDOW_MS = 5 * 60_000
const CONTEXT_MAX_FRAGMENTS = 80

export async function fetchVoiceLiveStatus(owner?: OwnerScope): Promise<null | VoiceLiveStatus> {
  try {
    const response = await hermesApi<{ ok: boolean } & VoiceLiveStatus>({
      ...(owner ? ownerScoped(owner) : profileScoped()),
      path: '/api/audio/voice-live/status'
    })

    if (!response?.ok) {
      return null
    }

    return {
      available: Boolean(response.available),
      mode: isLiveVoiceMode(response.mode) ? response.mode : 'chained',
      model: response.model,
      reason: response.reason ?? null,
      voice: response.voice,
      debug: response.mode === 'codex-live' && response.debug === true
    }
  } catch {
    // Older backend without the endpoint → chained.
    return null
  }
}

/** Split a reply into append-sized chunks on sentence boundaries. */
export function chunkForCommentary(text: string, limit = APPEND_CHAR_LIMIT): string[] {
  const clean = text.replace(/\s+/g, ' ').trim()

  if (!clean) {
    return []
  }

  if (clean.length <= limit) {
    return [clean]
  }

  const chunks: string[] = []
  let current = ''

  for (const sentence of clean.split(/(?<=[.!?])\s+/)) {
    if (sentence.length > limit) {
      if (current) {
        chunks.push(current)
        current = ''
      }

      for (let index = 0; index < sentence.length; index += limit) {
        chunks.push(sentence.slice(index, index + limit))
      }

      continue
    }

    const candidate = current ? `${current} ${sentence}` : sentence

    if (candidate.length > limit) {
      chunks.push(current)
      current = sentence
    } else {
      current = candidate
    }
  }

  if (current) {
    chunks.push(current)
  }

  return chunks
}

/** Seed history for a new Live session from the chat transcript (text turns only). */
export function toLiveHistory(
  turns: Array<{ role: 'assistant' | 'user'; text: string }>,
  maxMessages = 24,
  maxChars = 6_000
): LiveHistoryMessage[] {
  const out: LiveHistoryMessage[] = []
  let budget = maxChars

  for (const turn of [...turns].reverse()) {
    const text = turn.text.replace(/\s+/g, ' ').trim().slice(0, 1_200)

    if (!text) {
      continue
    }

    if (out.length >= maxMessages || budget - text.length < 0) {
      break
    }

    budget -= text.length
    out.unshift({
      content: [{ text, type: turn.role === 'assistant' ? 'output_text' : 'input_text' }],
      role: turn.role,
      type: 'message'
    })
  }

  return out
}

async function waitForIceGathering(connection: RTCPeerConnection): Promise<void> {
  if (connection.iceGatheringState === 'complete') {
    return
  }

  await new Promise<void>((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      connection.removeEventListener('icegatheringstatechange', onState)
      // Trickle is fine: the vendor answers with the candidates it has.
      resolve()
    }, ICE_GATHER_TIMEOUT_MS)

    function onState() {
      if (connection.iceGatheringState !== 'complete') {
        return
      }

      window.clearTimeout(timeout)
      connection.removeEventListener('icegatheringstatechange', onState)
      resolve()
    }

    connection.addEventListener('icegatheringstatechange', onState)
    connection.addEventListener('connectionstatechange', () => {
      if (connection.connectionState === 'failed') {
        window.clearTimeout(timeout)
        reject(new Error('WebRTC connection failed'))
      }
    })
  })
}

export class VoiceLiveSession {
  readonly audio: HTMLAudioElement
  /** Whose (connection, profile) this session dials; null → the active scope.
   *  A Bot chat runs its GPT-Live session on the Bot's own profile, so the
   *  voice configured there is the voice that answers. */
  private readonly owner: null | OwnerScope
  private readonly handlers: VoiceLiveHandlers
  private peer: null | RTCPeerConnection = null
  private events: null | RTCDataChannel = null
  private microphone: null | MediaStream = null
  private remoteTracks = new Set<MediaStreamTrack>()
  private closeTimer: null | number = null
  private closeDetails: VoiceLiveCloseDetails | null = null
  private finalized = false
  private started = false
  private eventCounter = 0
  private transcript: LiveTranscriptFragment[] = []
  private speakingProbe: null | number = null
  private analyser: null | AnalyserNode = null
  private audioContext: null | AudioContext = null
  private lastSpeaking = false
  private readonly diagnostics: CodexLiveDiagnostics
  private readonly openedAt = performance.now()
  private handoffStartedAt = new Map<string, number>()
  private startupError = 'microphone'
  private protocol: VoiceLiveProtocol = 'gpt-live'
  private codexTranscript = new CodexLiveTranscript()
  private seenDelegations = new Set<string>()
  private answeredDelegations = new Set<string>()
  readonly epoch = crypto.randomUUID()
  sessionId: null | string = null
  /** The delegation currently being answered by Hermes; late results for an
   *  older id are dropped by the conversation hook. */
  activeDelegationId: null | string = null

  constructor(handlers: VoiceLiveHandlers, owner: null | OwnerScope = null, debug = false) {
    this.handlers = handlers
    this.owner = owner
    const debugOwner = resolveOwnerNow(owner ?? undefined)
    this.diagnostics = new CodexLiveDiagnostics(debug, events =>
      hermesApiAs(debugOwner, {
        method: 'POST',
        path: '/api/audio/voice-live/debug',
        body: { events },
        timeoutMs: 5000
      })
    )
    this.audio = new Audio()
    this.audio.autoplay = true
  }

  get connected(): boolean {
    return !this.finalized && this.started && this.events?.readyState === 'open'
  }

  get finalResultOnly(): boolean {
    return this.protocol === 'codex-live'
  }

  private nextEventId(prefix: string): string {
    this.eventCounter += 1

    return `${prefix}_${this.eventCounter}`
  }

  private send(event: Record<string, unknown>): boolean {
    if (this.finalized || !this.events || this.events.readyState !== 'open') {
      return false
    }

    this.events.send(JSON.stringify(event))

    return true
  }

  /** Recent conversation, oldest first, bounded by time and count. */
  contextWindow(): LiveTranscriptFragment[] {
    const transcript = this.finalResultOnly ? this.codexTranscript.context() : this.transcript
    const last = transcript.at(-1)

    if (!last) {
      return []
    }

    const floor = last.endMs - CONTEXT_WINDOW_MS

    return transcript
      .filter(fragment => fragment.endMs >= floor)
      .slice(-CONTEXT_MAX_FRAGMENTS)
      .map(fragment => ({ ...fragment }))
  }

  async start(history: LiveHistoryMessage[]): Promise<void> {
    this.assertOpen()

    if (this.peer) {
      throw new Error('Live voice session already started')
    }

    this.diagnostics.record({ event: 'lifecycle.start' })

    try {
      this.startupError = 'webrtc'
      const connection = new RTCPeerConnection()
      this.peer = connection
      this.startupError = 'microphone'
      await this.open(connection, history)
    } catch (error) {
      this.diagnostics.record({ event: 'session.error', error: this.startupError })
      this.finish('startup_failed', null, 'startup_failed')
      throw error
    }
  }

  private assertOpen(): void {
    if (this.finalized) {
      throw new Error('Live voice session closed')
    }
  }

  private async open(connection: RTCPeerConnection, history: LiveHistoryMessage[]): Promise<void> {
    connection.addEventListener('track', event => {
      if (this.finalized) {
        event.track.stop()

        return
      }

      this.remoteTracks.add(event.track)
      const stream = new MediaStream([event.track])
      this.audio.srcObject = stream
      void this.audio.play().catch(() => undefined)
      this.armSpeakingProbe(stream)
    })
    connection.addEventListener('connectionstatechange', () => {
      this.diagnostics.record({
        event: 'webrtc.state',
        state: connection.connectionState,
        duration_ms: this.elapsed(this.openedAt)
      })

      if (connection.connectionState === 'failed') {this.diagnostics.record({ event: 'session.error', error: 'webrtc' })}

      // Native Codex leaves transient disconnects to WebRTC recovery; only failure ends the call.
      if (connection.connectionState === 'failed' || (connection.connectionState === 'disconnected' && !this.finalResultOnly)) {
        this.finish('connection_lost', null, 'transport_lost')
      }
    })

    const microphone = await navigator.mediaDevices.getUserMedia({
      audio: { autoGainControl: true, echoCancellation: true, noiseSuppression: true }
    })

    if (this.finalized) {
      microphone.getTracks().forEach(track => track.stop())
      this.assertOpen()
    }

    this.microphone = microphone
    this.startupError = 'webrtc'

    for (const track of this.microphone.getAudioTracks()) {
      connection.addTrack(track, this.microphone)
    }

    // Register the data channel before the offer so its m-line is negotiated.
    const events = connection.createDataChannel('oai-events')
    this.events = events

    const channelState = () =>
      this.diagnostics.record({
        event: 'data_channel.state',
        state: events.readyState,
        duration_ms: this.elapsed(this.openedAt)
      })

    events.addEventListener('open', channelState)
    events.addEventListener('closing', channelState)
    events.addEventListener('error', () => this.diagnostics.record({ event: 'session.error', error: 'data_channel' }))
    channelState()
    events.addEventListener('message', ({ data }) => this.handleEvent(String(data)))
    events.addEventListener('close', () => {
      channelState()

      if (!this.finalized) {
        this.finish('connection_lost', null, 'transport_lost')
      }
    })

    const offer = await connection.createOffer()
    this.assertOpen()
    await connection.setLocalDescription(offer)
    this.assertOpen()
    await waitForIceGathering(connection)
    this.assertOpen()

    const sdp = connection.localDescription?.sdp

    if (!sdp) {
      throw new Error('Missing local SDP offer')
    }

    this.startupError = 'handshake'

    const response = await hermesApi<{
      ok: boolean
      session?: { id: string }
      protocol?: VoiceLiveProtocol
      transport?: { sdp: string; type: string }
    }>({
      ...ownerScoped(this.owner ?? undefined),
      body: { history, sdp },
      method: 'POST',
      path: '/api/audio/voice-live/session',
      timeoutMs: 45_000
    })

    this.assertOpen()

    if (!response?.ok || !response.transport?.sdp) {
      throw new Error('Live voice session creation failed')
    }

    this.protocol = response.protocol === 'codex-live' ? 'codex-live' : 'gpt-live'
    this.sessionId = response.session?.id ?? null
    this.startupError = 'webrtc'
    await connection.setRemoteDescription({ sdp: response.transport.sdp, type: 'answer' })
    this.assertOpen()
  }

  private armSpeakingProbe(stream: MediaStream): void {
    try {
      const context = new AudioContext()
      const source = context.createMediaStreamSource(stream)
      const analyser = context.createAnalyser()
      analyser.fftSize = 512
      source.connect(analyser)
      this.audioContext = context
      this.analyser = analyser
      const buffer = new Uint8Array(analyser.frequencyBinCount)
      let quietFrames = 0

      this.speakingProbe = window.setInterval(() => {
        analyser.getByteTimeDomainData(buffer)
        let peak = 0

        for (const sample of buffer) {
          peak = Math.max(peak, Math.abs(sample - 128))
        }

        const loud = peak > 6
        quietFrames = loud ? 0 : quietFrames + 1
        const speaking = loud || quietFrames < 4

        if (speaking !== this.lastSpeaking) {
          this.lastSpeaking = speaking
          this.handlers.onSpeakingChange?.(speaking)
        }
      }, 100)
    } catch {
      // No analyser → no speaking indicator; the conversation still works.
    }
  }

  private handleEvent(raw: string): void {
    if (this.finalized) {
      return
    }

    let event: LiveServerEvent

    try {
      event = JSON.parse(raw) as LiveServerEvent

      if (!event || typeof event.type !== 'string') {throw new Error()}
    } catch {
      this.diagnostics.record({ event: 'session.error', error: 'protocol' })

      return
    }

    if (this.finalResultOnly) {
      const fragment = this.codexTranscript.accept(event)

      if (fragment) {
        this.handlers.onTranscript?.(fragment)

        return
      }

      if (event.type === 'delegation.created') {
        if (event.item?.target === 'client' && event.item.id) {
          const turnId = event.item.user_bidi_turn_id
          const context = turnId ? this.codexTranscript.contextForTurn(turnId) : this.contextWindow()

          if (context) {
            this.delegate(event.item.id, context, {id: event.item.handoff_id ?? event.item.id, delegation_id: event.item.id, epoch: this.epoch, user_turn_id: turnId})
          } else if (!this.seenDelegations.has(event.item.id)) {
            this.seenDelegations.add(event.item.id)
            this.activeDelegationId = event.item.id
            this.speak(
              event.item.id,
              'I could not match that request to its spoken turn. Please repeat it; no task was started.',
              'error'
            )
          }
        }

        return
      }
    }

    switch (event.type) {
      case 'session.started':
        this.started = true
        this.sessionId = event.session?.id ?? this.sessionId

        return

      case 'session.input_transcript.delta':
      case 'session.output_transcript.delta': {
        const fragment: LiveTranscriptFragment = {
          endMs: event.end_ms ?? 0,
          speaker: event.type === 'session.input_transcript.delta' ? 'user' : 'assistant',
          startMs: event.start_ms ?? 0,
          text: event.delta ?? ''
        }

        this.transcript.push(fragment)

        if (this.transcript.length > 2_000) {
          this.transcript.splice(0, this.transcript.length - 1_500)
        }

        this.handlers.onTranscript?.(fragment)

        return
      }

      case 'session.delegation.created': {
        const id = event.delegation?.id

        if (id) {
          this.delegate(id)
        }

        return
      }

      case 'error': {
        const code = event.error?.code ?? ''

        // Late appends after our own close are expected noise.
        if (code === 'context_injection_incomplete') {
          return
        }

        this.diagnostics.record({ event: 'session.error', error: 'protocol' })
        this.handlers.onError(event.error?.message ?? 'GPT-Live error', false)

        return
      }

      case 'session.closed':
        this.finish(event.reason ?? 'closed', event.usage?.seconds ?? null)

        return

      default:
        return
    }
  }

  private elapsed(start: number): number {
    return Math.min(86_400_000, Math.max(0, Math.round(performance.now() - start)))
  }

  interrupted(): void {
    this.diagnostics.record({ event: 'interruption' })
  }

  delegationFailed(id: string): void {
    const startedAt = this.handoffStartedAt.get(id)
    this.diagnostics.record(
      { event: 'delegation.error', error: 'delegation',
        ...(startedAt === undefined ? {} : { duration_ms: this.elapsed(startedAt) }) },
      id
    )
    this.handoffStartedAt.delete(id)
  }

  disposition(id: string | undefined, outcome: string): void {
    this.diagnostics.record({ event: 'delegation.disposition', outcome }, id)
  }

  private replySent(id: string, outcome: string): void {
    const startedAt = this.handoffStartedAt.get(id)
    this.diagnostics.record({ event: 'delegation.reply_sent', outcome,
      ...(startedAt === undefined ? {} : { duration_ms: this.elapsed(startedAt) }) }, id)
    this.handoffStartedAt.delete(id)
  }

  /** Quiet progress for the live model ("Hermes is running the tests…"). */
  think(delegationId: null | string, content: string): void {
    if (this.finalResultOnly) {
      this.updateContext(content)

      return
    }

    const text = content.replace(/\s+/g, ' ').trim().slice(0, APPEND_CHAR_LIMIT)

    if (text) {
      this.send({
        content: text,
        delegation_id: delegationId,
        event_id: this.nextEventId('think'),
        type: 'session.thinking.append'
      })
    }
  }

  /** A result the voice should say aloud (paraphrased). */
  speak(delegationId: null | string, content: string, outcome: 'task_result' | 'status' | 'busy' | 'pending' | 'error' = 'task_result'): void {
    if (this.finalResultOnly) {
      const text = codexLiveResult(content)

      if (
        !text ||
        !delegationId ||
        !this.seenDelegations.has(delegationId) ||
        this.answeredDelegations.has(delegationId)
      ) {
        return
      }

      if (
        this.send({
          type: 'delegation.context.append',
          delegation_item_id: delegationId,
          content: [{ type: 'input_text', text }]
        })
      ) {
        this.answeredDelegations.add(delegationId)
        this.replySent(delegationId, outcome)
      }

      return
    }

    for (const chunk of chunkForCommentary(content)) {
      this.send({
        content: chunk,
        delegation_id: delegationId,
        event_id: this.nextEventId('say'),
        type: 'session.commentary.append'
      })
    }
  }

  /** Steer the live persona mid-conversation (session-wide). */
  instruct(content: string): void {
    if (this.finalResultOnly) {
      this.updateContext(content)

      return
    }

    const text = content.trim().slice(0, APPEND_CHAR_LIMIT)

    if (text) {
      this.send({
        content: text,
        delegation_id: null,
        event_id: this.nextEventId('instr'),
        type: 'session.instructions.append'
      })
    }
  }

  updateContext(content: string): boolean {
    if (!this.finalResultOnly || !this.connected) {return false}

    return codexContextChunks(content.slice(0, 8000)).every(text =>
      this.send({type: 'session.context.append', channel: 'commentary', content: [{type: 'input_text', text}]}))
  }

  silence(): void {
    this.audio.muted = true
    this.interrupted()
    this.handlers.onSpeakingChange?.(false)
  }

  resumeSpeech(): void {
    this.audio.muted = false
  }

  setMuted(muted: boolean): void {
    for (const track of this.microphone?.getAudioTracks() ?? []) {
      track.enabled = !muted
    }

    if (this.finalResultOnly) {
      return
    }

    this.send({
      event_id: this.nextEventId(muted ? 'mute' : 'unmute'),
      type: muted ? 'session.input_audio.mute' : 'session.input_audio.unmute'
    })
  }

  /** Graceful close: ask for `session.closed`, tear down after it (or a timeout). */
  close(details: VoiceLiveCloseDetails = { close_trigger: 'requested' }): void {
    if (this.finalized) {
      return
    }

    this.closeDetails ??= details

    if (this.finalResultOnly || !this.started || !this.send({ type: 'session.close' })) {
      this.finish('close_requested', null)

      return
    }

    this.closeTimer = window.setTimeout(() => this.finish('close_requested', null), CLOSE_TIMEOUT_MS)
  }

  private finish(reason: string, usageSeconds: null | number, trigger: VoiceLiveCloseDetails['close_trigger'] = 'remote_close'): void {
    if (this.finalized) {
      return
    }

    this.finalized = true
    this.started = false

    const details: VoiceLiveCloseDetails = this.closeDetails ?? { close_trigger: trigger }

    this.diagnostics.record({ event: 'lifecycle.stop', duration_ms: this.elapsed(this.openedAt),
      close_trigger: details.close_trigger,
      conversation_changed: details.conversation_changed,
      profile_changed: details.profile_changed,
      connection_changed: details.connection_changed })
    this.diagnostics.close()
    this.handoffStartedAt.clear()

    if (this.closeTimer) {
      window.clearTimeout(this.closeTimer)
      this.closeTimer = null
    }

    if (this.speakingProbe) {
      window.clearInterval(this.speakingProbe)
      this.speakingProbe = null
    }

    this.analyser?.disconnect()
    void this.audioContext?.close().catch(() => undefined)
    this.microphone?.getTracks().forEach(track => track.stop())
    this.remoteTracks.forEach(track => track.stop())
    this.remoteTracks.clear()
    this.events?.close()
    this.peer?.close()
    this.audio.srcObject = null
    this.audio.pause()
    this.handlers.onClosed(reason, usageSeconds)
  }

  private delegate(id: string, context: LiveTranscriptFragment[] = this.contextWindow(), handoff?: VoiceHandoff): void {
    if (this.seenDelegations.has(id)) {
      return
    }

    this.seenDelegations.add(id)

    // Diagnostic timing is bounded and never decides whether work can run.
    if (this.handoffStartedAt.size < 100) {this.handoffStartedAt.set(id, performance.now())}
    this.diagnostics.record({ event: 'delegation.start' }, id)
    this.activeDelegationId = id
    this.handlers.onDelegation(id, context, handoff)
  }
}
