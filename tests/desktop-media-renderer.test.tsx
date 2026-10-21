// @vitest-environment jsdom
// Finite synthetic host/service fixtures exercising the ACTUAL pinned renderer.
// These are NOT browser/device, microphone, live gateway or provider acceptance.
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { JsonRpcGatewayError } from '@hermes/shared'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { uploadComposerAttachment, usePromptActions } from '@/app/session/hooks/use-prompt-actions'
import { $composerAttachments, type ComposerAttachment } from '@/store/composer'
import { $connection, $sessions, setSessionOwnerHint, _resetSessionOwnerHintsForTests } from '@/store/session'
import { $activeGatewayProfile } from '@/store/profile'
import { $sessionStates, recordSessionEventScope } from '@/store/session-states'
import type { SessionInfo } from '@/types/hermes'
import { createClientSessionState } from '@/lib/chat-runtime'
import { transcribeAudio } from '@/hermes'
import { transcribeAudioClientDirect } from '@/lib/voice-client-direct'
import { extractDroppedFiles, partitionDroppedFiles, useComposerActions } from '@/app/chat/hooks/use-composer-actions'
import { useVoiceRecorder } from '@/app/chat/composer/hooks/use-voice-recorder'
import { useVoiceConversation } from '@/app/chat/composer/hooks/use-voice-conversation'
import { ComposerScopeProvider, MAIN_COMPOSER_SCOPE } from '@/app/chat/composer/scope'
import type { PropsWithChildren } from 'react'

vi.mock('@/hermes', async () => ({
  resolveOwnerNow: (await import('@/api/client')).resolveOwnerNow,
  getProfiles: vi.fn(async () => ({ profiles: [] })),
  getSession: vi.fn(async () => {
    throw new Error('Unlisted synthetic session')
  }),
  PROMPT_SUBMIT_REQUEST_TIMEOUT_MS: 1_800_000,
  setApiRequestProfile: vi.fn(),
  transcribeAudio: vi.fn(async () => {
    throw new Error('Legacy audio forbidden in Android fixture')
  }),
  setSttLease: vi.fn(async () => {
    throw new Error('Optional STT warm-up unsupported in Android fixture')
  })
}))
vi.mock('@/lib/voice-client-direct', () => ({
  transcribeAudioClientDirect: vi.fn(async () => {
    throw new Error('Provider/config access forbidden in Android fixture')
  })
}))

