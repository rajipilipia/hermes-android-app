import { describe, expect, it } from 'vitest'

import { codexLiveResult, CodexLiveTranscript } from './voice-live-codex'

describe('Codex cumulative transcripts', () => {
  it('adopts fragments received before turn.created without duplicating snapshots', () => {
    const transcript = new CodexLiveTranscript()
    transcript.accept({ type: 'input_transcript.added', item: { text: 'Check the ' } })
    transcript.accept({ type: 'turn.created', turn: { id: 'u', role: 'user', transcript: '' } })
    transcript.accept({ type: 'input_transcript.added', item: { text: 'weather' } })
    transcript.accept({ type: 'turn.delta', turn: { id: 'u', role: 'user', transcript: 'Check the weather' } })
    transcript.accept({ type: 'turn.done', turn: { id: 'u', role: 'user', transcript: 'Check the weather.' } })
    transcript.accept({ type: 'output_transcript.added', item: { text: 'Checking.' } })
    transcript.accept({ type: 'turn.done', turn: { id: 'a', role: 'assistant', transcript: 'Checking.' } })
    expect(transcript.context().map(f => [f.turnId, f.speaker, f.text])).toEqual([
      ['u', 'user', 'Check the weather.'],
      ['a', 'assistant', 'Checking.']
    ])
  })

  it('does not let a repeated completed turn split the current input fragments', () => {
    const transcript = new CodexLiveTranscript()
    const old = { type: 'turn.done', turn: { id: 'old', role: 'user', transcript: 'First request.' } }
    transcript.accept(old)
    transcript.accept({ type: 'turn.created', turn: { id: 'new', role: 'user', transcript: '' } })
    transcript.accept({ type: 'input_transcript.added', item: { text: 'New ' } })
    transcript.accept(old)
    transcript.accept({ type: 'input_transcript.added', item: { text: 'request.' } })
    expect(transcript.context().map(f => f.text)).toEqual(['First request.', 'New request.'])
  })

  it('bounds delegation context to its originating user turn, never a newer request', () => {
    const transcript = new CodexLiveTranscript()
    transcript.accept({ type: 'turn.done', turn: { id: 'u1', role: 'user', transcript: 'First request.' } })
    transcript.accept({ type: 'turn.created', turn: { id: 'u2', role: 'user', transcript: 'Second request.' } })
    expect(transcript.contextForTurn('u1')?.map(f => f.text)).toEqual(['First request.'])
    expect(transcript.contextForTurn('missing')).toBeNull()
  })

  it('bounds a long final result as one marked response rather than multiple completions', () => {
    const result = codexLiveResult('A complete sentence. '.repeat(2000))
    expect(result.length).toBeLessThanOrEqual(12000)
    expect(result).toMatch(/\. \[Full result is in the chat\.\]$/)
    expect(codexLiveResult('  Done.\n All passed. ')).toBe('Done. All passed.')
  })
})
