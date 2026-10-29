import { useCallback, useEffect, useRef, useState } from 'react'

import { resolveOwnerNow } from '@/api/client'
import { useI18n } from '@/i18n'
import { sanitizeTextForSpeech } from '@/lib/speech-text'
import {
  fetchVoiceLiveStatus,
  type LiveHistoryMessage,
  type LiveTranscriptFragment,
  VoiceLiveSession
} from '@/lib/voice-live'
import type { VoiceLiveCloseDetails } from '@/lib/voice-live-debug'
import { codexVoiceIntent, type VoiceHandoff, type VoiceTaskSnapshot } from '@/lib/voice-live-task'
import { CodexTaskLink } from '@/lib/voice-live-task-link'
import { isVoiceStopCommand } from '@/lib/voice-stop-word'
import { notify, notifyError } from '@/store/notifications'

import { useComposerScope } from '../scope'

import { micError } from './use-mic-recorder'
import type { ConversationStatus } from './use-voice-conversation'

/** How long an accepted delegation may sit before the gateway shows the turn running. */
const SUBMIT_SETTLE_GRACE_MS = 15_000
/** Quiet after the last user transcript fragment before the utterance is judged
 *  as a whole ("stop" ends the chat; "stop the container" is a request). */
const UTTERANCE_SETTLE_MS = 1_500

interface PendingVoiceResponse {
  id: string
  pending: boolean
  text: string
}

interface VoiceLiveConversationOptions {
  sessionId?: string | null
  /** Durable chat/lineage identity; null is a draft awaiting first adoption. */
  queueSessionKey?: string | null
  taskRequest?: (action?: string, taskId?: string, text?: string) => Promise<VoiceTaskSnapshot>
  busy: boolean
  enabled: boolean
  onFatalError?: () => void
  /** Interrupt the in-flight Hermes turn (Stop-button seam). Fired when a new
   *  delegation supersedes one still running. */
  onInterrupt?: () => Promise<void> | void
  onStopWord?: () => void
  /** Submit a Hermes turn: `text` is the user's last words (the bubble and the
   *  persisted row), `voiceContext` the recent spoken exchange for the model. */
  onSubmit: (text: string, voiceContext: string, handoff?: VoiceHandoff) => Promise<void> | void
  pendingResponse: () => PendingVoiceResponse | null
  /** Codex returns the final bubble once, without replaying tool narration. */
  pendingFinalResponse?: () => PendingVoiceResponse | null
  consumePendingResponse: () => void
  /** Text turns to seed the live model with when the session opens. */
  seedHistory: () => LiveHistoryMessage[]
  /** Names of tools currently running in the turn (quiet progress for the voice). */
  activeToolLabel?: () => null | string
  beforeMicOpen?: () => Promise<void> | void
}

/** Turn transcript fragments into the Hermes turn: `prompt` is what the user
 *  last said (the persisted user row), `context` the recent spoken exchange
 *  that rides the model input only (see tools/voice_live.py). */
export function delegationPrompt(context: LiveTranscriptFragment[]): { context: string; prompt: string } {
  const turns: Array<{ speaker: 'assistant' | 'user'; text: string; turnId?: string }> = []

  for (const fragment of context) {
    const last = turns.at(-1)

    if (last && last.speaker === fragment.speaker && last.turnId === fragment.turnId) {
      last.text += fragment.text
    } else {
      turns.push({ speaker: fragment.speaker, text: fragment.text, turnId: fragment.turnId })
    }
  }

  const lastUser = [...turns].reverse().find(turn => turn.speaker === 'user')
  const prompt = (lastUser?.text ?? '').replace(/\s+/g, ' ').trim()

  const transcript = turns
    .map(turn => `${turn.speaker === 'user' ? 'User' : 'Voice assistant'}: ${turn.text.replace(/\s+/g, ' ').trim()}`)
    .filter(line => !line.endsWith(': '))
    .join('\n')

  return { context: transcript, prompt: prompt || transcript.slice(-400) }
}

/**
 * Body of the session-end toast. `connection_lost` and `closed` are our own
 * machine reasons (`lib/voice-live.ts`) and get i18n copy; so does a blank
 * reason, which has no wording of its own. Any other reason is server-sent and
 * unbounded, so it passes through verbatim (issue #111987 — no redaction claim
 * for vendor strings).
 */
