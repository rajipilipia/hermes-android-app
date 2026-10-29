/** MIME is metadata, not executable content. Preserve the pinned target shape. */
export function filePreviewKind(mime: string | undefined, fallback: string): string {
  const type = (mime || "").split(";", 1)[0].trim().toLowerCase();
  if (type === "application/pdf") return "pdf";
  if (type.startsWith("image/")) return "image";
  return fallback;
}
export function readablePreview<T extends { text?: string; binary?: boolean; mimeType?: string }>(result: T): T {
  const text = result.text || "";
  const replacements = text.split("\uFFFD").length - 1;
  const invalid = /[\x00-\x08\x0B\x0C\x0E-\x1F]/.test(text) || (replacements >= 8 && replacements / Math.max(1, text.length) > 0.05);
  const nontext = /^(application\/(?:pdf|zip|x-7z-compressed|x-rar-compressed|vnd\.openxmlformats-officedocument)|image\/|audio\/|video\/)/i.test(result.mimeType || "");
  return result.binary || invalid || nontext ? { ...result, binary: true, text: undefined } : result;
}
