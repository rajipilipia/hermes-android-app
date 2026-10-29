import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const mobile = readFileSync("src/desktop/mobile.css", "utf8");
const single = readFileSync("src/desktop/single-screen.css", "utf8");

// Computed-style proof of the winning rules is in tests/browser/phone-audit.mjs (real Chromium);
// these checks keep the rule text from being weakened by accident.
describe("0.3.1 phone CSS", () => {
  it("F4: the two rules that Desktop CSS used to override carry the stronger prefix", () => {
    expect(mobile).toContain('html[data-android-touch] [data-slot="composer-status-stack"] .status-row-actions {');
    expect(mobile).toContain('html[data-android-touch] [data-slot="aui_msg-actions"] button {');
    expect(mobile).not.toContain("Loaded after the renderer styles");
  });

  it("F8: 40px invisible tap areas for titlebar icons, session actions and sidebar footer icons", () => {
    expect(mobile).toMatch(/\[data-size="icon-titlebar"\]::after \{\s*inset: -5px 0 -11px;/);
    expect(mobile).toMatch(/button\[aria-label="Session actions"\]::after \{\s*inset: -10px -8px;/);
    expect(mobile).toContain('button[aria-label="New profile"]');
  });

  it("F10: landscape menus open above the titlebar", () => {
    expect(single).toMatch(/@media \(orientation: landscape\) \{\s*html\[data-android-compact\] \[data-radix-popper-content-wrapper\] \{\s*z-index: 90 !important;/);
  });

  it("F14: the Browser tab strip + (labelled New tab) gets the same size rule as the chat strip +", () => {
    expect(single).toContain('[data-zone-tabstrip] :is(button[aria-label="New session tab"], button[aria-label="New tab"])');
  });

  it("F16: small text utilities rise to 12px only on the single-screen phone", () => {
    const block = single.slice(single.indexOf("Text is at least 12px"));
    expect(block).toContain("html[data-android-compact] :is(");
    expect(block).toContain('[class*="text-[0.6"]'); // 0.6xx rem sizes, including 0.6875rem
    expect(block).toContain('[class*="text-[11px"]');
    expect(block).toMatch(/font-size: 0\.75rem;/);
    // Gated by html[data-android-compact] (single-screen phone); the unfolded Fold keeps Desktop's sizes.
    expect(block.indexOf('[class*=')).toBeGreaterThan(block.indexOf('html[data-android-compact] :is('));
  });

  it("tool rows: the wide time stamp wraps to a second line instead of covering the tool summary", () => {
    expect(single).toMatch(/html\[data-android-compact\] \.group\\\/disclosure-row \{\s*flex-wrap: wrap;/);
    // The rule targets Desktop's own class; fail here if the pinned Desktop row renames it.
    const row = readFileSync("vendor/hermes/apps/desktop/src/components/chat/disclosure-row.tsx", "utf8");
    expect(row).toContain('"group/disclosure-row relative flex');
  });
});
