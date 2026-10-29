import { validatedRemoteHtmlDataUrl } from "../../vendor/hermes/apps/desktop/src/lib/local-preview";

const PREFIX = "data:text/html;base64,";
const MAX_BYTES = 2 * 1024 * 1024;

/** Only for AndroidOfflineHtml: native supplies the opaque-origin sandbox and network/storage fences. */
export function androidRemoteHtmlPreviewDocument(dataUrl: string): string | null {
  if (!dataUrl.startsWith(PREFIX) || dataUrl.length - PREFIX.length > Math.ceil(MAX_BYTES / 3) * 4)
    return null;
  const validated = validatedRemoteHtmlDataUrl(dataUrl);
  if (!validated) return null;
  const bytes = Uint8Array.from(atob(validated.slice(PREFIX.length)), char => char.charCodeAt(0));
  if (bytes.length > MAX_BYTES) return null;
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return null;
  }
}
