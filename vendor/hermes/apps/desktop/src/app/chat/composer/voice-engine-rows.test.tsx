import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { I18nProvider } from '@/i18n'
import type { VoiceChatMode, VoiceLiveStatus } from '@/lib/voice-live'

const { request, fetchStatus } = vi.hoisted(() => ({
  request: vi.fn(async () => undefined),
  fetchStatus: vi.fn<() => Promise<null | VoiceLiveStatus>>()
}))

vi.mock('@/store/gateway', () => ({
  activeGatewayConnectionId: () => 'conn-a',
  activeGatewayProfileKey: () => 'work',
  requestGatewayForProfile: request
}))
vi.mock('@/lib/voice-live', () => ({ fetchVoiceLiveStatus: fetchStatus }))
vi.mock('@/lib/haptics', () => ({ triggerHaptic: vi.fn() }))
vi.mock('@/store/notifications', () => ({ notifyError: vi.fn() }))

import { $voiceLiveStatus } from '@/store/voice-live'

import { useVoiceEngineName, VoiceEngineRows } from './voice-engine-rows'

function EngineName() {
  return <output data-testid="engine-name">{useVoiceEngineName()}</output>
}

function showMenu(mode: VoiceChatMode, disabled = false) {
  $voiceLiveStatus.set({
    mode,
    available: false,
    reason: 'Selected credentials missing',
    model: 'gpt-live-1',
    voice: 'marin'
  })

  return render(
    <I18nProvider configClient={null} initialLocale="en">
      <EngineName />
      <DropdownMenu open>
        <DropdownMenuTrigger>Voice</DropdownMenuTrigger>
        <DropdownMenuContent>
          <VoiceEngineRows disabled={disabled} />
        </DropdownMenuContent>
      </DropdownMenu>
    </I18nProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  $voiceLiveStatus.set(null)
})
afterEach(cleanup)

describe('voice engine choices', () => {
  it.each([
    ['gpt-live', 'codex-live', 'Codex Live'],
    ['codex-live', 'gpt-live', 'GPT-Live']
  ] as const)('allows switching from unavailable %s to %s and refreshes selected readiness', async (from, to, name) => {
    fetchStatus.mockResolvedValue({ mode: to, available: true, reason: null, model: 'gpt-live-1', voice: 'marin' })
    showMenu(from)
    const target = screen.getByRole('menuitemradio', { name: new RegExp(`^${name}`) })
    expect(target.getAttribute('aria-disabled')).not.toBe('true')
    expect(target.textContent).not.toContain('Selected credentials missing')
    fireEvent.click(target)
    await waitFor(() =>
      expect(request).toHaveBeenCalledWith('work', 'config.set', { key: 'voice.voice_chat_mode', value: to })
    )
    await waitFor(() => expect(target.getAttribute('aria-checked')).toBe('true'))
    expect(fetchStatus).toHaveBeenCalledOnce()
    expect(screen.getByTestId('engine-name').textContent).toBe(name)
  })

  it('shows Codex login and private-interface caveats and only the selected failure reason', () => {
    showMenu('codex-live')
    const codex = screen.getByRole('menuitemradio', { name: /^Codex Live/ })
    expect(codex.getAttribute('aria-checked')).toBe('true')
    expect(codex.textContent).toContain('existing ChatGPT login')
    expect(codex.textContent).toContain('availability and billing are not guaranteed')
    expect(codex.textContent).toContain('Selected credentials missing')
    expect(screen.getByRole('menuitemradio', { name: /^GPT-Live/ }).textContent).not.toContain(
      'Selected credentials missing'
    )
  })

  it('locks all three engines during an active conversation', () => {
    showMenu('codex-live', true)
    const items = screen.getAllByRole('menuitemradio')
    expect(items).toHaveLength(3)

    for (const item of items) {expect(item.getAttribute('aria-disabled')).toBe('true')}
  })
})
