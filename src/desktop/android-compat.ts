// Android build adapters for the pinned Desktop renderer. Source/vendor bytes stay
// unchanged. Exact-match guards require review if the upstream implementation moves.
function replaceOnce(code: string, before: string, after: string, label: string): string {
  if (code.split(before).length !== 2) throw new Error(`Android ${label} adapter: pinned Desktop source changed.`);
  return code.replace(before, after);
}

export function patchAndroidCompatibility(id: string, source: string): string | undefined {
  const file = id.replaceAll("\\", "/").split("?")[0];
  let code = source;
  if (file.endsWith("/vendor/hermes/apps/desktop/src/lib/local-preview.ts")) {
    code = replaceOnce(code, `mimeType: result.mimeType`, `mimeType: result.mimeType,
      previewKind: filePreviewKind(result.mimeType, target.previewKind)`, "MIME-aware file target");
    const start = source.indexOf("export async function openPreviewTargetInBrowser(");
    const end = source.indexOf("export function localPreviewTarget(", start);
    if (start < 0 || end < 0) throw new Error("Android preview action adapter: pinned Desktop source changed.");
    code = replaceOnce(code, source.slice(start, end), `export async function openPreviewTargetInBrowser(target: PreviewTarget): Promise<void> {
  return openAndroidPreview(target)
}

`, "mobile preview action");
    return 'import { openAndroidPreview } from "/src/desktop/open-preview";\nimport { filePreviewKind } from "/src/desktop/file-preview-policy";\n' + code;
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/lib/desktop-fs.ts")) {
    code = replaceOnce(code, `    return result
  }

  return remoteFsApi<HermesReadFileTextResult>(fsPath('read-text', path))`, `    return readablePreview(result)
  }

  return remoteFsApi<HermesReadFileTextResult>(fsPath('read-text', path)).then(readablePreview)`, "readable file preview");
    return 'import { readablePreview } from "/src/desktop/file-preview-policy";\n' + code;
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/chat/right-rail/preview-artifact.tsx")) {
    code = replaceOnce(code, `<iframe
      className="block size-full border-0 bg-white"
      sandbox="allow-scripts"
      srcDoc={composeArtifactHtml(content)}`, `<AndroidOfflineHtml
      className="block size-full border-0 bg-white"
      srcDoc={composeArtifactHtml(content)}`, "isolated HTML artifact");
    return 'import { AndroidOfflineHtml } from "/src/desktop/offline-html";\n' + code;
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/chat/right-rail/preview-file.tsx")) {
    code = replaceOnce(code, `<iframe
          aria-label={target.label}
          className="h-full w-full border-0 bg-white"
          src={pdfUrl}
          title={target.label}
        />`, `<AndroidPdfPreview dataUrl={state.dataUrl!} title={target.label} />`, "canvas PDF preview");
    // Binary bytes cannot become a useful source preview. Keep the override for large text only.
    code = replaceOnce(code, `primaryAction={{ label: t.preview.previewAnyway, onClick: () => setForcePreview(true) }}`, `primaryAction={binary ? undefined : { label: t.preview.previewAnyway, onClick: () => setForcePreview(true) }}`, "no binary-as-text override");
    return 'import { AndroidPdfPreview } from "/src/desktop/pdf-preview";\n' + code;
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/components/assistant-ui/inline-preview-directive.tsx")) {
    code = replaceOnce(code, "const MAX_HEIGHT = 1200", "const MAX_HEIGHT = 8192", "tall inline content");
    code = replaceOnce(code, `<iframe
            className="absolute inset-0 size-full border-0 bg-transparent"
            loading="lazy"
            sandbox="allow-scripts"
            srcDoc={framedDoc}
            style={{ colorScheme }}
            title={file}
          />`, `<AndroidOfflineHtml
            className="absolute inset-0 size-full border-0 bg-transparent"
            srcDoc={framedDoc}
            style={{ colorScheme }}
            title={file}
            onHeight={setMeasured}
          />`, "isolated inline HTML");
    return 'import { AndroidOfflineHtml } from "/src/desktop/offline-html";\n' + code;
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/chat/right-rail/preview-pane.tsx")) {
    code = replaceOnce(code, "isRemoteHtml ? remoteHtmlPreviewDocument(target.dataUrl!) : null",
      "isRemoteHtml ? androidRemoteHtmlPreviewDocument(target.dataUrl!) : null", "interactive isolated file HTML");
    code = replaceOnce(code, `<iframe
              className="absolute inset-0 size-full border-0 bg-white"
              referrerPolicy="no-referrer"
              sandbox=""
              srcDoc={remoteHtmlDocument || ''}
              title={target.label || copy.fallbackTitle}
            />`, `<AndroidOfflineHtml
              className="absolute inset-0 size-full border-0 bg-white"
              srcDoc={remoteHtmlDocument ?? '<p>Invalid or oversized offline HTML preview.</p>'}
              title={target.label || copy.fallbackTitle}
            />`, "isolated file HTML");
    return 'import { AndroidOfflineHtml } from "/src/desktop/offline-html";\nimport { androidRemoteHtmlPreviewDocument } from "/src/desktop/full-html-preview";\n' + code;
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/chat/composer/hooks/use-composer-metrics.ts")) {
    // The Android stylesheet gives narrow screens a separate input/control row.
    // Keep the model and reasoning entry points instead of removing them to fit
    // Desktop's one-line toolbar. Wide/Fold metrics remain byte-for-byte logic.
    code = replaceOnce(code, "compactPill: fit.compactPill || fit.tight,",
      'compactPill: document.documentElement.hasAttribute("data-android-compact") ? false : fit.compactPill || fit.tight,', "phone model label");
    code = replaceOnce(code, "foldVoice: fit.foldVoice || fit.minimal,",
      'foldVoice: document.documentElement.hasAttribute("data-android-compact") ? true : fit.foldVoice || fit.minimal,', "phone voice menu");
    return replaceOnce(code, "minimal: fit.minimal,",
      'minimal: document.documentElement.hasAttribute("data-android-compact") ? false : fit.minimal,', "phone controls");
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/chat/composer/floating-target.ts")) {
    code = replaceOnce(code, "if (!owner || selectionOutsideComposer() || inFloatingLayer(document.activeElement)) {",
      'if (document.documentElement.hasAttribute("data-android-touch") || !owner || selectionOutsideComposer() || inFloatingLayer(document.activeElement)) {', "native caret");
    return replaceOnce(code, "if (keyboardNavigation || keepsOwnFocus(target) || (pointerDownTarget && target.contains(pointerDownTarget))) {",
      'if (document.documentElement.hasAttribute("data-android-touch") || keyboardNavigation || keepsOwnFocus(target) || (pointerDownTarget && target.contains(pointerDownTarget))) {', "native focus");
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/chat/composer/reasoning-pill.tsx")) {
    // Wait for a completed touch tap. Radix normally opens on pointerdown, while
    // Android is still finishing its selection/keyboard gesture. Mouse and keys
    // continue through Radix unchanged. No custom text editing is introduced.
    return replaceOnce(code, 'data-testid="reasoning-pill"', `data-testid="reasoning-pill"
            onPointerDown={event => {
              if (event.pointerType === 'touch') event.preventDefault()
            }}
            onClick={event => {
              if (event.nativeEvent instanceof PointerEvent && event.nativeEvent.pointerType === 'touch') setMenuOpen(!open)
            }}`, "reasoning tap");
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/contrib/wiring.tsx")) {
    code = replaceOnce(code, "void openNewSessionTile('center', { listed: false })",
      "void openAndroidNewSessionTab(openNewSessionTile)", "new tab selection");
    return 'import { openAndroidNewSessionTab } from "/src/desktop/new-session-tab";\n' + code;
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/session/hooks/use-session-actions/index.ts")) {
    code = replaceOnce(code, "        listed?: boolean\n        profile?: string",
      '        listed?: boolean\n        androidSelection?: import("/src/desktop/new-session-tab").AndroidTabSelection\n        profile?: string', "new tab options");
    code = replaceOnce(code, "        // Same lease chain as createBackendSessionForSend: owner socket held",
      `        if (options?.androidSelection) Object.assign(params, options.androidSelection)

        // Same lease chain as createBackendSessionForSend: owner socket held`, "new tab request");
    return replaceOnce(code, "const runtimeInfo = applyRuntimeInfo(created.info, backgroundRuntimeOptions(capturedRoute, requestedProfile))",
      "const runtimeInfo = applyRuntimeInfo({ ...options?.androidSelection, ...created.info }, backgroundRuntimeOptions(capturedRoute, requestedProfile))", "new tab runtime");
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/session/hooks/use-prompt-actions/index.ts")) {
    // Android selected-file media seam (host.androidMedia, optional). Without it
    // every original Desktop branch below runs unchanged.
    code = replaceOnce(code, "  const uploadBytes = remote || attachmentPathNeedsUpload(path, backendCwd, terminalBackend)\n",
      `  const androidMedia = getAndroidMedia()

  if (androidMedia?.isLocalPath(path)) {
    // Capture the exact caller target, never infer a stored id from a runtime
    // or consult foreground selection after the owner lookup.
    const sessionId = opts.sessionId
    const boundStoredId = $sessionStates.get()[sessionId]?.storedSessionId
    const runtimeOwner = runtimeSessionOwner(sessionId)
    const runtimeProfile =
      typeof runtimeOwner === 'string' ? runtimeOwner : runtimeOwner?.targetProfile ?? runtimeOwner?.profile
    const runtimeConnectionId = typeof runtimeOwner === 'object' && runtimeOwner ? runtimeOwner.connectionId : null

    if (
      !sessionId ||
      !storedSessionId ||
      (boundStoredId && boundStoredId !== storedSessionId) ||
      (attachment.kind !== 'file' && attachment.kind !== 'image')
    ) {
      throw new Error('Android attachment requires an exact stored session and owner')
    }

    const owner = await resolveSessionOwner(storedSessionId)
    const profile = typeof owner === 'string' ? owner : owner?.targetProfile ?? owner?.profile
    const connectionId = typeof owner === 'object' && owner ? owner.connectionId : null

    if (
      !profile ||
      (typeof owner === 'object' && !connectionId) ||
      (runtimeProfile &&
        runtimeProfile !== profile &&
        (typeof owner !== 'object' || runtimeProfile !== owner?.profile)) ||
      (runtimeConnectionId && runtimeConnectionId !== connectionId)
    ) {
      throw new Error('Android attachment requires an exact stored session and owner')
    }

    // Deliberately outside withSessionNotFoundResume: a binary completion may
    // have committed before its reply was lost. Never auto-replay it. Never read
    // a whole-file data URL through the bridge either.
    const result = await androidMedia.uploadAttachment({
      path,
      kind: attachment.kind,
      profile,
      connectionId,
      sessionId,
      storedSessionId
    })

    if (!result.attached || (attachment.kind === 'file' && (!('ref_text' in result) || !result.ref_text))) {
      throw new Error(\`Could not attach \${label}\`)
    }

    return {
      ...attachment,
      attachedSessionId: sessionId,
      ...(attachment.kind === 'image'
        ? { path: result.path }
        : { refText: 'ref_text' in result ? result.ref_text : undefined }),
      uploadState: undefined
    }
  }

  const uploadBytes = remote || attachmentPathNeedsUpload(path, backendCwd, terminalBackend)
`, "Android attachment upload");
    // Android binary completion cannot be replayed after an uncertain eager
    // result: stage once in the explicit submit's ordered pipeline.
    code = replaceOnce(code, "        attachment.kind === 'file' &&\n        Boolean(attachment.path) &&\n        !attachment.attachedSessionId &&",
      "        attachment.kind === 'file' &&\n        Boolean(attachment.path) &&\n        !getAndroidMedia()?.isLocalPath(attachment.path ?? '') &&\n        !attachment.attachedSessionId &&", "Android deferred upload");
    code = replaceOnce(code, "      // Client-direct first: mic audio goes straight to the profile's STT\n",
      `      const androidMedia = getAndroidMedia()

      if (androidMedia) {
        if (!owner) {
          throw new Error('Android transcription requires the recording owner')
        }

        // Recorder/conversation resolved this at mic-open. Keep a value copy:
        // no provider config/key lookup, ambient re-resolution or legacy replay.
        const result = await androidMedia.transcribeBlob(audio, {
          profile: owner.profile,
          connectionId: owner.connectionId
        })

        return result.transcript
      }

      // Client-direct first: mic audio goes straight to the profile's STT
`, "Android transcription");
    return 'import { getAndroidMedia } from "/src/desktop/android-media";\nimport { runtimeSessionOwner } from "@/store/session-states";\nimport { resolveSessionOwner } from "@/app/session/hooks/use-session-actions/utils";\n' + code;
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/app/chat/hooks/use-composer-actions.ts")) {
    // Selected Android files are local bytes, never backend paths, even before a
    // remote connection descriptor has finished publishing.
    code = replaceOnce(code, "function osDropNeedsStaging(candidate: DroppedFile, staging?: OsDropStagingContext): boolean {\n  if (!staging) {",
      "function osDropNeedsStaging(candidate: DroppedFile, staging?: OsDropStagingContext): boolean {\n  if (!staging || getAndroidMedia()?.isLocalPath(candidate.path)) {", "Android drop staging");
    code = replaceOnce(code, "      const removed = scope.remove(id)\n",
      "      const removed = scope.remove(id)\n\n      if (removed?.path) {\n        getAndroidMedia()?.discardLocalPath?.(removed.path)\n      }\n", "Android handle discard");
    return 'import { getAndroidMedia } from "/src/desktop/android-media";\n' + code;
  }
  if (file.endsWith("/vendor/hermes/apps/desktop/src/lib/voice-playback.ts")) {
    // Android's reviewed media transport is finite, non-streaming relay only.
    // Returning null selects the original whole-text speakText fallback.
    code = replaceOnce(code, "export async function resolveSpeakStreamUrl(owner?: OwnerScope): Promise<null | string> {\n",
      "export async function resolveSpeakStreamUrl(owner?: OwnerScope): Promise<null | string> {\n  if (getAndroidMedia()) {\n    return null\n  }\n\n", "Android speak stream");
    return 'import { getAndroidMedia } from "/src/desktop/android-media";\n' + code;
  }
  return undefined;
}
