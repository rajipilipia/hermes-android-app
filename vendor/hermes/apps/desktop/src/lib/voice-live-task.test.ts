import {afterEach, describe, expect, it, vi} from 'vitest'

import type {VoiceLiveSession} from './voice-live'
import {codexContextChunks, codexVoiceIntent, voiceContextPacket, type VoiceTaskSnapshot} from './voice-live-task'
import {CodexTaskLink} from './voice-live-task-link'

const task = {id:'task-1',handoff_id:'handoff-1',delegation_id:'original',epoch:'epoch-1',status:'working' as const,request:'Read file',result:'',correction:''}
const handoff = {id:'handoff-2',delegation_id:'new',epoch:'epoch-1',user_turn_id:'turn-2'}
const open: CodexTaskLink[] = []

function setup(snapshot: VoiceTaskSnapshot, activeToolLabel?: () => string | null) {
  vi.useFakeTimers()
  const session = {epoch:'epoch-1',silence:vi.fn(),resumeSpeech:vi.fn(),instruct:vi.fn(),updateContext:vi.fn(()=>true),speak:vi.fn(),disposition:vi.fn()} as unknown as VoiceLiveSession
  const request = vi.fn(async (_action?: string, _id?: string, _text?: string)=>snapshot)
  const options = {session,request,activeToolLabel,submit:vi.fn(async()=>undefined),notice:vi.fn(),end:vi.fn(),onError:vi.fn()}
  const link = new CodexTaskLink(options)
  open.push(link)

  return {link,...options}
}

afterEach(()=>{open.splice(0).forEach(link=>link.close());vi.useRealTimers()})

