import type { ResolvedOwner } from '@/hermes'

// Android-only optional host seam. The pinned Electron bridge and shared
// transports stay unchanged; these handles refer to host-owned selected bytes,
// never to paths on the PC. Transport validation and quotas live in the host.
export interface AndroidFileAttachmentResult {
  attached: true
  name: string
  path: string
  ref_path: string
  ref_text: string
  uploaded: boolean
}

export interface AndroidImageAttachmentResult {
  attached: true
  path: string
  count: number
  remainder: string
  text: string
  bytes: number
  name: string
  width?: number
  height?: number
  token_estimate?: number
}

export interface AndroidMediaBridge {
  isLocalPath(path: string): boolean
  discardLocalPath?(path: string): void
  uploadAttachment(input: {
    path: string
    kind: 'file' | 'image'
    profile: string
    sessionId: string
    storedSessionId: string
    connectionId?: string | null
  }): Promise<AndroidFileAttachmentResult | AndroidImageAttachmentResult>
  transcribeBlob(
    audio: Blob,
    owner: ResolvedOwner
  ): Promise<{
    ok: true
    transcript: string
    provider: string | null
  }>
}

export function getAndroidMedia(): AndroidMediaBridge | undefined {
  return (window.hermesDesktop as (typeof window.hermesDesktop & { androidMedia?: AndroidMediaBridge }) | undefined)
    ?.androidMedia
}
