import { useStore } from '@nanostores/react'

import {
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  dropdownMenuRow
} from '@/components/ui/dropdown-menu'
import { useI18n } from '@/i18n'
import { triggerHaptic } from '@/lib/haptics'
import { notifyError } from '@/store/notifications'
import { $voiceLiveStatus, selectedVoiceChatMode, setVoiceChatMode } from '@/store/voice-live'

/**
 * Which engine the next voice conversation mounts: the chained
 * speech-to-text → Hermes → speech loop, or a live engine delegating to Hermes.
 *
 * Radio rows, not a toggle: the user is choosing between named engines and
 * the checked row tells them which one the next press starts. Rendered inside
 * whichever menu the layout has room for (the folded voice menu, or the
 * right-click menu on the start button), so the same rows appear in both.
 * Hidden while the backend has not answered or predates the mode, so we never
 * offer a switch the gateway would refuse with 4002.
 */
export function VoiceEngineRows({ disabled }: { disabled: boolean }) {
  const { t } = useI18n()
  const c = t.composer
  const status = useStore($voiceLiveStatus)

  if (status === null) {
    return null
  }

  const selected = selectedVoiceChatMode(status)

  // Readiness belongs only to the selected mode. Let users select another
  // provider, then refresh its status; never infer its credentials from this one.
  const engines = [
    { mode: 'gpt-live', label: c.voiceEngineLive, detail: c.voiceEngineLiveNeedsKey },
    { mode: 'codex-live', label: c.voiceEngineCodexLive, detail: c.voiceEngineCodexLiveDescription }
  ] as const

  return (
    <>
      <DropdownMenuLabel>{c.voiceEngine}</DropdownMenuLabel>
      <DropdownMenuRadioGroup
        onValueChange={value => {
          if (value !== 'chained' && value !== 'gpt-live' && value !== 'codex-live') {
            return
          }

          triggerHaptic('open')
          setVoiceChatMode(value).catch(error => notifyError(error, c.voiceEngineChangeFailed))
        }}
        value={selected}
      >
        <DropdownMenuRadioItem className={dropdownMenuRow} disabled={disabled} value="chained">
          {c.voiceEngineChained}
        </DropdownMenuRadioItem>
        {engines.map(engine => (
          <DropdownMenuRadioItem className={dropdownMenuRow} disabled={disabled} key={engine.mode} value={engine.mode}>
            <span className="flex min-w-0 flex-col">
              <span>{engine.label}</span>
              <span className="text-muted-foreground max-w-xs text-xs whitespace-normal">{engine.detail}</span>
              {selected === engine.mode && !status.available && status.reason ? (
                <span className="text-muted-foreground max-w-xs text-xs whitespace-normal">{status.reason}</span>
              ) : null}
            </span>
          </DropdownMenuRadioItem>
        ))}
      </DropdownMenuRadioGroup>
    </>
  )
}

/** Short engine name for tooltips, or null until the backend has answered. */
export function useVoiceEngineName(): null | string {
  const { t } = useI18n()
  const status = useStore($voiceLiveStatus)

  if (status === null) {
    return null
  }

  return {
    chained: t.composer.voiceEngineChainedShort,
    'gpt-live': t.composer.voiceEngineLiveShort,
    'codex-live': t.composer.voiceEngineCodexLiveShort
  }[selectedVoiceChatMode(status)]
}
