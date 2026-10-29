import { describe, expect, it } from 'vitest'

import { TRANSLATIONS } from '@/i18n/catalog'

import { ENUM_OPTIONS, FIELD_DESCRIPTIONS } from './constants'

describe('voice engine settings', () => {
  it('offers Codex Live alongside both existing engines with explicit login and private-interface caveats', () => {
    expect(ENUM_OPTIONS['voice.voice_chat_mode']).toEqual(['chained', 'gpt-live', 'codex-live'])
    expect(FIELD_DESCRIPTIONS['voice.voiceChatMode']).toContain('existing ChatGPT login')
    expect(FIELD_DESCRIPTIONS['voice.voiceChatMode']).toContain('availability and billing are not guaranteed')
  })

  it.each(Object.entries(TRANSLATIONS))('describes Codex Live in the %s settings and composer', (_locale, t) => {
    expect(t.settings.fieldDescriptions['voice.voiceChatMode']).toContain('codex-live')
    expect(t.settings.fieldDescriptions['voice.voiceChatMode']).toContain('ChatGPT')
    expect(t.composer.voiceEngineCodexLive).toContain('Codex Live')
    expect(t.composer.voiceEngineCodexLiveDescription).toContain('ChatGPT')
    expect(t.composer.voiceEngineCodexLiveShort).toBe('Codex Live')
  })
})