const runtimeId = 'runtime-fixture-exact-42'
const storedId = 'stored-fixture-exact-91'
const connectionId = 'connection-fixture-a'
const localPath = 'android-local://fixture-1/.ქართული.txt'
const fileComplete = {
  attached: true,
  name: '.ქართული.txt',
  path: 'attachments/.ქართული.txt',
  ref_path: 'attachments/.ქართული.txt',
  ref_text: '@file:attachments/.ქართული.txt',
  uploaded: true
}
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}
const attachment = (overrides: Partial<ComposerAttachment> = {}): ComposerAttachment => ({
  id: 'fixture-file',
  kind: 'file',
  label: '.ქართული.txt',
  path: localPath,
  ...overrides
})
function installHost(host: Record<string, unknown>) {
  Object.defineProperty(window, 'hermesDesktop', { configurable: true, value: host })
}
const requestGateway = vi.fn(async (method: string) => {
  throw new Error(`Unexpected original gateway request: ${method}`)
})
function seedOwner(profile = 'example-profile') {
  $sessions.set([
    {
      id: storedId,
      profile,
      connection_id: connectionId,
      ended_at: null,
      input_tokens: 0,
      is_active: true,
      last_active: 0,
      message_count: 0,
      model: null,
      output_tokens: 0,
      preview: null,
      source: 'desktop',
      started_at: 0,
      title: 'synthetic fixture',
      tool_call_count: 0
    } satisfies SessionInfo
  ])
  $sessionStates.set({})
  recordSessionEventScope({ session_id: runtimeId, profile, connectionId })
}
function promptHook(gateway = requestGateway, active: string | null = null) {
  const selectedStoredSessionIdRef = { current: storedId as string | null }
  const activeSessionIdRef = { current: runtimeId as string | null }
  const busyRef = { current: false }
  const runtimeIdByStoredSessionIdRef = { current: new Map([[storedId, runtimeId]]) }
  const result = renderHook(() =>
    usePromptActions({
      activeSessionId: active,
      activeSessionIdRef,
      busyRef,
      branchCurrentSession: async () => true,
      createBackendSessionForSend: async () => {
        throw new Error('Unexpected session create')
      },
      getRoutedStoredSessionId: () => storedId,
      getRuntimeIdForStoredSession: (id) => runtimeIdByStoredSessionIdRef.current.get(id) ?? null,
      getRouteToken: () => `session:${storedId}`,
      handleSkinCommand: () => '',
      openMemoryGraph: () => undefined,
      refreshSessions: async () => undefined,
      requestGateway: gateway,
      resumeStoredSession: async () => {
        throw new Error('Unexpected session resume')
      },
      runtimeIdByStoredSessionIdRef,
      selectedStoredSessionIdRef,
      startFreshSessionDraft: () => undefined,
      sttEnabled: true,
      updateSessionState: (id, update, stored) => {
        const state = update($sessionStates.get()[id] ?? createClientSessionState(stored))
        $sessionStates.set({ ...$sessionStates.get(), [id]: state })
        return state
      }
    })
  )
  return { ...result, selectedStoredSessionIdRef, activeSessionIdRef }
}
beforeEach(() => {
  vi.clearAllMocks()
  _resetSessionOwnerHintsForTests({ storage: true })
  $composerAttachments.set([])
  $connection.set(null)
  $activeGatewayProfile.set('unrelated-ambient')
  seedOwner()
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

// Hardware boundary only: the real useMicRecorder and voice finalizers still
// execute. This finite MediaRecorder emits fixed synthetic bytes, NOT mic audio.
const fixedAudioBytes = [82, 73, 70, 70, 4, 0, 0, 0]
class FixtureMediaRecorder {
  static isTypeSupported = () => true
  mimeType = 'audio/webm;codecs=opus'
  state: RecordingState = 'inactive'
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null
  onerror: ((event: Event) => void) | null = null
  start() {
    this.state = 'recording'
  }
  stop() {
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob([new Uint8Array(fixedAudioBytes)], { type: this.mimeType }) })
    this.onstop?.()
  }
}
function installCaptureFixture() {
  vi.stubGlobal('MediaRecorder', FixtureMediaRecorder)
  vi.stubGlobal('AudioContext', undefined)
  const stopTrack = vi.fn()
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: stopTrack }] })) }
  })
  return { stopTrack }
}
async function blobBytes(blob: Blob): Promise<number[]> {
  const buffer = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as ArrayBuffer)
    reader.onerror = () => reject(reader.error)
    reader.readAsArrayBuffer(blob)
  })
  return [...new Uint8Array(buffer)]
}