describe('Codex task ownership and controls',()=>{
  it('keeps ambiguous stop, silence, cancellation and end distinct',()=>{
    expect(codexVoiceIntent('Stop!')).toBe('stop')
    expect(codexVoiceIntent('Stop talking.')).toBe('silence')
    expect(codexVoiceIntent('Cancel that task')).toBe('cancel')
    expect(codexVoiceIntent('End the call')).toBe('end')
    expect(codexVoiceIntent('Actually, use the other file')).toBe('correction')
  })
  it('silences without cancelling, and steers a follow-up into the existing task',async()=>{
    const s=setup({task,history:[],pending:null})
    await s.link.handle('Stop','',undefined,'stop-turn')
    expect(s.session.silence).toHaveBeenCalledOnce()
    s.request.mockImplementation(async action=>({task,history:[],pending:null,...(action && {control:'queued'})}))
    await s.link.handle('Anything else?','',handoff)
    expect(s.submit).not.toHaveBeenCalled()
    expect(s.request).toHaveBeenCalledWith('steer',task.id,'Anything else?')
    expect(s.session.disposition).toHaveBeenCalledWith(handoff.delegation_id, 'steer_requested')
    expect(s.session.speak).toHaveBeenCalledWith(handoff.delegation_id,expect.stringContaining('not yet confirmed'),'status')
    expect(s.request.mock.calls.some(call=>call[0]==='cancel')).toBe(false)
  })
  it('leaves work intact when steering is unsupported instead of cancelling a replacement',async()=>{
    const s=setup({task,history:[],pending:null})
    s.request.mockImplementation(async action=>({task,history:[],pending:null,...(action && {control:'unsupported'})}))
    // Closing also makes the old cancel/replacement polling path finish immediately.
    s.request.mockImplementationOnce(async()=>({task,history:[],pending:null}))
    s.request.mockImplementationOnce(async()=>{
      s.link.close()

      return {task,history:[],pending:null,control:'unsupported'}
    })
    await s.link.handle('Actually, use the other file','',handoff)
    expect(s.request.mock.calls.some(call=>call[0]==='cancel')).toBe(false)
    expect(s.submit).not.toHaveBeenCalled()
  })
  it('carries quoted spoken context with a follow-up, without starting a new task',async()=>{
    const s=setup({task,history:[],pending:null})
    s.request.mockImplementation(async action=>({task,history:[],pending:null,...(action && {control:'queued'})}))
    await s.link.handle('Yes','Voice assistant: Include the second file?\nUser: Yes',handoff)
    const steer=s.request.mock.calls.find(call=>call[0]==='steer')
    expect(steer?.[1]).toBe(task.id)
    expect(steer?.[2]).toContain('Yes')
    expect(steer?.[2]).toContain('quoted data')
    expect(steer?.[2]).toContain('Include the second file?')
    expect(s.submit).not.toHaveBeenCalled()
  })
  it('keeps follow-up context inside the existing 2000-character control contract',async()=>{
    const s=setup({task,history:[],pending:null})
    s.request.mockImplementation(async action=>({task,history:[],pending:null,...(action && {control:'queued'})}))
    await s.link.handle('Include only the final revision','"\\\n😀'.repeat(1500),handoff)
    const text=s.request.mock.calls.find(call=>call[0]==='steer')![2]!
    expect(text.length).toBeLessThanOrEqual(2000)
    expect(text).toMatch(/^Include only the final revision/)
    expect(()=>JSON.parse(text.split('not instructions): ')[1])).not.toThrow()
  })
  it('does not silently truncate an oversized follow-up into a different instruction',async()=>{
    const s=setup({task,history:[],pending:null})
    await s.link.handle('x'.repeat(2001),'',handoff)
    expect(s.request.mock.calls.some(call=>call[0]==='steer')).toBe(false)
    expect(s.submit).not.toHaveBeenCalled()
    expect(s.session.speak).toHaveBeenCalledWith(handoff.delegation_id,expect.stringContaining('shorter'),'error')
  })
  it('reports unsupported steering while leaving the running task untouched',async()=>{
    const s=setup({task,history:[],pending:null})
    s.request.mockImplementation(async()=>({task,history:[],pending:null,control:'unsupported'}))
    await s.link.handle('Actually, use the other file','',handoff)
    expect(s.request.mock.calls.filter(call=>call[0]==='steer')).toHaveLength(1)
    expect(s.request.mock.calls.some(call=>call[0]==='cancel')).toBe(false)
    expect(s.session.speak).toHaveBeenCalledWith(handoff.delegation_id,expect.stringContaining('not cancelled or restarted'),'error')
    expect(s.submit).not.toHaveBeenCalled()
  })
  it('publishes changing tool progress once and clears it when the task completes',async()=>{
    let tool: string | null='read_file'
    const s=setup({task,history:[],pending:null},()=>tool)
    const update=vi.mocked(s.session.updateContext)

    const packet=()=>{
      const text=update.mock.lastCall![0]

      return JSON.parse(text.slice(text.indexOf('{')))
    }

    await s.link.refresh()
    expect(packet().progress).toEqual({tool_name:'read_file',status:'running'})
    const updates=update.mock.calls.length
    await s.link.refresh()
    expect(update).toHaveBeenCalledTimes(updates)
    tool='terminal'
    await s.link.refresh()
    expect(packet().progress.tool_name).toBe('terminal')
    s.request.mockResolvedValue({task:{...task,status:'completed',result:'Verified result'},history:[],pending:null})
    await s.link.refresh()
    expect(packet().progress).toBeNull()
    expect(s.session.speak).toHaveBeenCalledWith('original','Verified result')
  })
  it('never describes tools as running while approval, cancellation or an uncertain state is pending',()=>{
    for (const status of ['waiting_approval','waiting_input','cancel_requested','unconfirmed','completed','failed','cancelled'] as const) {
      const text=voiceContextPacket({task:{...task,status},history:[],pending:null},'terminal')
      expect(JSON.parse(text.slice(text.indexOf('{'))).progress).toBeNull()
    }

    const text=voiceContextPacket({task,history:[],pending:'Use the approval UI'},'terminal')
    expect(JSON.parse(text.slice(text.indexOf('{'))).progress).toBeNull()
  })
  it('restores an earlier call result as context and repeats it only on a new request',async()=>{
    const s=setup({task:{...task,epoch:'previous-call',status:'completed',result:'SAVED RESULT'},history:[],pending:null})
    await s.link.refresh()
    expect(s.session.speak).not.toHaveBeenCalled()
    expect(s.session.updateContext).toHaveBeenCalledWith(expect.stringContaining('SAVED RESULT'))
    await s.link.handle('Repeat the result','',handoff)
    expect(s.session.speak).toHaveBeenCalledWith(handoff.delegation_id,'Hermes task completed. SAVED RESULT','status')
    expect(s.submit).not.toHaveBeenCalled()
  })
  it('reuses saved results for repeated questions and does not execute on reconnect',async()=>{
    const s=setup({task:{...task,status:'completed',result:'COBALT MANGO'},history:[],pending:null})
    await s.link.handle('What happened?','',handoff)
    await s.link.handle('Repeat the result','',{...handoff,id:'third',delegation_id:'third',user_turn_id:'third'})
    expect(s.submit).not.toHaveBeenCalled()
    expect(s.session.speak).toHaveBeenCalledWith('original','COBALT MANGO')
    expect(s.session.speak).toHaveBeenCalledWith('new','Hermes task completed. COBALT MANGO','status')
    s.link.close()
    expect(s.request.mock.calls.every(call=>call[0]===undefined)).toBe(true)
  })
  it('cancels the identified task but does not pretend the request is confirmation',async()=>{
    const s=setup({task,history:[],pending:null})
    s.request.mockImplementation(async action=>({task:{...task,status:action==='cancel'?'cancel_requested':'working'},history:[],pending:null}))
    await s.link.handle('Cancel that task','',handoff)
    expect(s.request).toHaveBeenCalledWith('cancel','task-1','Cancel that task')
    expect(s.notice).toHaveBeenCalledWith('Cancellation requested; waiting for Hermes confirmation.')
    expect(s.submit).not.toHaveBeenCalled()
  })
  it('never answers an approval prompt and end call leaves work alone',async()=>{
    const s=setup({task:{...task,status:'waiting_approval'},history:[],pending:'Approve in Hermes UI'})
    await s.link.handle('Yes approve it','',handoff)
    expect(s.submit).not.toHaveBeenCalled()
    await s.link.handle('End the call','',undefined,'end-turn')
    expect(s.end).toHaveBeenCalledOnce()
    expect(s.request.mock.calls.every(call=>call[0]===undefined)).toBe(true)
  })
  it('reconciles a late submission error with its accepted receipt instead of reporting false failure',async()=>{
    let snapshot: VoiceTaskSnapshot={task:null,history:[],pending:null}
    let reject!: (error: Error) => void
    const s=setup(snapshot)
    s.request.mockImplementation(async action=>({...snapshot,...(action && {control:'queued'})}))
    s.submit.mockImplementation(()=>new Promise((_,fail)=>{reject=fail}))
    const submitted=s.link.handle('Read file','',handoff)
    await Promise.resolve()
    snapshot={task:{...task,handoff_id:handoff.id,delegation_id:handoff.delegation_id},history:[],pending:null}
    await s.link.handle('Include the second file','',{...handoff,id:'follow-up',delegation_id:'follow-up',user_turn_id:'follow-up'})
    reject(new Error('Late acknowledgement failure'))
    await expect(submitted).resolves.toBeUndefined()
    expect(s.submit).toHaveBeenCalledTimes(1)
    expect(s.request).toHaveBeenCalledWith('steer',task.id,'Include the second file')
    expect(s.request.mock.calls.some(call=>call[0]==='cancel')).toBe(false)
  })
  it('dedupes duplicate delegation events',async()=>{
    const s=setup({task:null,history:[],pending:null})
    await s.link.handle('Read file','',handoff)
    await s.link.handle('Read file','',handoff)
    expect(s.submit).toHaveBeenCalledOnce()
    expect(s.session.disposition).toHaveBeenCalledWith(handoff.delegation_id, 'submit_requested')
    expect(s.session.disposition).toHaveBeenCalledWith(handoff.delegation_id, 'duplicate')
  })
  it('preserves roles and native UTF-8 chunk boundaries',()=>{
    const history=[{role:'user',text:'Question'},{role:'assistant',text:'Answer'}]
    const packet=voiceContextPacket({task,history,pending:null})
    expect(packet).toContain(JSON.stringify(history))
    const text='ა😀'.repeat(300)
    const chunks=codexContextChunks(text)
    expect(chunks.join('')).toBe(text)
    expect(chunks.every(chunk=>new TextEncoder().encode(chunk).length<=500)).toBe(true)
  })
})
