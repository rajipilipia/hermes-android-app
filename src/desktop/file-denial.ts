// Why a file read failed (R3: inline images got HTTP 403 on the phone, 2026-10-19). Logs only
// Hermes's fixed refusal reason (a managed-root refusal is "outside_root"), the file extension and
// whether the path is inside a .hermes folder; never the path, file name or contents.
import { diag } from "./diag";

/** Hermes's own fixed refusal texts (hermes_cli/web_routers/files.py, web_server_files.py). */
const REASONS: Record<string, string> = {
  "Access to sensitive files is not allowed": "sensitive",
  "File is not readable": "not_readable",
  "Path points to a directory": "directory",
  "Only regular files can be read": "not_regular",
  "File too large": "too_large",
  "Session not found": "session_not_found",
  "Invalid path": "invalid_path",
};

type Call = { operation?: unknown; query?: unknown };

export function fileDenialFields(params: Call, response: { status: number; body: unknown }) {
  const operation = String(params.operation ?? "");
  if (!operation.startsWith("GET /api/fs/")) return undefined;
  const body = response.body as { detail?: unknown; error?: unknown } | null;
  const detail = typeof body?.detail === "string" ? body.detail : typeof body?.error === "string" ? body.error : "";
  const path = String((params.query as { path?: unknown } | undefined)?.path ?? "").replace(/\\/g, "/");
  const ext = /\.([A-Za-z0-9]{1,5})$/.exec(path)?.[1]?.toLowerCase();
  return {
    op: operation.slice("GET /api/fs/".length),
    status: response.status,
    reason: REASONS[detail] ?? (/outside the managed read boundary/i.test(detail) ? "outside_root" : detail ? "other" : "none"),
    ext: ext ?? "none",
    in_hermes_dir: /(^|\/)\.hermes(\/|$)/.test(path),
  };
}

export function noteFileDenial(params: Call, response: { status: number; body: unknown }): void {
  const fields = fileDenialFields(params, response);
  if (fields) diag("file_denied", fields);
}
