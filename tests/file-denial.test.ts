import { expect, it, vi } from "vitest";
import { fileDenialFields, noteFileDenial } from "../src/desktop/file-denial";

it("classifies a refused image read by Hermes's fixed reason without logging the path", () => {
  const params = { operation: "GET /api/fs/read-data-url", query: { path: "C:\\Users\\someone\\.hermes\\cache\\images\\private-name.PNG" } };
  expect(fileDenialFields(params, { status: 403, body: { detail: "Access to sensitive files is not allowed" } })).toEqual({
    op: "read-data-url", status: 403, reason: "sensitive", ext: "png", in_hermes_dir: true,
  });
  const lines: string[] = [];
  vi.spyOn(console, "info").mockImplementation((line: string) => void lines.push(line));
  noteFileDenial(params, { status: 403, body: { detail: "Access to sensitive files is not allowed" } });
  expect(lines).toEqual(["[hermes-diag] file_denied op=read-data-url status=403 reason=sensitive ext=png in_hermes_dir=true"]);
  expect(lines[0]).not.toMatch(/someone|private|Users|cache/);
  vi.restoreAllMocks();
});

it("unknown server texts are never logged; non-file operations are ignored", () => {
  expect(fileDenialFields({ operation: "GET /api/fs/read-text", query: { path: "/srv/x" } }, { status: 404, body: { detail: "File /srv/x missing" } }))
    .toEqual({ op: "read-text", status: 404, reason: "other", ext: "none", in_hermes_dir: false });
  expect(fileDenialFields({ operation: "GET /api/sessions" }, { status: 403, body: {} })).toBeUndefined();
});
