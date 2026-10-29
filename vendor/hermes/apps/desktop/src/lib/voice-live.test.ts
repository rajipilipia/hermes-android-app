// @vitest-environment jsdom
import { webcrypto } from 'node:crypto'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { hermesApi } from '@/hermes'

import { fetchVoiceLiveStatus, VoiceLiveSession } from './voice-live'

vi.mock('@/hermes', () => ({ hermesApi: vi.fn() }))
vi.mock('@/api/client', () => ({
  ownerScoped: (owner: unknown) => ({ owner }),
  profileScoped: () => ({}),
  resolveOwnerNow: (owner: unknown) => owner,
  hermesApiAs: (owner: unknown, request: Record<string, unknown>) => hermesApi({ ...request, owner } as never)
}))

class Channel extends EventTarget {
  readyState = 'open'
  send = vi.fn()
  close = vi.fn(() => {
    this.readyState = 'closed'
  })
  emit(event: unknown) {
    this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(event) }))
  }
}

class Peer extends EventTarget {
  static instances: Peer[] = []
  channel = new Channel()
  iceGatheringState = 'complete'
  connectionState = 'connected'
  localDescription = { sdp: 'offer' }
  addTrack = vi.fn()
  createDataChannel = vi.fn(() => this.channel)
  createOffer = vi.fn(async () => ({ sdp: 'offer', type: 'offer' }))
  setLocalDescription = vi.fn(async () => undefined)
  setRemoteDescription = vi.fn(async () => undefined)
  close = vi.fn()
  constructor() {
    super()
    Peer.instances.push(this)
  }
}
const track = { enabled: true, stop: vi.fn() }
const stream = { getAudioTracks: () => [track], getTracks: () => [track] }
const handlers = () => ({ onDelegation: vi.fn(), onClosed: vi.fn(), onError: vi.fn(), onTranscript: vi.fn() })

const answer = (protocol = 'codex-live') => ({
  ok: true,
  protocol,
  session: { id: 'session' },
  transport: { type: 'webrtc', sdp: 'answer' }
})

