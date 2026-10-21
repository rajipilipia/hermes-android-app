// Verbose, privacy-safe diagnostics for phone debugging.
// Lines go to console.info; the native chrome client copies them to logcat
// (tag HermesDiag). Fields are structural only: short enums, numbers, error
// names and codes. Never pass tokens, URLs, paths, file names or chat text.
type Field = string | number | boolean | null | undefined;
const SECRET_LIKE = /[A-Za-z0-9_\-+/=]{24,}/g;

export function safeText(value: unknown, max = 120): string {
  const text = typeof value === "string" ? value : String(value ?? "");
  return text
    .replace(SECRET_LIKE, "[redacted]")
    .replace(/[^A-Za-z0-9 _.:;,()[\]/=-]/g, "?")
    .slice(0, max);
}

// Name, numeric code/status and a short redacted message of a rejection.
export function describeFailure(reason: unknown, withMessage = true): string {
  if (reason === null || typeof reason !== "object")
    return `type=${typeof reason}`;
  const item = reason as { name?: unknown; code?: unknown; status?: unknown; message?: unknown };
  const parts: string[] = [];
  if (typeof item.name === "string") parts.push(`name=${safeText(item.name, 40)}`);
  if (typeof item.code === "number" || typeof item.code === "string")
    parts.push(`code=${safeText(item.code, 24)}`);
  if (typeof item.status === "number") parts.push(`status=${item.status}`);
  if (withMessage && typeof (item as { detail?: unknown }).detail === "string")
    parts.push(`detail=${safeText((item as { detail: string }).detail, 80)}`);
  if (withMessage && typeof item.message === "string")
    parts.push(`message=${safeText(item.message)}`);
  return parts.join(" ") || "type=object";
}

export function diag(event: string, fields: Record<string, Field> = {}): void {
  try {
    const parts = Object.entries(fields)
      .filter(([, value]) => value !== undefined && value !== null)
      .map(([key, value]) => `${safeText(key, 24)}=${safeText(value)}`);
    console.info(`[hermes-diag] ${safeText(event, 48)} ${parts.join(" ")}`.trim());
  } catch {
    // Logging must never break the app.
  }
}