export function liveEndedMessage(
  reason: string,
  usageSeconds: null | number,
  copy: { liveEndedClosed: string; liveEndedConnectionLost: string }
): string {
  let text = reason?.trim() ?? ''

  if (text === 'connection_lost') {
    text = copy.liveEndedConnectionLost
  } else if (text === 'closed' || !text) {
    text = copy.liveEndedClosed
  }

  return usageSeconds != null ? `${text} (${Math.round(usageSeconds)}s)` : text
}

/**
 * GPT-Live conversation engine — same public shape as `useVoiceConversation`
 * so the composer can mount either from `voice.voice_chat_mode`.
 *
 * Status mapping: `listening` = session up, voice idle; `speaking` = the
 * remote track is producing audio; `thinking` = a delegation is in flight in
 * Hermes. There is no `transcribing` phase: the voice model owns speech.
 */
export function useVoiceLiveConversation({
  sessionId,
  queueSessionKey,
  taskRequest,
  busy,
  enabled,
  onFatalError,
  onInterrupt,
  onStopWord,
  onSubmit,
  pendingResponse,
  pendingFinalResponse,
  consumePendingResponse,
  seedHistory,
  activeToolLabel,
  beforeMicOpen
}: VoiceLiveConversationOptions) {
  const { t } = useI18n()
  const voiceCopy = t.notifications.voice
  const [status, setStatus] = useState<ConversationStatus>('idle')
  const [muted, setMuted] = useState(false)
  const [level, setLevel] = useState(0)
  // Mirrors delegationRef for the reply-drive effect: a new delegation must
  // restart the feed loop, and a ref write alone does not re-render.
  const [activeDelegation, setActiveDelegation] = useState<null | string>(null)
  const sessionRef = useRef<null | VoiceLiveSession>(null)
  const taskLinkRef = useRef<CodexTaskLink | null>(null)
  // The scope's session owner (a Bot's own connection + profile) picks the
  // GPT-Live backend and voice; a ref keeps the long-lived start closures
  // reading the current value.
  const { connectionId: ownerConnectionId, profile: ownerProfile } = useComposerScope()
  const ownerRef = useRef({ connectionId: ownerConnectionId, profile: ownerProfile })
  ownerRef.current = { connectionId: ownerConnectionId, profile: ownerProfile }
  // Bumped by every start/end so an in-flight start() that lost the race
  // (StrictMode double-effect, quick toggle) closes its session instead of
  // leaving a second billed one running.
  const startEpochRef = useRef(0)
  const startingRef = useRef(false)
  // Set at delegation submit; a turn is only "settled" once it has been seen
  // running (busy) or produced a reply — the gateway ack lags the submit.
  const turnObservedRef = useRef(false)
  const submittedAtRef = useRef(0)
  const enabledRef = useRef(enabled)
  const busyRef = useRef(busy)
  const speakingRef = useRef(false)
  const userUtteranceRef = useRef('')
  const utteranceTimerRef = useRef<null | number>(null)
  const delegationRef = useRef<null | string>(null)
  const spokenLengthRef = useRef(0)
  const spokenResponseIdRef = useRef<null | string>(null)
  const lastToolLabelRef = useRef<null | string>(null)
  const wasEnabledRef = useRef(enabled)

  const latest = useRef({
    taskRequest,
    activeToolLabel,
    beforeMicOpen,
    onFatalError,
    onInterrupt,
    onStopWord,
    onSubmit,
    pendingResponse,
    pendingFinalResponse,
    consumePendingResponse,
    seedHistory
  })

  latest.current = {
    taskRequest,
    activeToolLabel,
    beforeMicOpen,
    onFatalError,
    onInterrupt,
    onStopWord,
    onSubmit,
    pendingResponse,
    pendingFinalResponse,
    consumePendingResponse,
    seedHistory
  }

  // eslint-disable-next-line no-restricted-syntax -- legitimate non-atom ref write (see eslint rule comment)
  useEffect(() => {
    enabledRef.current = enabled
  }, [enabled])

  // eslint-disable-next-line no-restricted-syntax -- legitimate non-atom ref write (see eslint rule comment)
  useEffect(() => {
    busyRef.current = busy
  }, [busy])

  const setDelegation = useCallback((id: null | string) => {
    delegationRef.current = id
    setActiveDelegation(id)
  }, [])

  const refreshStatus = useCallback(() => {
    if (!sessionRef.current) {
      setStatus('idle')

      return
    }

    if (speakingRef.current) {
      setStatus('speaking')
    } else if (delegationRef.current) {
      setStatus('thinking')
    } else {
      setStatus('listening')
    }
  }, [])

  const end = useCallback(async (details: VoiceLiveCloseDetails = { close_trigger: 'requested' }) => {
    taskLinkRef.current?.close()
    taskLinkRef.current = null
    startEpochRef.current += 1
    startingRef.current = false

    if (utteranceTimerRef.current) {
      window.clearTimeout(utteranceTimerRef.current)
      utteranceTimerRef.current = null
    }

    userUtteranceRef.current = ''
    const session = sessionRef.current
    sessionRef.current = null
    setDelegation(null)
    spokenResponseIdRef.current = null
    spokenLengthRef.current = 0
    speakingRef.current = false
    session?.close(details)
    setMuted(false)
    setLevel(0)
    setStatus('idle')
  }, [setDelegation])

  const start = useCallback(async () => {
    if (sessionRef.current || startingRef.current) {
      return
    }

    startingRef.current = true
    const epoch = ++startEpochRef.current

    try {
      await latest.current.beforeMicOpen?.()
    } catch {
      // A wake-pause failure must not block an explicit start.
    }

    if (!enabledRef.current || startEpochRef.current !== epoch) {
      startingRef.current = false

      return
    }

    const owner = resolveOwnerNow(ownerRef.current)
    const liveStatus = await fetchVoiceLiveStatus(owner)

    if (!enabledRef.current || startEpochRef.current !== epoch) {return}

    const session = new VoiceLiveSession(
      {
        // The voice model answers a bare "stop" itself (it just goes quiet) and
        // never delegates it, so the spoken stop phrase is judged on the user
        // transcript once the utterance settles.
        onTranscript: fragment => {
          if (fragment.speaker !== 'user') {
            return
          }

          if (sessionRef.current !== session) {
            return
          }

          if (session.finalResultOnly) {
            const intent = codexVoiceIntent(fragment.text)

            if (intent === 'silence' || intent === 'stop') {session.silence()}

            if (fragment.final && ['silence', 'stop', 'cancel', 'end'].includes(intent)) {
              void taskLinkRef.current?.handle(fragment.text, '', undefined, fragment.turnId).catch(error => notifyError(error, voiceCopy.liveError))
            } else if (fragment.final) {session.resumeSpeech()}

            return
          }

          userUtteranceRef.current += fragment.text

          if (utteranceTimerRef.current) {
            window.clearTimeout(utteranceTimerRef.current)
          }

          utteranceTimerRef.current = window.setTimeout(() => {
            utteranceTimerRef.current = null
            const utterance = userUtteranceRef.current
            userUtteranceRef.current = ''

            if (sessionRef.current === session && isVoiceStopCommand(utterance)) {
              void end({ close_trigger: 'spoken_end' })
              latest.current.onStopWord?.()
            }
          }, UTTERANCE_SETTLE_MS)
        },
        onClosed: (reason, usageSeconds) => {
          if (sessionRef.current !== session) {
            return
          }

          taskLinkRef.current?.close()
          taskLinkRef.current = null
          sessionRef.current = null
          setDelegation(null)
          setStatus('idle')

          if (reason !== 'close_requested' && reason !== 'startup_failed') {
            notify({
              kind: 'warning',
              message: liveEndedMessage(reason, usageSeconds, voiceCopy),
              title: voiceCopy.liveEnded
            })
            latest.current.onFatalError?.()
          }
        },
        onDelegation: (delegationId, context, handoff) => {
          if (sessionRef.current !== session) {
            return
          }

          const { context: voiceContext, prompt } = delegationPrompt(context)

          if (session.finalResultOnly) {
            void taskLinkRef.current?.handle(prompt, voiceContext, handoff, handoff?.user_turn_id).catch(error => {
              notifyError(error, voiceCopy.liveDelegationFailed)
              session.delegationFailed(delegationId)
              session.speak(delegationId, 'Hermes could not verify or accept that request. No automatic retry will run. Check the chat.', 'error')
            })

            return
          }

          // A spoken stop command ends the conversation instead of becoming a turn.
          if (prompt && isVoiceStopCommand(prompt)) {
            void end({ close_trigger: 'spoken_end' })
            latest.current.onStopWord?.()

            return
          }

          // A newer request supersedes an in-flight turn: stop it so the answer
          // the voice speaks is for what the user asked last.
          if (busyRef.current) {
            session.interrupted()
            void latest.current.onInterrupt?.()
          }

          setDelegation(delegationId)
          spokenResponseIdRef.current = null
          spokenLengthRef.current = 0
          lastToolLabelRef.current = null
          turnObservedRef.current = false
          submittedAtRef.current = Date.now()
          latest.current.consumePendingResponse()
          refreshStatus()
          void Promise.resolve(latest.current.onSubmit(prompt, voiceContext)).catch(error => {
            if (sessionRef.current !== session || delegationRef.current !== delegationId) {
              return
            }

            session.delegationFailed(delegationId)
            notifyError(error, voiceCopy.liveDelegationFailed)
            session.speak(delegationId, 'Sorry, I could not reach Hermes for that request.')
            setDelegation(null)
            refreshStatus()
          })
        },
        onError: (message, fatal) => {
          notify({ kind: fatal ? 'error' : 'warning', message, title: voiceCopy.liveError })
        },
        onSpeakingChange: speaking => {
          speakingRef.current = speaking
          setLevel(speaking ? 0.6 : 0)
          refreshStatus()
        }
      },
      owner,
      liveStatus?.mode === 'codex-live' && liveStatus.debug === true
    )

    sessionRef.current = session

    if (liveStatus?.mode === 'codex-live') {
      taskLinkRef.current = new CodexTaskLink({
        session,
        activeToolLabel: () => latest.current.activeToolLabel?.() ?? null,
        request: (action, taskId, text) => {
          const request = latest.current.taskRequest

          if (!request) {return Promise.reject(new Error('Voice task continuity is unavailable'))}

          return request(action, taskId, text)
        },
        submit: async (text, context, handoff) => {await latest.current.onSubmit(text, context, handoff)},
        notice: message => notify({kind: 'info', message}),
        end: () => {void end({ close_trigger: 'spoken_end' }); latest.current.onStopWord?.()},
        onError: error => notifyError(error, voiceCopy.liveError)
      })
    }

    startingRef.current = false
    setMuted(false)
    setStatus('thinking')

    try {
      await session.start(latest.current.seedHistory())

      if (sessionRef.current !== session || startEpochRef.current !== epoch) {
        session.close({ close_trigger: 'startup_superseded' })

        return
      }

      refreshStatus()
    } catch (error) {
      if (sessionRef.current === session) {
        sessionRef.current = null
      }

      session.close({ close_trigger: 'startup_failed' })

      if (startEpochRef.current !== epoch) {
        return
      }

      // Only a mic DOMException gets the recorder's copy: this catch also
      // takes non-mic start failures ('GPT-Live session already started',
      // 'Missing local SDP offer', API errors) — those keep their own message.
      notifyError(error instanceof DOMException ? micError(error, voiceCopy) : error, voiceCopy.couldNotStartSession)
      setStatus('idle')
      latest.current.onFatalError?.()
    }
  }, [end, refreshStatus, setDelegation, voiceCopy])

  // Drive the reply back into the voice: stream commentary as Hermes writes
  // it (sentence-chunked), quiet tool progress as thinking appends, and clear
  // the delegation when the turn settles.
  // eslint-disable-next-line no-restricted-syntax -- turn-coordination refs (delegation id / spoken cursor), not atom mirrors
  useEffect(() => {
    const session = sessionRef.current
    const delegationId = delegationRef.current

    if (!session || session.finalResultOnly || !delegationId) {
      return undefined
    }

    const tick = () => {
      if (sessionRef.current !== session || delegationRef.current !== delegationId) {
        return
      }

      if (busyRef.current) {
        turnObservedRef.current = true
      }

      const tool = latest.current.activeToolLabel?.() ?? null

      if (tool && tool !== lastToolLabelRef.current) {
        lastToolLabelRef.current = tool
        session.think(delegationId, `Hermes is working: ${tool}. Not done yet.`)
      }

      const response =
        session.finalResultOnly && latest.current.pendingFinalResponse
          ? latest.current.pendingFinalResponse()
          : latest.current.pendingResponse()

      if (response) {
        turnObservedRef.current = true

        if (spokenResponseIdRef.current !== response.id) {
          spokenResponseIdRef.current = response.id
          spokenLengthRef.current = 0
        }

        const spoken = sanitizeTextForSpeech(response.text)

        // Append only completed sentences while streaming; the tail lands on settle.
        if (response.pending || busyRef.current) {
          if (session.finalResultOnly) {
            return
          }

          const boundary = spoken.lastIndexOf('. ', spoken.length - 2)
          const cut = boundary > spokenLengthRef.current ? boundary + 1 : spokenLengthRef.current

          if (cut > spokenLengthRef.current) {
            session.speak(delegationId, spoken.slice(spokenLengthRef.current, cut))
            spokenLengthRef.current = cut
          }

          return
        }

        if (spoken.length > spokenLengthRef.current) {
          session.speak(delegationId, spoken.slice(spokenLengthRef.current))
          spokenLengthRef.current = spoken.length
        }

        latest.current.consumePendingResponse()
        setDelegation(null)
        refreshStatus()

        return
      }

      // The submit ack lags: give the turn time to be seen running before
      // reading "idle and no reply" as a finished turn.
      if (
        !busyRef.current &&
        (turnObservedRef.current || Date.now() - submittedAtRef.current > SUBMIT_SETTLE_GRACE_MS)
      ) {
        // Turn settled without a speakable reply (tool-only, error, interrupted).
        session.delegationFailed(delegationId)

        if (spokenLengthRef.current === 0) {
          if (session.finalResultOnly) {
            session.speak(
              delegationId,
              'Hermes returned no answer. The task may have failed or been interrupted; check the chat before assuming it completed.'
            )
          } else {
            session.think(delegationId, 'Hermes finished that request without a spoken result.')
          }
        }

        setDelegation(null)
        refreshStatus()
      }
    }

    const timer = window.setInterval(tick, 200)
    tick()

    return () => window.clearInterval(timer)
  }, [activeDelegation, busy, refreshStatus, setDelegation, status])

  const toggleMute = useCallback(() => {
    setMuted(value => {
      const next = !value
      sessionRef.current?.setMuted(next)

      return next
    })
  }, [])

  /** No explicit turn boundary in full duplex; a nudge tells the voice to answer now. */
  const stopTurn = useCallback(() => {
    sessionRef.current?.instruct('The user has finished speaking. Respond now to what they said.')
  }, [])

  // eslint-disable-next-line no-restricted-syntax -- legitimate non-atom ref write (see eslint rule comment)
  useEffect(() => {
    if (enabled && !wasEnabledRef.current) {
      void start()
    }

    if (!enabled && wasEnabledRef.current) {
      void end({ close_trigger: 'disabled' })
    }

    wasEnabledRef.current = enabled
  }, [enabled, end, start])

  const scope = resolveOwnerNow(ownerRef.current)
  // Untagged connections use the local pool; publishing its explicit name is
  // not a backend switch. Profiles and all other connections stay distinct.
  const connectionId = scope.connectionId ?? 'local'
  const profile = scope.profile
  const scopeKey = JSON.stringify([connectionId, profile])
  // Runtime ids rotate/rebind within a chat. An explicit null durable key is
  // a draft, even while the previous runtime id is still being cleared.
  const conversationKey = queueSessionKey === undefined ? sessionId : queueSessionKey
  const previousScope = useRef({scopeKey, conversationKey, connectionId, profile})
  // eslint-disable-next-line no-restricted-syntax -- previous-owner transition token, not an atom mirror
  useEffect(() => {
    const previous = previousScope.current

    if (previous.scopeKey !== scopeKey || (previous.conversationKey && previous.conversationKey !== conversationKey)) {
      void end({ close_trigger: 'scope_changed',
        conversation_changed: previous.conversationKey !== conversationKey,
        connection_changed: previous.connectionId !== connectionId,
        profile_changed: previous.profile !== profile })
    }

    previousScope.current = {scopeKey, conversationKey, connectionId, profile}
  }, [end, scopeKey, conversationKey, connectionId, profile])

  useEffect(() => () => void end({ close_trigger: 'unmount' }), [end])

  return { end, level, muted, start, status, stopTurn, toggleMute }
}
