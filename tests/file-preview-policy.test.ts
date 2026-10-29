import { expect, it } from "vitest";
import { filePreviewKind, readablePreview } from "../src/desktop/file-preview-policy";
it("promotes PDF/image MIME metadata even when a filename has no useful extension", () => {
  expect(filePreviewKind("application/pdf", "text")).toBe("pdf");
  expect(filePreviewKind("IMAGE/PNG; charset=binary", "text")).toBe("image");
  expect(filePreviewKind(undefined, "text")).toBe("text");
});
it("does not display binary, control-filled or clearly lossy decoding as text", () => {
  for (const result of [{ binary: true, text: "PK bytes" }, { text: "a\0b" }, { text: "\uFFFD".repeat(30) }, { mimeType: "application/pdf", text: "%PDF binary" }]) {
    expect(readablePreview(result)).toMatchObject({ binary: true, text: undefined });
  }
});
it("preserves readable Georgian, Markdown and genuine isolated replacement symbols", () => {
  const result = { text: "# გამარჯობა\nOrdinary text \uFFFD", binary: false };
  expect(readablePreview(result)).toBe(result);
});
