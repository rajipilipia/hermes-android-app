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

// DEV PHONE full logging (the author, 2026-10-28: "save all on the phone no matter what"): message
// content is logged, but values of secret-looking fields, Bearer values and JWTs are masked.
const SECRET_FIELD = /("?[a-z_]*(?:token|secret|password|passwd|api_?key|authorization|cookie|ticket|refresh)[a-z_]*"?\s*[:=]\s*"?)[^\s",;&}]{4,}/gi;
const BEARER = /(bearer\s+)[A-Za-z0-9._~+/=-]{8,}/gi;
const JWT = /eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g;
export const FULL_MAX = 3500;

export function redactSecrets(text: string): string {
  return text.replace(BEARER, "$1[redacted]").replace(SECRET_FIELD, "$1[redacted]").replace(JWT, "[redacted-jwt]");
}

/** One full-content debug line (truncated to fit one logcat entry). */
export function full(event: string, content: unknown): void {
  try {
    const text = typeof content === "string" ? content : JSON.stringify(content) ?? String(content);
    const clean = redactSecrets(text);
    console.info(`[hermes-full] ${event} len=${text.length} ${clean.slice(0, FULL_MAX)}${clean.length > FULL_MAX ? " [cut]" : ""}`);
  } catch {
    // Logging must never break the app.
  }
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
