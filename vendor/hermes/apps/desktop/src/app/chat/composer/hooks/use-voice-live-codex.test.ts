// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { VoiceLiveHandlers } from '@/lib/voice-live'
import type { VoiceHandoff, VoiceTaskSnapshot } from '@/lib/voice-live-task'

import { useVoiceLiveConversation } from './use-voice-live-conversation'

const transport = vi.hoisted(() => ({ handlers: [] as VoiceLiveHandlers[], speak: vi.fn() }))
vi.mock('@/lib/voice-live', async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  fetchVoiceLiveStatus: vi.fn(async () => ({ mode: 'codex-live', available: true })),
  VoiceLiveSession: class {
    finalResultOnly = true
    epoch = 'epoch'
    close = vi.fn()
    updateContext = vi.fn(() => true)
    disposition = vi.fn()
    resumeSpeech = vi.fn()
    delegationFailed = vi.fn()
    instruct = vi.fn()
    setMuted = vi.fn()
    speak = transport.speak
    think = vi.fn()
    start = vi.fn(async () => undefined)
    constructor(handlers: VoiceLiveHandlers) {
      transport.handlers.push(handlers)
    }
  }
}))

interface Response {
  id: string
  pending: boolean
  text: string
}
const context = [{ speaker: 'user' as const, text: 'Run tests', startMs: 0, endMs: 1 }]

const handoff = (id: string): VoiceHandoff => ({ id: `handoff-${id}`, delegation_id: id, epoch: 'epoch', user_turn_id: `turn-${id}` })

const snapshot = (id: string, response: Response | null): VoiceTaskSnapshot => ({
  task: response ? {
    id: `task-${id}`, handoff_id: handoff(id).id, delegation_id: id, epoch: 'epoch',
    status: response.pending ? 'working' : 'completed', request: 'Run tests',
    result: response.pending ? '' : response.text, correction: ''
  } : null,
  history: [], pending: null
})

describe('Codex Live Hermes result delivery', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    transport.speak.mockClear()
    transport.handlers = []
  })
  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it('waits for the final answer and returns one coherent result, not interim sentences', async () => {
    let response: Response = { id: 'reply', pending: true, text: 'Checking now. Still running. ' }
    let accepted = false
    const submit = vi.fn(async () => { accepted = true })

    const hook = renderHook(
      ({ busy }) =>
        useVoiceLiveConversation({
          busy,
          enabled: true,
          onSubmit: submit,
          taskRequest: async () => snapshot('d1', accepted ? response : null),
          consumePendingResponse: vi.fn(),
          pendingResponse: () => response,
          seedHistory: () => []
        }),
      { initialProps: { busy: false } }
    )

    await act(async () => hook.result.current.start())
    await act(async () => transport.handlers.at(-1)!.onDelegation('d1', context, handoff('d1')))
    hook.rerender({ busy: true })
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(submit).toHaveBeenCalledTimes(1)
    expect(transport.speak).not.toHaveBeenCalled()
    response = { id: 'final', pending: false, text: 'All tests passed.' }
    hook.rerender({ busy: false })
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(transport.speak).toHaveBeenCalledExactlyOnceWith('d1', 'All tests passed.')
  })

  it('resolves an empty completed turn with an explicit outcome instead of leaving voice waiting', async () => {
    let accepted = false
    let complete = false

    const hook = renderHook(
      ({ busy }) =>
        useVoiceLiveConversation({
          busy,
          enabled: true,
          onSubmit: vi.fn(async () => { accepted = true }),
          taskRequest: async () => snapshot('empty', accepted ? { id: 'empty', pending: !complete, text: '' } : null),
          consumePendingResponse: vi.fn(),
          pendingResponse: () => null,
          seedHistory: () => []
        }),
      { initialProps: { busy: false } }
    )

    await act(async () => hook.result.current.start())
    await act(async () => transport.handlers.at(-1)!.onDelegation('empty', context, handoff('empty')))
    hook.rerender({ busy: true })
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    complete = true
    hook.rerender({ busy: false })
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(transport.speak).toHaveBeenCalledExactlyOnceWith(
      'empty',
      'Hermes task completed.'
    )
  })

  it('does not let a late acknowledgement error clear work already accepted and steered', async () => {
    let rejectOld!: (error: Error) => void
    let accepted = false

    const submit = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise((_, reject) => {
            accepted = true
            rejectOld = reject
          })
      )
      .mockResolvedValue(undefined)

    let response: Response = { id: 'old', pending: true, text: '' }
    const request = vi.fn(async (action?: string) => ({ ...snapshot('old', accepted ? response : null), ...(action && { control: 'queued' }) }))

    const hook = renderHook(() =>
      useVoiceLiveConversation({
        busy: false,
        enabled: true,
        onSubmit: submit,
        taskRequest: request,
        consumePendingResponse: vi.fn(),
        pendingResponse: () => response,
        seedHistory: () => []
      })
    )

    await act(async () => hook.result.current.start())
    const handler = transport.handlers.at(-1)!
    await act(async () => handler.onDelegation('old', context, handoff('old')))
    await act(async () => handler.onDelegation('new', context, handoff('new')))
    expect(submit).toHaveBeenCalledTimes(1)
    expect(request).toHaveBeenCalledWith('steer', 'task-old', expect.any(String))
    expect(transport.speak).toHaveBeenCalledWith('new', expect.stringContaining('not yet confirmed'), 'status')
    transport.speak.mockClear()
    await act(async () => rejectOld(new Error('old failed')))
    expect(transport.speak).not.toHaveBeenCalled()
    response = { id: 'new-result', pending: false, text: 'New result.' }
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(transport.speak).toHaveBeenCalledExactlyOnceWith('old', 'New result.')
  })
})
