// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setApiRequestConnection } from '@/api/client'
import type { VoiceLiveHandlers } from '@/lib/voice-live'
import type { VoiceHandoff, VoiceTaskSnapshot } from '@/lib/voice-live-task'

import { ComposerScopeProvider, MAIN_COMPOSER_SCOPE } from '../scope'

import { useVoiceLiveConversation } from './use-voice-live-conversation'

const transport = vi.hoisted(() => ({
  sessions: [] as Array<{
    handlers: VoiceLiveHandlers
    close: ReturnType<typeof vi.fn>
    speak: ReturnType<typeof vi.fn>
    updateContext: ReturnType<typeof vi.fn>
    delegationFailed: ReturnType<typeof vi.fn>
  }>
}))

// Keep the real task link: a surviving mic alone does not prove receipt delivery.
vi.mock('@/lib/voice-live', async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  fetchVoiceLiveStatus: vi.fn(async () => ({ mode: 'codex-live', available: true })),
  VoiceLiveSession: class {
    finalResultOnly = true
    epoch = 'voice-epoch'
    close = vi.fn()
    speak = vi.fn()
    updateContext = vi.fn(() => true)
    resumeSpeech = vi.fn()
    disposition = vi.fn()
    delegationFailed = vi.fn()

    constructor(public handlers: VoiceLiveHandlers) {
      transport.sessions.push(this)
    }

    async start(): Promise<void> {}
  }
}))

vi.mock('@/store/notifications', () => ({ notify: vi.fn(), notifyError: vi.fn() }))

interface LiveScope {
  sessionId: string | null
  queueSessionKey?: string | null
}

const owner = { connectionId: null as string | null, profile: 'rp-life' }
const emptySnapshot = (): VoiceTaskSnapshot => ({ task: null, history: [], pending: null })

const handoff: VoiceHandoff = {
  id: 'handoff-1',
  delegation_id: 'delegation-1',
  epoch: 'voice-epoch',
  user_turn_id: 'turn-1'
}

function mountLive(
  initialProps: LiveScope,
  callbacks = {
    taskRequest: vi.fn(async (): Promise<VoiceTaskSnapshot> => emptySnapshot()),
    onSubmit: vi.fn(async (_text: string, _context: string, _handoff?: VoiceHandoff) => {})
  },
  activeToolLabel?: () => string | null
) {
  return renderHook(
    (scope: LiveScope) =>
      useVoiceLiveConversation({
        ...scope,
        ...callbacks,
        activeToolLabel,
        enabled: true,
        busy: false,
        consumePendingResponse: vi.fn(),
        pendingResponse: () => null,
        seedHistory: () => []
      }),
    {
      initialProps,
      wrapper: ({ children }: { children: ReactNode }) => (
        <ComposerScopeProvider value={{ ...MAIN_COMPOSER_SCOPE, ...owner }}>{children}</ComposerScopeProvider>
      )
    }
  )
}

async function start(hook: ReturnType<typeof mountLive>) {
  await act(async () => {
    await hook.result.current.start()
  })
  expect(hook.result.current.status).toBe('listening')

  return transport.sessions.at(-1)!
}

function delegate(session: (typeof transport.sessions)[number], next = handoff) {
  session.handlers.onDelegation(
    next.delegation_id,
    [{ speaker: 'user', text: 'Run the tests.', startMs: 0, endMs: 1 }],
    next
  )
}

