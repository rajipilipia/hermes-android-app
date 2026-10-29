// @vitest-environment jsdom
import { expect, it } from "vitest";
import { androidRemoteHtmlPreviewDocument } from "../src/desktop/full-html-preview";
import { remoteHtmlPreviewDocument } from "../vendor/hermes/apps/desktop/src/lib/local-preview";

const dataUrl = (html: string) => "data:text/html;base64," + Buffer.from(html, "utf8").toString("base64");

it("keeps UTF-8 renderer initialization scripts only on the native offline path", () => {
  const html = '<div id="view"></div><script>document.getElementById("view").textContent="გამარჯობა"</script>';
  expect(remoteHtmlPreviewDocument(dataUrl(html))).not.toContain("<script>");
  expect(androidRemoteHtmlPreviewDocument(dataUrl(html))).toBe(html);
});

it("rejects non-HTML, malformed and noncanonical base64", () => {
  for (const value of ["https://example.org/", "data:text/plain;base64,YQ==", "data:text/html;base64,!", "data:text/html;base64,YR=="])
    expect(androidRemoteHtmlPreviewDocument(value)).toBeNull();
});

it("bounds the document by the native 2 MiB byte limit", () => {
  const exact = "x".repeat(2 * 1024 * 1024);
  expect(androidRemoteHtmlPreviewDocument(dataUrl(exact))).toBe(exact);
  expect(androidRemoteHtmlPreviewDocument(dataUrl(exact + "x"))).toBeNull();
});

it("rejects malformed UTF-8 instead of inventing replacement characters", () => {
  expect(androidRemoteHtmlPreviewDocument("data:text/html;base64,/w==")).toBeNull();
});
