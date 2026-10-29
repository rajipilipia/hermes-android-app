import type { LiveTranscriptFragment } from './voice-live'

export interface CodexLiveEvent {
  type: string
  item?: {
    id?: string
    type?: string
    target?: string
    text?: string
    user_bidi_turn_id?: string
    handoff_id?: string
    content?: Array<{ type: string; text?: string }>
  }
  turn?: { id: string; role: string; transcript?: string }
}

/** Added events are fragments; turn events are cumulative snapshots of those
 * same words. Keep one entry per turn, including the still-speaking user. */
export class CodexLiveTranscript {
  private fragments: LiveTranscriptFragment[] = []
  private current = new Map<string, LiveTranscriptFragment>()
  private turns = new Map<string, LiveTranscriptFragment>()

  accept(event: CodexLiveEvent): LiveTranscriptFragment | null {
    const isTurn = ['turn.created', 'turn.delta', 'turn.done'].includes(event.type)

    const role = isTurn
      ? event.turn?.role
      : { 'input_transcript.added': 'user', 'output_transcript.added': 'assistant' }[event.type]

    if (role !== 'user' && role !== 'assistant') {
      return null
    }

    const turn = isTurn ? event.turn : undefined
    let fragment = turn ? this.turns.get(turn.id) : this.current.get(role)
    const historical = Boolean(turn && fragment && this.current.get(role) !== fragment)

    if (!fragment && turn) {
      const pending = this.current.get(role)

      if (pending && !pending.turnId) {
        fragment = pending
      }
    }

    if (!fragment) {
      fragment = { speaker: role, text: '', startMs: Date.now(), endMs: Date.now() }
      this.fragments.push(fragment)
    }

    if (turn) {
      fragment.turnId = turn.id
      this.turns.set(turn.id, fragment)

      // Empty lifecycle events must not erase input already received.
      if (turn.transcript) {
        fragment.text = turn.transcript
      }
    } else {
      fragment.text += event.item?.text ?? ''
    }

    fragment.endMs = Date.now()

    if (historical) {
      return null
    }

    this.current.set(role, fragment)

    if (event.type === 'turn.done') {
      this.current.delete(role)
    }

    // Bound the long-running session's transcript and turn index together.
    if (this.fragments.length > 160) {
      for (const removed of this.fragments.splice(0, 80)) {
        if (removed.turnId) {
          this.turns.delete(removed.turnId)
        }
      }
    }

    return { ...fragment, final: event.type === 'turn.done' }
  }

  context(): LiveTranscriptFragment[] {
    return this.fragments.filter(fragment => fragment.text).map(fragment => ({ ...fragment }))
  }

  contextForTurn(turnId: string): LiveTranscriptFragment[] | null {
    const index = this.fragments.findIndex(fragment => fragment.turnId === turnId && fragment.speaker === 'user')
    if (index < 0 || !this.fragments[index].text) {
      return null
    }
    return this.fragments
      .slice(0, index + 1)
      .filter(fragment => fragment.text)
      .slice(-80)
      .map(fragment => ({ ...fragment }))
  }
}

/** Codex accepts a single final context result, not streamed commentary. */
export function codexLiveResult(content: string, limit = 12_000): string {
  const text = content.replace(/\s+/g, ' ').trim()

  if (text.length <= limit) {
    return text
  }

  const head = text.slice(0, limit - 64)
  const boundary = head.lastIndexOf('. ')

  return `${boundary > head.length / 2 ? head.slice(0, boundary + 1) : head.trimEnd()} [Full result is in the chat.]`
}
