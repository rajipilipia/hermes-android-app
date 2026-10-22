import { expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import config from "../vite.config";

it("bundles the upstream license, notice index and every indexed dependency notice with unchanged bytes", () => {
  const plugin = (config.plugins as { name?: string; generateBundle?: unknown }[])
    .find((item) => item.name === "android-desktop-licenses");
  expect(plugin, "the production renderer must include license assets").toBeDefined();
  if (typeof plugin?.generateBundle !== "function") throw new Error("Missing notice emitter");
  const assets = new Map<string, string | Uint8Array>();
  plugin.generateBundle.call({
    emitFile(asset: { type: string; fileName: string; source: string | Uint8Array }) {
      expect(asset.type).toBe("asset");
      expect(assets.has(asset.fileName)).toBe(false);
      assets.set(asset.fileName, asset.source);
    },
  });
  const manifest = JSON.parse(fs.readFileSync("vendor/third-party/manifest.json", "utf8"));
  const notices = new Map<string, string>();
  for (const entry of manifest.packages)
    for (const notice of entry.notices) notices.set(notice.path, notice.sha256);
  for (const file of ["vendor/hermes/LICENSE", "vendor/THIRD_PARTY_NOTICES.md", "vendor/third-party/manifest.json"])
    expect(Buffer.from(assets.get(`licenses/${file}`)!)).toEqual(fs.readFileSync(path.resolve(file)));
  for (const [file, hash] of notices) {
    const bytes = assets.get(`licenses/${file}`);
    expect(bytes, file).toBeDefined();
    expect(crypto.createHash("sha256").update(bytes!).digest("hex")).toBe(hash);
  }
  for (const name of ["@novnc/novnc", "@fontsource/courier-prime", "@fontsource/ibm-plex-mono"])
    expect(manifest.packages.find((item: { name: string }) => item.name === name)?.notices.length).toBeGreaterThan(0);
});