beforeEach(() => {
  vi.clearAllMocks()
  Peer.instances = []
  track.enabled = true
  vi.stubGlobal('RTCPeerConnection', Peer)
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(async () => stream) } })
  vi.stubGlobal(
    'Audio',
    class {
      autoplay = false
      srcObject = null
      play = vi.fn(async () => undefined)
      pause = vi.fn()
    }
  )
  vi.mocked(hermesApi).mockResolvedValue(answer())
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('live transport protocol boundary', () => {
  it.each([undefined, false, 'true', 1])('keeps diagnostics off for non-true status %s', async debug => {
    vi.mocked(hermesApi).mockResolvedValue({ ok: true, mode: 'codex-live', debug })
    expect((await fetchVoiceLiveStatus())?.debug).toBe(false)
  })

  it('uses the owner status and only enables diagnostics for Codex Live', async () => {
    vi.mocked(hermesApi).mockResolvedValue({ ok: true, mode: 'codex-live', debug: true })
    expect((await fetchVoiceLiveStatus({ connectionId: 'owner', profile: 'profile' }))?.debug).toBe(true)
    expect(hermesApi).toHaveBeenCalledWith(
      expect.objectContaining({ owner: { connectionId: 'owner', profile: 'profile' } })
    )
    vi.mocked(hermesApi).mockResolvedValue({ ok: true, mode: 'gpt-live', debug: true })
    expect((await fetchVoiceLiveStatus())?.debug).toBe(false)
  })

  it.each(['microphone', 'handshake'])(
    'records only a fixed %s error and closes after startup failure',
    async phase => {
      vi.useFakeTimers()
      vi.stubGlobal('crypto', webcrypto)

      if (phase === 'microphone')
        {vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValue(new Error('SECRET failure'))}
      else
        {vi.mocked(hermesApi).mockImplementation(async request => {
          if (request.path.endsWith('/session')) {throw new Error('SECRET failure')}

          return { ok: true } as never
        })}

      const live = new VoiceLiveSession(handlers(), null, true)
      await expect(live.start([])).rejects.toThrow('SECRET failure')
      await vi.advanceTimersByTimeAsync(1000)
      await vi.waitFor(() =>
        expect(vi.mocked(hermesApi).mock.calls.some(([r]) => r.path.endsWith('/debug'))).toBe(true)
      )

      const request = vi
        .mocked(hermesApi)
        .mock.calls.map(([r]) => r)
        .find(r => r.path.endsWith('/debug'))!

      expect((request.body as { events: unknown[] }).events).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ event: 'session.error', error: phase }),
          expect.objectContaining({ event: 'lifecycle.stop' })
        ])
      )
      expect(JSON.stringify(request.body)).not.toContain('SECRET')
      expect(vi.getTimerCount()).toBe(0)
    }
  )

  it('records real Codex lifecycle, state, interruption and handoff timings without content', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('crypto', webcrypto)
    const live = new VoiceLiveSession(handlers(), { connectionId: 'owner', profile: 'profile' }, true)
    await live.start([])
    const peer = Peer.instances[0]
    peer.dispatchEvent(new Event('connectionstatechange'))
    peer.channel.dispatchEvent(new Event('open'))
    peer.channel.emit({ type: 'turn.done', turn: { id: 'raw-turn', role: 'user', transcript: 'SECRET transcript' } })
    peer.channel.emit({
      type: 'delegation.created',
      item: { target: 'client', id: 'raw-handoff', user_bidi_turn_id: 'raw-turn' }
    })
    await vi.advanceTimersByTimeAsync(125)
    live.interrupted()
    live.speak('raw-handoff', 'SECRET result')
    peer.channel.emit({ type: 'error', error: { message: 'SECRET exception' } })
    live.close()
    await vi.advanceTimersByTimeAsync(1000)
    await vi.waitFor(() => expect(vi.mocked(hermesApi).mock.calls.some(([r]) => r.path.endsWith('/debug'))).toBe(true))

    const requests = vi
      .mocked(hermesApi)
      .mock.calls.map(([r]) => r)
      .filter(r => r.path.endsWith('/debug'))

    const events = requests.flatMap(r => (r.body as { events: Array<Record<string, unknown>> }).events)
    expect(events.map(e => e.event)).toEqual(
      expect.arrayContaining([
        'lifecycle.start',
        'lifecycle.stop',
        'webrtc.state',
        'data_channel.state',
        'interruption',
        'delegation.start',
        'delegation.reply_sent',
        'session.error'
      ])
    )
    expect(events.find(e => e.event === 'delegation.reply_sent')).toMatchObject({
      duration_ms: 125,
      handoff_id: expect.stringMatching(/^[a-f0-9]{64}$/)
    })
    expect(JSON.stringify(requests)).not.toMatch(/SECRET|raw-handoff|raw-turn|offer|answer/)
  })

  it('correlates overlapping reply sends without calling them task or playback completion', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('crypto', webcrypto)
    const live = new VoiceLiveSession(handlers(), null, true)
    await live.start([])
    const channel = Peer.instances[0].channel

    const delegate = (id: string) => {
      channel.emit({ type: 'turn.done', turn: { id, role: 'user', transcript: 'SECRET request' } })
      channel.emit({ type: 'delegation.created', item: { target: 'client', id, user_bidi_turn_id: id } })
    }

    delegate('first')
    await vi.advanceTimersByTimeAsync(50)
    delegate('second')
    await vi.advanceTimersByTimeAsync(50)
    live.disposition('second', 'busy')
    live.speak('second', 'SECRET notice', 'busy')
    await vi.advanceTimersByTimeAsync(50)
    live.speak('first', 'SECRET result')
    live.close()
    await vi.advanceTimersByTimeAsync(1000)
    await vi.waitFor(() => expect(vi.mocked(hermesApi).mock.calls.some(([r]) => r.path.endsWith('/debug'))).toBe(true))

    const events = vi.mocked(hermesApi).mock.calls
      .filter(([r]) => r.path.endsWith('/debug'))
      .flatMap(([r]) => (r.body as { events: Array<Record<string, unknown>> }).events)

    const replies = events.filter(e => e.event === 'delegation.reply_sent')
    expect(replies).toEqual([
      expect.objectContaining({ duration_ms: 50, outcome: 'busy' }),
      expect.objectContaining({ duration_ms: 150, outcome: 'task_result' })
    ])
    expect(replies[0].handoff_id).not.toBe(replies[1].handoff_id)
    expect(events.find(e => e.event === 'delegation.disposition')).toMatchObject({ outcome: 'busy', handoff_id: replies[0].handoff_id })
    expect(events.some(e => e.event === 'delegation.complete')).toBe(false)
    expect(JSON.stringify(events)).not.toContain('SECRET')
  })

  it.each(['scope_changed', 'unmount', 'remote_close'] as const)(
    'records the %s close trigger without provider text or raw identities', async trigger => {
      vi.useFakeTimers()
      vi.stubGlobal('crypto', webcrypto)
      const live = new VoiceLiveSession(handlers(), null, true)
      await live.start([])

      if (trigger === 'remote_close') {
        Peer.instances[0].channel.emit({ type: 'session.closed', reason: 'startup_failed' })
      } else {
        live.close({ close_trigger: trigger, conversation_changed: true, profile_changed: false, connection_changed: false })
      }

      await vi.advanceTimersByTimeAsync(1000)
      await vi.waitFor(() => expect(vi.mocked(hermesApi).mock.calls.some(([r]) => r.path.endsWith('/debug'))).toBe(true))

      const events = vi.mocked(hermesApi).mock.calls
        .filter(([r]) => r.path.endsWith('/debug'))
        .flatMap(([r]) => (r.body as { events: Array<Record<string, unknown>> }).events)

      expect(events.find(e => e.event === 'lifecycle.stop')).toMatchObject({ close_trigger: trigger })
      expect(JSON.stringify(events)).not.toContain('SECRET')
    }
  )

  it('keeps Codex audio alive through a transient disconnect and stops it on failure', async () => {
    vi.stubGlobal(
      'MediaStream',
      class {
        constructor(readonly tracks: unknown[]) {}
      }
    )
    const callbacks = handlers()
    const live = new VoiceLiveSession(callbacks, { connectionId: 'owner-connection', profile: 'owner-profile' })
    await live.start([])
    expect(hermesApi).toHaveBeenCalledWith(
      expect.objectContaining({ owner: { connectionId: 'owner-connection', profile: 'owner-profile' } })
    )
    const peer = Peer.instances[0]
    const remote = { stop: vi.fn() }
    peer.dispatchEvent(Object.assign(new Event('track'), { track: remote }))
    expect(live.audio.play).toHaveBeenCalledTimes(1)
    expect(live.audio.srcObject).not.toBeNull()
    peer.channel.emit({ type: 'session.started', session: { id: 'codex' } })
    peer.connectionState = 'disconnected'
    peer.dispatchEvent(new Event('connectionstatechange'))
    expect(remote.stop).not.toHaveBeenCalled()
    expect(track.stop).not.toHaveBeenCalled()
    expect(live.audio.srcObject).not.toBeNull()
    expect(callbacks.onClosed).not.toHaveBeenCalled()
    peer.connectionState = 'connected'
    peer.dispatchEvent(new Event('connectionstatechange'))
    expect(live.connected).toBe(true)
    expect(peer.close).not.toHaveBeenCalled()
    peer.connectionState = 'failed'
    peer.dispatchEvent(new Event('connectionstatechange'))
    expect(remote.stop).toHaveBeenCalledTimes(1)
    expect(track.stop).toHaveBeenCalledTimes(1)
    expect(live.audio.srcObject).toBeNull()
    expect(callbacks.onClosed).toHaveBeenCalledExactlyOnceWith('connection_lost', null)
  })

  it('preserves legacy GPT teardown on disconnect', async () => {
    vi.mocked(hermesApi).mockResolvedValue(answer('gpt-live'))
    const callbacks = handlers()
    const live = new VoiceLiveSession(callbacks)
    await live.start([])
    const peer = Peer.instances[0]
    peer.connectionState = 'disconnected'
    peer.dispatchEvent(new Event('connectionstatechange'))
    expect(track.stop).toHaveBeenCalledTimes(1)
    expect(peer.close).toHaveBeenCalledTimes(1)
    expect(callbacks.onClosed).toHaveBeenCalledExactlyOnceWith('connection_lost', null)
  })

  it('stops a late microphone grant after close without making an offer', async () => {
    let grant!: (value: MediaStream) => void
    vi.mocked(navigator.mediaDevices.getUserMedia).mockReturnValue(
      new Promise(resolve => {
        grant = resolve
      }) as Promise<MediaStream>
    )
    const callbacks = handlers()
    const live = new VoiceLiveSession(callbacks)
    const starting = live.start([])
    live.close()
    grant(stream as unknown as MediaStream)
    await expect(starting).rejects.toThrow('closed')
    expect(track.stop).toHaveBeenCalledTimes(1)
    expect(Peer.instances[0].addTrack).not.toHaveBeenCalled()
    expect(hermesApi).not.toHaveBeenCalled()
    expect(callbacks.onClosed).toHaveBeenCalledTimes(1)
  })

  it('cleans up rejected handshakes without requiring caller cleanup', async () => {
    vi.mocked(hermesApi).mockRejectedValue(new Error('denied'))
    const live = new VoiceLiveSession(handlers())
    await expect(live.start([])).rejects.toThrow('denied')
    expect(track.stop).toHaveBeenCalledTimes(1)
    expect(Peer.instances[0].close).toHaveBeenCalledTimes(1)
  })

  it('ignores a late SDP answer and remote track after close', async () => {
    let answerSdp!: (value: unknown) => void
    vi.mocked(hermesApi).mockReturnValue(
      new Promise(resolve => {
        answerSdp = resolve
      })
    )
    const live = new VoiceLiveSession(handlers())
    const starting = live.start([])
    await vi.waitFor(() => expect(hermesApi).toHaveBeenCalled())
    live.close()
    answerSdp(answer())
    await expect(starting).rejects.toThrow('closed')
    const peer = Peer.instances[0]
    const remote = { stop: vi.fn() }
    peer.dispatchEvent(Object.assign(new Event('track'), { track: remote }))
    expect(peer.setRemoteDescription).not.toHaveBeenCalled()
    expect(remote.stop).toHaveBeenCalledTimes(1)
    expect(live.audio.play).not.toHaveBeenCalled()
  })

  it('keeps the legacy GPT protocol when the backend omits protocol', async () => {
    vi.mocked(hermesApi).mockResolvedValue({ ...answer(), protocol: undefined })
    const callbacks = handlers()
    const live = new VoiceLiveSession(callbacks)
    await live.start([])
    const channel = Peer.instances[0].channel
    channel.emit({ type: 'session.started' })
    channel.emit({ type: 'session.input_transcript.delta', delta: 'Hello ', start_ms: 0, end_ms: 100 })
    channel.emit({ type: 'session.input_transcript.delta', delta: 'Hermes', start_ms: 100, end_ms: 200 })
    channel.emit({ type: 'session.delegation.created', delegation: { id: 'g1', type: 'delegation', target: 'client' } })
    expect(callbacks.onDelegation.mock.calls[0][1].map((f: { text: string }) => f.text).join('')).toBe('Hello Hermes')
    live.think('g1', 'working')
    live.speak('g1', 'done')
    expect(channel.send.mock.calls.map(([raw]) => JSON.parse(raw).type)).toEqual([
      'session.thinking.append',
      'session.commentary.append'
    ])
    live.close()
    channel.emit({ type: 'session.closed' })
    expect(track.stop).toHaveBeenCalledTimes(1)
  })

  it('delegates Codex input before turn.done exactly once, without cumulative transcript duplication', async () => {
    const callbacks = handlers()
    const live = new VoiceLiveSession(callbacks)
    await live.start([])
    const channel = Peer.instances[0].channel
    channel.emit({ type: 'session.started', session: { id: 'codex' } })
    channel.emit({ type: 'turn.created', turn: { id: 'u1', role: 'user', transcript: '' } })
    channel.emit({ type: 'input_transcript.added', item: { text: 'Run ' } })
    channel.emit({ type: 'input_transcript.added', item: { text: 'the tests' } })
    channel.emit({ type: 'turn.delta', turn: { id: 'u1', role: 'user', transcript: 'Run the tests' } })

    const delegation = {
      type: 'delegation.created',
      item: { id: 'd1', type: 'delegation', target: 'client', user_bidi_turn_id: 'u1', handoff_id: 'h1' }
    }

    channel.emit(delegation)
    channel.emit({ type: 'turn.done', turn: { id: 'u1', role: 'user', transcript: 'Run the tests.' } })
    channel.emit(delegation)
    expect(live.connected).toBe(true)
    expect(callbacks.onDelegation).toHaveBeenCalledTimes(1)
    expect(callbacks.onDelegation.mock.calls[0][1].map((f: { text: string }) => f.text).join('')).toBe('Run the tests')
    expect(
      live
        .contextWindow()
        .map(f => f.text)
        .join('')
    ).toBe('Run the tests.')
    live.think('d1', 'working')
    live.instruct('respond now')
    live.setMuted(true)
    expect(track.enabled).toBe(false)
    expect(channel.send.mock.calls.map(([raw]) => JSON.parse(raw))).toEqual([
      {type: 'session.context.append', channel: 'commentary', content: [{type: 'input_text', text: 'working'}]},
      {type: 'session.context.append', channel: 'commentary', content: [{type: 'input_text', text: 'respond now'}]}
    ])
    channel.send.mockClear()
    live.speak('d1', 'All tests passed.')
    live.speak('d1', 'duplicate')
    expect(channel.send).toHaveBeenCalledTimes(1)
    expect(JSON.parse(channel.send.mock.calls[0][0])).toEqual({
      type: 'delegation.context.append',
      delegation_item_id: 'd1',
      content: [{ type: 'input_text', text: 'All tests passed.' }]
    })
    live.close()
    expect(track.stop).toHaveBeenCalledTimes(1)
    expect(Peer.instances[0].close).toHaveBeenCalledTimes(1)
    expect(callbacks.onClosed).toHaveBeenCalledTimes(1)
    channel.emit({ type: 'session.started', session: { id: 'late' } })
    expect(live.connected).toBe(false)
  })
})
