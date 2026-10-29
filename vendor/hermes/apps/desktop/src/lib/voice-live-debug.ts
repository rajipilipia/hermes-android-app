const EVENTS = new Set([
  'lifecycle.start',
  'lifecycle.stop',
  'webrtc.state',
  'data_channel.state',
  'interruption',
  'delegation.start',
  'delegation.complete',
  'delegation.reply_sent',
  'delegation.disposition',
  'delegation.error',
  'session.error'
])

const STATES = new Set([
  'new',
  'connecting',
  'connected',
  'disconnected',
  'failed',
  'closed',
  'open',
  'closing',
  'checking',
  'completed'
])

const ERRORS = new Set(['microphone', 'handshake', 'webrtc', 'data_channel', 'protocol', 'delegation', 'unknown'])

const OUTCOMES = new Set([
  'task_result', 'status', 'busy', 'pending', 'error', 'submit_requested',
  'silenced', 'end_call', 'cancel_requested', 'steer_requested',
  'no_active_task', 'duplicate', 'replacement_requested', 'replacement_blocked'
])

const CLOSE_TRIGGERS = new Set([
  'requested', 'spoken_end', 'disabled', 'scope_changed', 'unmount',
  'startup_superseded', 'startup_failed', 'remote_close', 'transport_lost'
])

export interface VoiceLiveCloseDetails {
  close_trigger: 'requested' | 'spoken_end' | 'disabled' | 'scope_changed' | 'unmount' |
    'startup_superseded' | 'startup_failed' | 'remote_close' | 'transport_lost'
  conversation_changed?: boolean
  profile_changed?: boolean
  connection_changed?: boolean
}

export interface CodexLiveDebugEvent {
  event: string
  connection_id?: string
  handoff_id?: string
  duration_ms?: number
  state?: string
  error?: string
  outcome?: string
  close_trigger?: VoiceLiveCloseDetails['close_trigger']
  conversation_changed?: boolean
  profile_changed?: boolean
  connection_changed?: boolean
}

/** Only scalars from closed vocabularies cross this boundary. Never spread input. */
function metadata(input: Record<string, unknown>): CodexLiveDebugEvent | null {
  if (typeof input.event !== 'string' || !EVENTS.has(input.event)) {return null}
  const event: CodexLiveDebugEvent = { event: input.event }

  if (typeof input.state === 'string' && STATES.has(input.state)) {event.state = input.state}

  if (typeof input.error === 'string' && ERRORS.has(input.error)) {event.error = input.error}

  if (typeof input.outcome === 'string' && OUTCOMES.has(input.outcome)) {event.outcome = input.outcome}

  if (typeof input.close_trigger === 'string' && CLOSE_TRIGGERS.has(input.close_trigger)) {
    event.close_trigger = input.close_trigger as VoiceLiveCloseDetails['close_trigger']
  }

  for (const key of ['conversation_changed', 'profile_changed', 'connection_changed'] as const) {
    if (typeof input[key] === 'boolean') {event[key] = input[key]}
  }

  if (
    typeof input.duration_ms === 'number' &&
    Number.isInteger(input.duration_ms) &&
    input.duration_ms >= 0 &&
    input.duration_ms <= 86_400_000
  )
    {event.duration_ms = input.duration_ms}

  return event
}

async function hashId(raw: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw))

  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
}

/** Per-connection opt-in sink: bounded even while hashing or sending stalls.
 * Failures drop a batch, never retry, never log, and never enter voice control flow. */
export class CodexLiveDiagnostics {
  private queue: Array<Promise<CodexLiveDebugEvent | null>> = []
  private connection: Promise<string | null> | null = null
  private timer: ReturnType<typeof setInterval> | null = null
  private inflight = false
  private closing = false

  constructor(
    enabled: boolean,
    private readonly send: (events: CodexLiveDebugEvent[]) => Promise<unknown>
  ) {
    if (enabled !== true) {return}

    try {
      this.connection = hashId(crypto.randomUUID()).catch(() => null)
      this.timer = setInterval(() => {
        void this.flush()
      }, 1000)
    } catch {
      // Missing Web Crypto disables diagnostics, not voice.
    }
  }

  record(input: Record<string, unknown>, handoffId?: string): void {
    if (!this.connection || this.closing || this.queue.length >= 100) {return}
    const event = metadata(input)

    if (!event) {return}

    // Do not retain protocol objects or unbounded provider IDs while hashing.
    const handoff =
      typeof handoffId === 'string' && handoffId.length > 0 && handoffId.length <= 1024
        ? hashId(handoffId).catch(() => null)
        : Promise.resolve(null)

    this.queue.push(
      Promise.all([this.connection, handoff]).then(([connection, handoff]) => {
        if (!connection) {return null}
        event.connection_id = connection

        if (handoff) {event.handoff_id = handoff}

        return event
      })
    )
  }

  close(): void {
    this.closing = true
    this.clearWhenDrained()
  }

  private clearWhenDrained(): void {
    if (this.closing && this.queue.length === 0 && this.timer !== null) {
      clearInterval(this.timer)
      this.timer = null
    }
  }

  private async flush(): Promise<void> {
    if (this.inflight || this.queue.length === 0) {return}
    this.inflight = true

    try {
      const events = (await Promise.all(this.queue.splice(0, 20))).filter(
        (event): event is CodexLiveDebugEvent => event !== null
      )

      if (events.length && new TextEncoder().encode(JSON.stringify({ events })).byteLength <= 16 * 1024)
        {await this.send(events)}
    } catch {
      // Best effort only. Never expose exceptions, payloads or retry failed batches.
    } finally {
      this.inflight = false
      this.clearWhenDrained()
    }
  }
}
