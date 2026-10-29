/** Bounded binary decoding; never route PDF bytes through UTF-8 text preview. */
export function pdfBytes(dataUrl: string): Uint8Array {
  const comma = dataUrl.indexOf(",");
  if (comma < 0 || !/;base64$/i.test(dataUrl.slice(0, comma))) throw new Error("Invalid PDF data response.");
  const encoded = dataUrl.slice(comma + 1);
  if (encoded.length > 24 * 1024 * 1024) throw new Error("PDF exceeds the preview size limit.");
  const raw = atob(encoded);
  if (!raw.slice(0, 1024).includes("%PDF-")) throw new Error("This file is not a valid PDF.");
  return Uint8Array.from(raw, character => character.charCodeAt(0));
}
