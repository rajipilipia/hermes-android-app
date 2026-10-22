import { expect, it } from "vitest";
import { stripBundledFontQuery } from "../src/desktop/bundled-assets";
it("uses content-hashed codicon font filenames without query suffixes rejected by the exact native asset policy", () => {
  const input =
    'src:url(./codicon-DjkITdqj.ttf?721d4c0a96379d0c13d3d5596893c348) format("truetype")';
  expect(stripBundledFontQuery(input)).toBe(
    'src:url(./codicon-DjkITdqj.ttf) format("truetype")',
  );
  expect(
    stripBundledFontQuery("url(https://example.invalid/font.ttf?v=1)"),
  ).toBe("url(https://example.invalid/font.ttf?v=1)");
});
