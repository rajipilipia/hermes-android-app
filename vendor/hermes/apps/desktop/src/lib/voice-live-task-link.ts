import type { VoiceLiveSession } from './voice-live'
import {codexVoiceIntent, voiceContextPacket, voiceFollowupText, type VoiceHandoff, voiceTaskActive, type VoiceTaskSnapshot} from './voice-live-task'

interface TaskLinkOptions {
  session: VoiceLiveSession
  request: (action?: string, taskId?: string, text?: string) => Promise<VoiceTaskSnapshot>
  submit: (text: string, context: string, handoff: VoiceHandoff) => Promise<unknown>
  notice: (text: string) => void
  end: () => void
  onError: (error: unknown) => void
  activeToolLabel?: () => string | null
}

/** One voice connection's view of backend receipts. Closing it never controls the task. */
export class CodexTaskLink {
  private closed = false
  private reading = false
  private submitting = false
  private readErrorReported = false
  private packet = ''
  private snapshot: VoiceTaskSnapshot = {task:null,history:[],pending:null}
  private handled = new Set<string>()
  private timer: ReturnType<typeof setInterval>

  constructor(private options: TaskLinkOptions) {
    this.timer = setInterval(() => {void this.refresh().catch(options.onError)}, 1000)
    void this.refresh().catch(options.onError)
  }

  close(): void {this.closed = true; clearInterval(this.timer)}

  private publish(next: VoiceTaskSnapshot): void {
    if (this.closed) {return}
    this.snapshot = next
    const packet = voiceContextPacket(next, this.options.activeToolLabel?.())

    if (packet !== this.packet && this.options.session.updateContext(packet)) {this.packet = packet}
    const task = next.task

    // Original epoch + original delegation, never whichever delegation happened most recently.
    if (task?.epoch === this.options.session.epoch && ['completed','failed','cancelled'].includes(task.status)) {
      this.options.session.speak(task.delegation_id, task.result || `Hermes task ${task.status}.`)
    }
  }

  async refresh(): Promise<void> {
    if (this.closed || this.reading) {return}
    this.reading = true

    try {this.publish(await this.options.request()); this.readErrorReported = false}
    catch (error) {
      this.options.session.updateContext('Hermes connection unavailable. Current task state is unconfirmed, not failed or cancelled. Do not execute or retry old requests.')

      if (!this.readErrorReported) {this.options.onError(error); this.readErrorReported = true}
    }
    finally {this.reading = false}
  }

  async handle(text: string, context: string, handoff?: VoiceHandoff, turnId?: string): Promise<void> {
    if (this.closed) {return}
    const intent = codexVoiceIntent(text)

    if (!handoff && intent === 'request') {return}
    const key = turnId || handoff?.user_turn_id || handoff?.id || text

    if (this.handled.has(key)) {
      if (handoff) {this.options.session.disposition(handoff.delegation_id, 'duplicate')}

      return
    }

    this.handled.add(key)
    const {session, notice} = this.options

    const disposition = (outcome: string) => {
      if (handoff) {session.disposition(handoff.delegation_id, outcome)}
    }

    if (intent === 'silence' || intent === 'stop') {
      disposition('silenced')
      session.silence()
      session.instruct('Speech interrupted only. The Hermes task has NOT been cancelled. Wait for the next user request.')

      if (intent === 'stop') {notice('Speech silenced. Do you mean cancel the task or end the call?')}

      return
    }

    session.resumeSpeech()

    if (intent === 'end') {
      disposition('end_call')

      try {
        this.publish(await this.options.request())
        notice(voiceTaskActive(this.snapshot.task) ? 'Voice call ended. Hermes work continues in this chat.' : 'Voice call ended. Check this chat for the saved task state.')
      } catch {
        notice('Voice call ended. Hermes task state is unconfirmed; disconnecting did not cancel it.')
      } finally {this.options.end()}

      return
    }

    // Every decision is reconciled with Hermes, not stale busy flags or voice guesses.
    this.publish(await this.options.request())

    if (this.closed) {return}
    const task = this.snapshot.task

    if (intent === 'status') {
      disposition('status')

      if (handoff) {session.speak(handoff.delegation_id, task ? `Hermes task ${task.status}. ${task.result}` : 'No verified voice task is recorded in this chat.', 'status')}

      return
    }

    if (this.snapshot.pending) {
      disposition('pending')
      notice(this.snapshot.pending)

      if (handoff) {session.speak(handoff.delegation_id, this.snapshot.pending, 'pending')}

      // Cancellation is permitted while awaiting approval; speech can never approve.
      if (intent !== 'cancel') {return}
    }

    if (intent === 'cancel' || intent === 'correction' || (handoff && voiceTaskActive(task))) {
      if (!voiceTaskActive(task) || !task) {
        disposition('no_active_task')
        notice('There is no identified running voice task to change.')

        return
      }

      const followup = intent === 'cancel' ? text : voiceFollowupText(text, context)

      if (followup === null) {
        const message = 'Please give a shorter follow-up (at most 2000 characters). The existing task was not changed.'
        disposition('error')
        notice(message)

        if (handoff) {session.speak(handoff.delegation_id, message, 'error')}

        return
      }

      disposition(intent === 'cancel' ? 'cancel_requested' : 'steer_requested')

      const next = await this.options.request(intent === 'cancel' ? 'cancel' : 'steer', task.id,
        followup)

      this.publish(next)

      if (this.closed) {return}

      if (intent === 'cancel') {
        notice('Cancellation requested; waiting for Hermes confirmation.')

        return
      }

      const queued = next.control === 'queued' || next.control === 'accepted'

      const message = queued
        ? 'Follow-up queued for the existing Hermes task; delivery is not yet confirmed.'
        : 'Hermes could not queue this follow-up. The existing task was not cancelled or restarted. Check the chat.'

      notice(message)

      if (handoff) {session.speak(handoff.delegation_id, message, queued ? 'status' : 'error')}

      return
    }

    if (!handoff) {return}

    if (voiceTaskActive(task) || this.submitting) {
      disposition('busy')
      session.speak(handoff.delegation_id, 'Hermes is still working on the existing task. It has not been cancelled. Wait, give a correction, or explicitly cancel that task.', 'busy')

      return
    }

    this.submitting = true
    disposition('submit_requested')

    try {await this.options.submit(text, context, handoff); await this.refresh()}
    catch (error) {
      // A lost acknowledgement cannot overrule Hermes' durable acceptance receipt.
      await this.refresh()
      const accepted = this.snapshot.task

      if (accepted?.handoff_id !== handoff.id || accepted.epoch !== handoff.epoch) {throw error}
    }
    finally {this.submitting = false}
  }
}