beforeEach(() => {
  vi.useFakeTimers()
  transport.sessions.length = 0
  owner.connectionId = null
  owner.profile = 'rp-life'
  setApiRequestConnection(null)
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('Codex Live conversation continuity', () => {
  it('feeds verified running-tool progress through the real task link without a second submission', async () => {
    let snapshot = emptySnapshot()

    const callbacks = {
      taskRequest: vi.fn(async () => snapshot),
      onSubmit: vi.fn(async (_text: string, _context: string, accepted?: VoiceHandoff) => {
        snapshot = {...emptySnapshot(),task:{
          id:'task-1',handoff_id:accepted!.id,delegation_id:accepted!.delegation_id,
          epoch:accepted!.epoch,status:'working',request:'Run the tests.',result:'',correction:''
        }}
      })
    }

    const hook = mountLive({queueSessionKey:'chat-root',sessionId:'runtime-1'},callbacks,()=> 'terminal')
    const session = await start(hook)
    await act(async () => {delegate(session)})
    expect(session.updateContext).toHaveBeenCalledWith(expect.stringContaining('"progress":{"tool_name":"terminal","status":"running"}'))
    expect(callbacks.onSubmit).toHaveBeenCalledTimes(1)
    expect(session.close).not.toHaveBeenCalled()
  })
  it('keeps an accepted task through a same-chat runtime rebind, speaks its receipt, and uses current request/submit routes', async () => {
    let snapshot = emptySnapshot()

    const callbacks = {
      taskRequest: vi.fn(async () => snapshot),
      onSubmit: vi.fn(async (_text: string, _context: string, accepted?: VoiceHandoff) => {
        snapshot = {
          ...emptySnapshot(),
          task: {
            id: 'task-1',
            handoff_id: accepted!.id,
            delegation_id: accepted!.delegation_id,
            epoch: accepted!.epoch,
            status: 'working',
            request: 'Run the tests.',
            result: '',
            correction: ''
          }
        }
      })
    }

    const hook = mountLive({ queueSessionKey: 'chat-root', sessionId: 'runtime-before' }, callbacks)
    const session = await start(hook)
    await act(async () => {
      delegate(session)
    })
    expect(callbacks.onSubmit).toHaveBeenCalledWith('Run the tests.', 'User: Run the tests.', handoff)
    expect(snapshot.task?.status).toBe('working')

    const originalRequest = callbacks.taskRequest
    const originalSubmit = callbacks.onSubmit
    const requestsBeforeRebind = originalRequest.mock.calls.length
    callbacks.taskRequest = vi.fn(async () => snapshot)
    callbacks.onSubmit = vi.fn(async () => {})
    hook.rerender({ queueSessionKey: 'chat-root', sessionId: 'runtime-after' })

    expect(session.close).not.toHaveBeenCalled()
    snapshot = { ...snapshot, task: { ...snapshot.task!, status: 'completed', result: 'All tests passed.' } }
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(callbacks.taskRequest).toHaveBeenCalled()
    expect(originalRequest).toHaveBeenCalledTimes(requestsBeforeRebind)
    expect(session.speak).toHaveBeenCalledWith(handoff.delegation_id, 'All tests passed.')
    expect(hook.result.current.status).toBe('listening')
    expect(transport.sessions).toHaveLength(1)

    snapshot = emptySnapshot()
    const next = { ...handoff, id: 'handoff-2', delegation_id: 'delegation-2', user_turn_id: 'turn-2' }
    await act(async () => {
      delegate(session, next)
    })
    expect(callbacks.onSubmit).toHaveBeenCalledWith('Run the tests.', 'User: Run the tests.', next)
    expect(originalSubmit).toHaveBeenCalledTimes(1)
  })

  it('records a rejected Codex submission as an error, not a completed task', async () => {
    const callbacks = {
      taskRequest: vi.fn(async () => emptySnapshot()),
      onSubmit: vi.fn(async () => { throw new Error('Synthetic rejection') })
    }

    const hook = mountLive({ queueSessionKey: 'chat-root', sessionId: 'runtime' }, callbacks)
    const session = await start(hook)
    await act(async () => { delegate(session) })
    expect(session.delegationFailed).toHaveBeenCalledWith(handoff.delegation_id)
    expect(session.speak).toHaveBeenCalledWith(handoff.delegation_id, expect.any(String), 'error')
    expect(session.close).not.toHaveBeenCalled()
  })

  it.each([null, 'stale-runtime'])(
    'adopts the first stored conversation from a draft (runtime %s)',
    async sessionId => {
      const hook = mountLive({ queueSessionKey: null, sessionId })
      const session = await start(hook)
      hook.rerender({ queueSessionKey: 'first-stored-chat', sessionId: 'first-runtime' })
      expect(session.close).not.toHaveBeenCalled()
      expect(hook.result.current.status).toBe('listening')
    }
  )

  it.each([
    [null, 'local'],
    ['local', null]
  ] as const)('preserves equivalent local owner publication %s → %s', async (before, after) => {
    owner.connectionId = before
    const hook = mountLive({ queueSessionKey: 'chat-root', sessionId: 'runtime' })
    const session = await start(hook)
    owner.connectionId = after
    hook.rerender({ queueSessionKey: 'chat-root', sessionId: 'runtime' })
    expect(session.close).not.toHaveBeenCalled()
    expect(hook.result.current.status).toBe('listening')
  })

  it.each([
    { name: 'different chat', key: 'another-chat', connection: null, profile: 'rp-life' },
    { name: 'new draft', key: null, connection: null, profile: 'rp-life' },
    { name: 'different profile', key: 'chat-root', connection: null, profile: 'another-profile' },
    { name: 'different backend', key: 'chat-root', connection: 'remote-gateway', profile: 'rp-life' }
  ])('closes voice and stops receipt polling on $name', async ({ key, connection, profile }) => {
    const callbacks = { taskRequest: vi.fn(async () => emptySnapshot()), onSubmit: vi.fn(async () => {}) }
    const hook = mountLive({ queueSessionKey: 'chat-root', sessionId: 'runtime' }, callbacks)
    const session = await start(hook)
    const requestsBeforeSwitch = callbacks.taskRequest.mock.calls.length
    owner.connectionId = connection
    owner.profile = profile
    // Deliberately retain the runtime id: durable chat identity must own this gate.
    hook.rerender({ queueSessionKey: key, sessionId: 'runtime' })
    expect(session.close).toHaveBeenCalledTimes(1)
    expect(session.close).toHaveBeenCalledWith({
      close_trigger: 'scope_changed',
      conversation_changed: key !== 'chat-root',
      connection_changed: connection !== null,
      profile_changed: profile !== 'rp-life'
    })
    expect(hook.result.current.status).toBe('idle')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(callbacks.taskRequest).toHaveBeenCalledTimes(requestsBeforeSwitch)
  })

  it('closes voice and stops receipt polling on unmount', async () => {
    const callbacks = { taskRequest: vi.fn(async () => emptySnapshot()), onSubmit: vi.fn(async () => {}) }
    const hook = mountLive({ queueSessionKey: 'chat-root', sessionId: 'runtime' }, callbacks)
    const session = await start(hook)
    const requestsBeforeUnmount = callbacks.taskRequest.mock.calls.length
    hook.unmount()
    expect(session.close).toHaveBeenCalledTimes(1)
    expect(session.close).toHaveBeenCalledWith({ close_trigger: 'unmount' })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(callbacks.taskRequest).toHaveBeenCalledTimes(requestsBeforeUnmount)
  })
})
