import { createHash, webcrypto } from 'node:crypto'

import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { type CodexLiveDebugEvent, CodexLiveDiagnostics } from './voice-live-debug'

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('crypto', webcrypto)
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it('is inert unless explicitly enabled and never logs', async () => {
  const send = vi.fn()
  const log = vi.spyOn(console, 'error')
  const debug = new CodexLiveDiagnostics(false, send)
  debug.record({ event: 'lifecycle.start' })
  debug.close()
  await vi.advanceTimersByTimeAsync(10_000)
  expect(send).not.toHaveBeenCalled()
  expect(log).not.toHaveBeenCalled()
  log.mockRestore()
})

it('bounds queue, batch, bytes, rate and inflight work; drops failures without retry', async () => {
  let reject!: (reason: Error) => void

  const send = vi.fn(
    (_events: CodexLiveDebugEvent[]) =>
      new Promise<void>((_, fail) => {
        reject = fail
      })
  )

  const debug = new CodexLiveDiagnostics(true, send)

  for (let i = 0; i < 1000; i++) {debug.record({ event: 'webrtc.state', state: 'connected', duration_ms: i })}
  await vi.advanceTimersByTimeAsync(1000)
  await vi.waitFor(() => expect(send).toHaveBeenCalledTimes(1))
  expect(send.mock.calls[0][0]).toHaveLength(20)
  expect(new TextEncoder().encode(JSON.stringify({ events: send.mock.calls[0][0] })).length).toBeLessThanOrEqual(16384)
  await vi.advanceTimersByTimeAsync(5000)
  expect(send).toHaveBeenCalledTimes(1)
  debug.close()
  send.mockResolvedValue(undefined)
  reject(new Error('SECRET failure'))
  await vi.advanceTimersByTimeAsync(5000)
  expect(send).toHaveBeenCalledTimes(5)
  const sent = send.mock.calls.flatMap(([events]) => events)
  expect(sent).toHaveLength(100)
  expect(new Set(sent.map(e => e.duration_ms)).size).toBe(100)
  expect(vi.getTimerCount()).toBe(0)
})

it('fails closed when hashing is unavailable, without sending raw IDs', async () => {
  vi.stubGlobal('crypto', {
    randomUUID: () => 'raw',
    subtle: {
      digest: async () => {
        throw new Error('secret')
      }
    }
  })
  const send = vi.fn()
  const debug = new CodexLiveDiagnostics(true, send)
  debug.record({ event: 'delegation.start' }, 'raw-id')
  debug.close()
  await vi.advanceTimersByTimeAsync(2000)
  expect(send).not.toHaveBeenCalled()
  expect(vi.getTimerCount()).toBe(0)
})

it('allows fixed close and outcome metadata but drops free text and non-boolean flags', async () => {
  const send = vi.fn(async (_events: CodexLiveDebugEvent[]) => undefined)
  const debug = new CodexLiveDiagnostics(true, send)
  debug.record({ event: 'lifecycle.stop', close_trigger: 'scope_changed', conversation_changed: true, profile_changed: false, connection_changed: false })
  debug.record({ event: 'delegation.reply_sent', outcome: 'busy' }, 'provider-id')
  debug.record({ event: 'lifecycle.stop', close_trigger: 'SECRET reason', conversation_changed: 'SECRET identity' })
  await vi.advanceTimersByTimeAsync(1000)
  await vi.waitFor(() => expect(send).toHaveBeenCalledTimes(1))
  const events = send.mock.calls[0][0]
  expect(events[0]).toMatchObject({ close_trigger: 'scope_changed', conversation_changed: true, profile_changed: false, connection_changed: false })
  expect(events[1]).toMatchObject({ event: 'delegation.reply_sent', outcome: 'busy' })
  expect(events[2]).toEqual({ event: 'lifecycle.stop', connection_id: events[0].connection_id })
  expect(JSON.stringify(events)).not.toMatch(/SECRET|provider-id/)
  debug.close()
})

it('transports only validated metadata and SHA256 identities', async () => {
  const send = vi.fn(async (_events: CodexLiveDebugEvent[]) => undefined)
  const debug = new CodexLiveDiagnostics(true, send)
  debug.record(
    { event: 'delegation.start', duration_ms: 25, state: 'open', text: 'SECRET', error: 'secret-error' },
    'raw-provider-id'
  )
  debug.record({ event: 'secret-event', duration_ms: 7 })
  debug.record({ event: 'session.error', error: 'protocol', duration_ms: -1 })
  await vi.advanceTimersByTimeAsync(1000)
  await vi.waitFor(() => expect(send).toHaveBeenCalledTimes(1))
  const events = send.mock.calls[0][0]
  expect(events).toHaveLength(2)
  expect(events[0]).toEqual({
    event: 'delegation.start',
    duration_ms: 25,
    state: 'open',
    connection_id: expect.stringMatching(/^[a-f0-9]{64}$/),
    handoff_id: createHash('sha256').update('raw-provider-id').digest('hex')
  })
  expect(events[1]).toEqual({ event: 'session.error', error: 'protocol', connection_id: events[0].connection_id })
  expect(JSON.stringify(events)).not.toMatch(/SECRET|secret|raw-provider/)
  debug.close()
})