describe('pinned Android renderer media — synthetic host fixture', () => {
  it('stages a local file with exact stored/runtime IDs and owner, preserving complete.ref_text', async () => {
    const uploadAttachment = vi.fn(async () => fileComplete)
    const readFileDataUrl = vi.fn(async () => {
      throw new Error('Whole-file data URL forbidden')
    })
    installHost({
      androidMedia: { isLocalPath: (path: string) => path === localPath, uploadAttachment },
      readFileDataUrl
    })
    const original = attachment({ label: 'Pasted content (2 KB)' })
    const uploaded = await uploadComposerAttachment(original, {
      sessionId: runtimeId,
      storedSessionId: storedId,
      remote: true,
      requestGateway
    })
    expect(uploadAttachment).toHaveBeenCalledExactlyOnceWith({
      path: localPath,
      kind: 'file',
      profile: 'example-profile',
      connectionId,
      sessionId: runtimeId,
      storedSessionId: storedId
    })
    expect(uploaded).toEqual({
      ...original,
      attachedSessionId: runtimeId,
      refText: fileComplete.ref_text,
      uploadState: undefined
    })
    expect(readFileDataUrl).not.toHaveBeenCalled()
    expect(requestGateway).not.toHaveBeenCalled()
  })

  it('transcribes the recorded Blob through Android FIRST, without provider/config or base64 relay', async () => {
    const audio = new Blob([new Uint8Array([82, 73, 70, 70, 4, 0, 0, 0])], { type: 'audio/wav' })
    const transcribeBlob = vi.fn(async () => ({ ok: true, transcript: 'სინთეზური ჩანაწერი', provider: null }))
    installHost({ androidMedia: { transcribeBlob } })
    const { result } = promptHook()
    const owner = { profile: 'example-profile', connectionId }
    expect(await result.current.transcribeVoiceAudio(audio, owner)).toBe('სინთეზური ჩანაწერი')
    expect(transcribeBlob).toHaveBeenCalledExactlyOnceWith(audio, owner)
    expect(transcribeAudioClientDirect).not.toHaveBeenCalled()
    expect(transcribeAudio).not.toHaveBeenCalled()
  })

  it('refuses a known runtime bound to a different stored session before any bytes are uploaded', async () => {
    $sessionStates.set({ [runtimeId]: createClientSessionState('different-stored-exact') })
    const uploadAttachment = vi.fn(async () => fileComplete)
    installHost({ androidMedia: { isLocalPath: () => true, uploadAttachment } })
    await expect(
      uploadComposerAttachment(attachment(), {
        sessionId: runtimeId,
        storedSessionId: storedId,
        remote: true,
        requestGateway
      })
    ).rejects.toThrow(/exact|owner|bound/)
    expect(uploadAttachment).not.toHaveBeenCalled()
  })

  it('refuses conflicting runtime and stored owners instead of picking the foreground connection', async () => {
    recordSessionEventScope({ session_id: runtimeId, profile: 'different-owner', connectionId: 'other-connection' })
    const uploadAttachment = vi.fn(async () => fileComplete)
    installHost({ androidMedia: { isLocalPath: () => true, uploadAttachment } })
    await expect(
      uploadComposerAttachment(attachment(), {
        sessionId: runtimeId,
        storedSessionId: storedId,
        remote: true,
        requestGateway
      })
    ).rejects.toThrow(/owner/)
    expect(uploadAttachment).not.toHaveBeenCalled()
  })

  it('defers Android files to submit instead of eager failure followed by an automatic binary replay', async () => {
    const uploadAttachment = vi.fn(async () => {
      throw new Error('Binary completion response uncertain')
    })
    installHost({ androidMedia: { isLocalPath: () => true, uploadAttachment } })
    $composerAttachments.set([attachment()])
    const { result } = promptHook(requestGateway, runtimeId)
    await act(async () => {
      await Promise.resolve()
    })
    expect($composerAttachments.get()[0]?.uploadState).toBeUndefined()
    expect(uploadAttachment).not.toHaveBeenCalled()
    let accepted: boolean | undefined
    await act(async () => {
      accepted = await result.current.submitText('Read this fixture')
    })
    expect(accepted).toBe(false)
    expect(uploadAttachment).toHaveBeenCalledTimes(1)
    expect(requestGateway).not.toHaveBeenCalled()
  })

  it('captures the canonical target owner before an asynchronous profile/connection switch', async () => {
    setSessionOwnerHint(storedId, { profile: 'desktop-alias', targetProfile: 'example-profile', connectionId })
    const uploadAttachment = vi.fn(async () => fileComplete)
    installHost({ androidMedia: { isLocalPath: () => true, uploadAttachment } })
    const pending = uploadComposerAttachment(attachment(), {
      sessionId: runtimeId,
      storedSessionId: storedId,
      remote: true,
      requestGateway
    })
    $activeGatewayProfile.set('other-profile')
    $connection.set({ mode: 'remote', profile: 'other-profile', connectionId: 'other-connection' } as never)
    $sessions.set([])
    await pending
    expect(uploadAttachment).toHaveBeenCalledExactlyOnceWith({
      path: localPath,
      kind: 'file',
      profile: 'example-profile',
      connectionId,
      sessionId: runtimeId,
      storedSessionId: storedId
    })
  })

  it('accepts a runtime event using the declared Desktop alias but uploads under its canonical target profile', async () => {
    setSessionOwnerHint(storedId, { profile: 'desktop-alias', targetProfile: 'example-profile', connectionId })
    recordSessionEventScope({ session_id: runtimeId, profile: 'desktop-alias', connectionId })
    const uploadAttachment = vi.fn(async () => fileComplete)
    installHost({ androidMedia: { isLocalPath: () => true, uploadAttachment } })
    await uploadComposerAttachment(attachment(), {
      sessionId: runtimeId,
      storedSessionId: storedId,
      remote: true,
      requestGateway
    })
    expect(uploadAttachment).toHaveBeenCalledExactlyOnceWith({
      path: localPath,
      kind: 'file',
      profile: 'example-profile',
      connectionId,
      sessionId: runtimeId,
      storedSessionId: storedId
    })
  })

  it.each([undefined, null, ''])(
    'does not derive a missing stored ID (%s) from a runtime ID',
    async (storedSessionId) => {
      const uploadAttachment = vi.fn(async () => fileComplete)
      installHost({ androidMedia: { isLocalPath: () => true, uploadAttachment } })
      await expect(
        uploadComposerAttachment(attachment(), {
          sessionId: runtimeId,
          storedSessionId,
          remote: true,
          requestGateway
        })
      ).rejects.toThrow(/exact/)
      expect(uploadAttachment).not.toHaveBeenCalled()
      expect(requestGateway).not.toHaveBeenCalled()
    }
  )

  it('refuses an absent stored owner rather than using the ambient profile', async () => {
    $sessions.set([])
    const uploadAttachment = vi.fn(async () => fileComplete)
    installHost({ androidMedia: { isLocalPath: () => true, uploadAttachment } })
    await expect(
      uploadComposerAttachment(attachment(), {
        sessionId: runtimeId,
        storedSessionId: storedId,
        remote: true,
        requestGateway
      })
    ).rejects.toThrow(/owner/)
    expect(uploadAttachment).not.toHaveBeenCalled()
  })

  it('does not invoke original session-not-found recovery after an ambiguous binary completion', async () => {
    const uploadAttachment = vi.fn(async () => {
      throw new JsonRpcGatewayError('Session not found', { code: 4004 })
    })
    const onRecovered = vi.fn()
    installHost({ androidMedia: { isLocalPath: () => true, uploadAttachment } })
    await expect(
      uploadComposerAttachment(attachment(), {
        sessionId: runtimeId,
        storedSessionId: storedId,
        remote: true,
        requestGateway,
        onRecovered
      })
    ).rejects.toThrow('Session not found')
    expect(uploadAttachment).toHaveBeenCalledTimes(1)
    expect(onRecovered).not.toHaveBeenCalled()
    expect(requestGateway).not.toHaveBeenCalled()
  })

  it('queues an image on the exact runtime and returns its completed path without changing its label', async () => {
    const queued: Array<{ runtime: string; path: string }> = []
    const imageComplete = {
      attached: true,
      path: 'images/generated.png',
      count: 1,
      remainder: '',
      text: '',
      bytes: 8,
      name: 'generated.png'
    }
    const uploadAttachment = vi.fn(async (input: { sessionId: string }) => {
      queued.push({ runtime: input.sessionId, path: imageComplete.path })
      return imageComplete
    })
    installHost({ androidMedia: { isLocalPath: () => true, uploadAttachment } })
    const original = attachment({ kind: 'image', path: 'android-local://image/ფოტო.png', label: 'ფოტო.png' })
    expect(
      await uploadComposerAttachment(original, {
        sessionId: runtimeId,
        storedSessionId: storedId,
        remote: true,
        requestGateway
      })
    ).toEqual({ ...original, attachedSessionId: runtimeId, path: imageComplete.path, uploadState: undefined })
    expect(queued).toEqual([{ runtime: runtimeId, path: imageComplete.path }])
    expect(uploadAttachment).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'image', sessionId: runtimeId, storedSessionId: storedId })
    )
  })

  it('actual submit hook waits for ALL file completions and sends ref_text in original attachment order', async () => {
    const first = deferred<typeof fileComplete>()
    const second = deferred<typeof fileComplete>()
    const uploadAttachment = vi
      .fn()
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise)
    installHost({ androidMedia: { isLocalPath: () => true, uploadAttachment } })
    const gateway = vi.fn(async (method: string) => {
      if (method === 'prompt.submit') return { status: 'streaming', user_row_id: 501 } as never
      throw new Error(`Unexpected fixture gateway operation: ${method}`)
    })
    const { result } = promptHook(gateway)
    const attachments = [
      attachment(),
      attachment({ id: 'second', path: 'android-local://second/other.txt', label: 'other.txt' })
    ]
    let pending!: Promise<boolean>
    act(() => {
      pending = result.current.submitText('Read both', { attachments, sessionId: runtimeId, storedSessionId: storedId })
    })
    await waitFor(() => expect(uploadAttachment).toHaveBeenCalledTimes(1))
    expect(gateway).not.toHaveBeenCalled()
    await act(async () => {
      first.resolve(fileComplete)
      await Promise.resolve()
    })
    expect(uploadAttachment).toHaveBeenCalledTimes(2)
    expect(gateway).not.toHaveBeenCalled()
    let accepted: boolean | undefined
    await act(async () => {
      second.resolve({ ...fileComplete, ref_text: '@file:attachments/other.txt' })
      accepted = await pending
    })
    expect(accepted).toBe(true)
    expect(gateway).toHaveBeenCalledExactlyOnceWith(
      'prompt.submit',
      {
        session_id: runtimeId,
        text: `${fileComplete.ref_text}\n@file:attachments/other.txt\n\nRead both`
      },
      1_800_000
    )
  })

  it('actual submit hook sends NO prompt after partial attachment failure and does not replay the completed file', async () => {
    const uploadAttachment = vi
      .fn()
      .mockResolvedValueOnce(fileComplete)
      .mockRejectedValueOnce(new Error('Synthetic second completion failed'))
    installHost({ androidMedia: { isLocalPath: () => true, uploadAttachment } })
    const { result } = promptHook()
    let accepted: boolean | undefined
    await act(async () => {
      accepted = await result.current.submitText('Must not submit', {
        attachments: [attachment(), attachment({ id: 'second', path: 'android-local://second/other.txt' })],
        sessionId: runtimeId,
        storedSessionId: storedId
      })
    })
    expect(accepted).toBe(false)
    expect(uploadAttachment).toHaveBeenCalledTimes(2)
    expect(requestGateway).not.toHaveBeenCalled()
    expect($sessionStates.get()[runtimeId]?.messages.at(-1)?.error).toContain('second completion failed')
  })

  it('rejects ownerless Android recordings and never falls back after an Android transcription failure', async () => {
    const transcribeBlob = vi.fn(async () => {
      throw new Error('Synthetic transcription refused')
    })
    installHost({ androidMedia: { transcribeBlob } })
    const { result } = promptHook()
    const audio = new Blob(['fixed synthetic audio'], { type: 'audio/webm;codecs=opus' })
    await expect(result.current.transcribeVoiceAudio(audio)).rejects.toThrow(/owner/)
    expect(transcribeBlob).not.toHaveBeenCalled()
    await expect(result.current.transcribeVoiceAudio(audio, { profile: 'example-profile', connectionId })).rejects.toThrow(
      'Synthetic transcription refused'
    )
    expect(transcribeBlob).toHaveBeenCalledTimes(1)
    expect(transcribeAudioClientDirect).not.toHaveBeenCalled()
    expect(transcribeAudio).not.toHaveBeenCalled()
  })

  it('extracts actual OS File drops synchronously and keeps Android handles out of PC inline references', () => {
    const file = new File(['fixed drop bytes'], '.ქართული.txt', { type: 'text/plain' })
    const getPathForFile = vi.fn((input: File) => {
      expect(input).toBe(file)
      return localPath
    })
    installHost({ getPathForFile, androidMedia: { isLocalPath: (path: string) => path === localPath } })
    const transfer = {
      getData: () => '',
      items: [{ kind: 'file', getAsFile: () => file, webkitGetAsEntry: () => ({ isDirectory: false }) }],
      files: { length: 1, item: () => file }
    } as unknown as DataTransfer
    const candidates = extractDroppedFiles(transfer)
    expect(candidates).toEqual([{ file, path: localPath }])
    expect(getPathForFile).toHaveBeenCalledTimes(1)
    expect(partitionDroppedFiles(candidates, { remote: false, backendCwd: 'C:\\pc-fixture' })).toEqual({
      osDrops: [{ file, path: localPath }],
      inAppRefs: []
    })
  })

  it('actual file picker opens synchronously, then attaches selected handles without awaiting a session', async () => {
    const picked = deferred<string[]>()
    const selectPaths = vi.fn(() => picked.promise)
    installHost({ selectPaths })
    const { result } = renderHook(() =>
      useComposerActions({ activeSessionId: null, currentCwd: 'C:\\pc-fixture', requestGateway })
    )
    let pending!: Promise<void>
    act(() => {
      pending = result.current.pickContextPaths('file')
    })
    // Same gesture stack: the host starts its standard input before the first
    // await. No session create/resume or gateway is involved in the picker.
    expect(selectPaths).toHaveBeenCalledTimes(1)
    expect(requestGateway).not.toHaveBeenCalled()
    expect($composerAttachments.get()).toEqual([])
    await act(async () => {
      picked.resolve([localPath])
      await pending
    })
    expect($composerAttachments.get()[0]).toMatchObject({ path: localPath, label: '.ქართული.txt', kind: 'file' })
  })

  it('actual picker cancellation and rejection add no successful-looking attachment', async () => {
    const selectPaths = vi.fn().mockResolvedValueOnce([]).mockRejectedValueOnce(new Error('Synthetic picker denied'))
    installHost({ selectPaths })
    const { result } = renderHook(() => useComposerActions({ activeSessionId: null, currentCwd: '', requestGateway }))
    await act(async () => {
      await result.current.pickContextPaths('file')
    })
    expect($composerAttachments.get()).toEqual([])
    await expect(result.current.pickContextPaths('file')).rejects.toThrow('Synthetic picker denied')
    expect($composerAttachments.get()).toEqual([])
    expect(requestGateway).not.toHaveBeenCalled()
  })

  it('actual pasted-text and extracted drop paths reach the bounded uploader with their original host filename', async () => {
    const paths = new Set([localPath, 'android-local://paste/pasted-content.txt'])
    const savePastedText = vi.fn(async () => 'android-local://paste/pasted-content.txt')
    const uploadAttachment = vi.fn(async (input: { path: string }) => ({
      ...fileComplete,
      name: input.path === localPath ? '.ქართული.txt' : 'pasted-content.txt'
    }))
    installHost({ savePastedText, androidMedia: { isLocalPath: (path: string) => paths.has(path), uploadAttachment } })
    const { result } = renderHook(() =>
      useComposerActions({ activeSessionId: null, currentCwd: 'C:\\pc-fixture', requestGateway })
    )
    const text = 'Synthetic pasted context, not user data'
    await act(async () => {
      expect(await result.current.attachPastedText(text)).toBe(true)
    })
    const file = new File(['fixed drop bytes'], '.ქართული.txt', { type: 'text/plain' })
    await act(async () => {
      expect(await result.current.attachDroppedItems([{ file, path: localPath }])).toBe(true)
    })
    expect(savePastedText).toHaveBeenCalledExactlyOnceWith(text)
    const attachments = $composerAttachments.get()
    expect(attachments).toHaveLength(2)
    expect(attachments[0]?.label).toContain('Pasted')
    expect(attachments[1]?.label).toBe('.ქართული.txt')
    for (const item of attachments) {
      const next = await uploadComposerAttachment(item, {
        sessionId: runtimeId,
        storedSessionId: storedId,
        remote: true,
        requestGateway
      })
      expect(next.refText).toBe(fileComplete.ref_text)
      expect(next.label).toBe(item.label)
    }
    expect(uploadAttachment.mock.calls.map(([input]) => input.path)).toEqual([
      'android-local://paste/pasted-content.txt',
      localPath
    ])
    expect(uploadAttachment.mock.calls.every(([input]) => !('name' in input))).toBe(true)
  })

  it('actual recorder stop/finalization passes fixed Blob bytes and mic-open owner across a scope switch', async () => {
    const { stopTrack } = installCaptureFixture()
    const transcribeBlob = vi.fn(async (audio: Blob) => {
      expect(await blobBytes(audio)).toEqual(fixedAudioBytes)
      expect(audio.type).toBe('audio/webm;codecs=opus')
      return { ok: true, transcript: 'სინთეზური დიქტაცია', provider: null }
    })
    installHost({ androidMedia: { transcribeBlob } })
    const actions = promptHook()
    let scope = { ...MAIN_COMPOSER_SCOPE, profile: 'example-profile', connectionId }
    const wrapper = ({ children }: PropsWithChildren) => (
      <ComposerScopeProvider value={scope}>{children}</ComposerScopeProvider>
    )
    const onTranscript = vi.fn()
    const focusInput = vi.fn()
    const recorder = renderHook(
      () =>
        useVoiceRecorder({
          maxRecordingSeconds: 10,
          onTranscribeAudio: actions.result.current.transcribeVoiceAudio,
          onTranscript,
          focusInput
        }),
      { wrapper }
    )
    act(() => recorder.result.current.dictate())
    await waitFor(() => expect(recorder.result.current.voiceStatus).toBe('recording'))
    scope = { ...scope, profile: 'other-profile', connectionId: 'other-connection' }
    recorder.rerender()
    act(() => recorder.result.current.dictate())
    await waitFor(() => expect(onTranscript).toHaveBeenCalledExactlyOnceWith('სინთეზური დიქტაცია'))
    expect(transcribeBlob).toHaveBeenCalledExactlyOnceWith(expect.any(Blob), { profile: 'example-profile', connectionId })
    expect(stopTrack).toHaveBeenCalledTimes(1)
    expect(focusInput).toHaveBeenCalledTimes(1)
    expect(transcribeAudioClientDirect).not.toHaveBeenCalled()
    expect(transcribeAudio).not.toHaveBeenCalled()
  })

  it('keeps non-Android PC paths on the original attach RPC even when the optional bridge exists', async () => {
    const uploadAttachment = vi.fn(async () => fileComplete)
    installHost({ androidMedia: { isLocalPath: () => false, uploadAttachment } })
    const gateway = vi.fn(async (method: string) => {
      if (method === 'file.attach') return fileComplete as never
      throw new Error(`Unexpected fixture gateway operation: ${method}`)
    })
    const original = attachment({ path: 'C:\\pc-fixture\\existing.txt', label: 'existing.txt' })
    const uploaded = await uploadComposerAttachment(original, {
      sessionId: runtimeId,
      storedSessionId: storedId,
      remote: false,
      requestGateway: gateway
    })
    expect(uploaded.refText).toBe(fileComplete.ref_text)
    expect(gateway).toHaveBeenCalledExactlyOnceWith('file.attach', {
      name: 'existing.txt',
      path: original.path,
      session_id: runtimeId
    })
    expect(uploadAttachment).not.toHaveBeenCalled()
  })

  it('keeps original Electron remote-byte attachment behavior when Android media is absent', async () => {
    const readFileDataUrl = vi.fn(async () => 'data:text/plain;base64,Zml4ZWQgZml4dHVyZQ==')
    installHost({ readFileDataUrl })
    const gateway = vi.fn(async (method: string) => {
      if (method === 'file.attach') return fileComplete as never
      throw new Error(`Unexpected fixture gateway operation: ${method}`)
    })
    await uploadComposerAttachment(attachment(), {
      sessionId: runtimeId,
      storedSessionId: storedId,
      remote: true,
      requestGateway: gateway
    })
    expect(gateway).toHaveBeenCalledExactlyOnceWith('file.attach', {
      name: '.ქართული.txt',
      path: localPath,
      session_id: runtimeId,
      data_url: 'data:text/plain;base64,Zml4ZWQgZml4dHVyZQ=='
    })
    expect(readFileDataUrl).toHaveBeenCalledExactlyOnceWith(localPath)
  })

  it('keeps the original direct transcription path when the Android bridge is absent', async () => {
    installHost({})
    vi.mocked(transcribeAudioClientDirect).mockResolvedValueOnce('Original direct fixture')
    const { result } = promptHook()
    const audio = new Blob(['fixed fixture'], { type: 'audio/webm' })
    const owner = { profile: 'example-profile', connectionId }
    expect(await result.current.transcribeVoiceAudio(audio, owner)).toBe('Original direct fixture')
    expect(transcribeAudioClientDirect).toHaveBeenCalledExactlyOnceWith(audio, owner)
    expect(transcribeAudio).not.toHaveBeenCalled()
  })

  it('actual voice-conversation turn finalizer reaches the same bounded recorder callback', async () => {
    installCaptureFixture()
    const transcribeBlob = vi.fn(async (audio: Blob) => {
      expect(await blobBytes(audio)).toEqual(fixedAudioBytes)
      return { ok: true, transcript: 'Synthetic voice conversation turn', provider: null }
    })
    installHost({ androidMedia: { transcribeBlob } })
    const actions = promptHook()
    const owner = { ...MAIN_COMPOSER_SCOPE, profile: 'example-profile', connectionId }
    const wrapper = ({ children }: PropsWithChildren) => (
      <ComposerScopeProvider value={owner}>{children}</ComposerScopeProvider>
    )
    const onSubmit = vi.fn()
    const conversation = renderHook(
      () =>
        useVoiceConversation({
          enabled: true,
          busy: false,
          onSubmit,
          onTranscribeAudio: actions.result.current.transcribeVoiceAudio,
          pendingResponse: () => null,
          consumePendingResponse: () => undefined
        }),
      { wrapper }
    )
    await act(async () => {
      await conversation.result.current.start()
    })
    await waitFor(() => expect(conversation.result.current.status).toBe('listening'))
    act(() => conversation.result.current.stopTurn())
    await waitFor(() => expect(onSubmit).toHaveBeenCalledExactlyOnceWith('Synthetic voice conversation turn'))
    await act(async () => {
      await conversation.result.current.end()
    })
    expect(transcribeBlob).toHaveBeenCalledExactlyOnceWith(expect.any(Blob), { profile: 'example-profile', connectionId })
    expect(transcribeAudioClientDirect).not.toHaveBeenCalled()
    expect(transcribeAudio).not.toHaveBeenCalled()
  })
})
