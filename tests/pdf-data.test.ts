import { expect, it } from "vitest";
import { pdfBytes } from "../src/desktop/pdf-data";
it("decodes PDF as bytes, preserving non-UTF8 values", () => {
  const value = "%PDF-1.7\n" + String.fromCharCode(255, 0, 128);
  expect(Array.from(pdfBytes("data:application/pdf;base64," + btoa(value))).slice(-3)).toEqual([255, 0, 128]);
});
it("rejects a binary non-PDF rather than printing garbage", () => {
  expect(() => pdfBytes("data:application/pdf;base64," + btoa("PK binary"))).toThrow("not a valid PDF");
  expect(() => pdfBytes("not a data URL")).toThrow("Invalid PDF");
});
