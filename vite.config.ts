import { defineConfig } from "vitest/config";
import { stripBundledFontQuery } from "./src/desktop/bundled-assets.ts";
import { patchStatusbarSource } from "./src/desktop/statusbar-defaults.ts";
import { patchContextMenuTouchSource } from "./src/desktop/context-menu-touch.ts";
import { patchAndroidCompatibility } from "./src/desktop/android-compat.ts";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";
import babel from "@rolldown/plugin-babel";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
import crypto from "node:crypto";
import { createRequire } from "node:module";
const root = path.dirname(fileURLToPath(import.meta.url));
const desktop = path.join(root, "vendor/hermes/apps/desktop");
const require = createRequire(import.meta.url);
const driver = path.dirname(require.resolve("driver.js"));
const compiler = reactCompilerPreset();
compiler.rolldown.filter = {
  ...compiler.rolldown.filter,
  code: /\/>|<\/|from\s*['"][^'"]*react/,
};
export default defineConfig({
  base: "./",
  publicDir: path.join(desktop, "public"),
  plugins: [
    {
      name: "android-desktop-compatibility",
      enforce: "pre",
      transform(code, id) {
        return patchAndroidCompatibility(id, code);
      },
    },
    // Exact-source adapters must run before Babel rewrites JSX and hook bodies.
    {
      name: "android-statusbar-defaults",
      enforce: "pre",
      transform(code, id) {
        return patchStatusbarSource(id, code);
      },
    },
    react(),
    babel({ presets: [compiler] }),
    {
      name: "android-desktop-font-path",
      enforce: "pre",
      transform(code, id) {
        if (
          id
            .replaceAll("\\", "/")
            .endsWith("/vendor/hermes/apps/desktop/src/styles.css")
        )
          return code.replaceAll("../../../node_modules/", "/node_modules/");
        if (
          id
            .replaceAll("\\", "/")
            .endsWith("/vendor/hermes/apps/desktop/src/themes/presets.ts")
        )
          return code.replace(
            /fontUrl: 'https:\/\/fonts\.googleapis\.com\/[^']*'/g,
            "fontUrl: ''",
          );
      },
    },
    {
      name: "android-native-text-selection",
      enforce: "pre",
      transform(code, id) {
        return patchContextMenuTouchSource(id, code);
      },
    },
    {
      name: "android-exact-bundled-assets",
      generateBundle(_options, bundle) {
        for (const asset of Object.values(bundle)) {
          if (
            asset.type === "asset" &&
            asset.fileName.endsWith(".css") &&
            typeof asset.source === "string"
          )
            asset.source = stripBundledFontQuery(asset.source);
        }
      },
    },
    {
      name: "android-desktop-licenses",
      generateBundle() {
        const manifest = JSON.parse(fs.readFileSync(
          path.join(root, "vendor/third-party/manifest.json"), "utf8",
        )) as { packages: { notices: { path: string; sha256: string }[] }[] };
        const files = new Map<string, string | null>([
          ["vendor/hermes/LICENSE", null],
          ["vendor/THIRD_PARTY_NOTICES.md", null],
          ["vendor/third-party/manifest.json", null],
        ]);
        for (const item of manifest.packages)
          for (const notice of item.notices) {
            if (
              !notice.path.startsWith("vendor/third-party/") ||
              notice.path.split("/").some((part) => !part || part === "." || part === "..") ||
              notice.path.includes("\\") ||
              !/^[0-9a-f]{64}$/.test(notice.sha256) ||
              (files.has(notice.path) && files.get(notice.path) !== notice.sha256)
            )
              throw new Error("Invalid dependency notice inventory.");
            files.set(notice.path, notice.sha256);
          }
        const realRoot = fs.realpathSync(root);
        for (const [file, expectedHash] of [...files].sort(([a], [b]) => a.localeCompare(b))) {
          const sourcePath = fs.realpathSync(path.join(realRoot, file));
          const relative = path.relative(realRoot, sourcePath);
          if (relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative))
            throw new Error("Dependency notice escapes the source root.");
          const source = fs.readFileSync(sourcePath);
          if (expectedHash && crypto.createHash("sha256").update(source).digest("hex") !== expectedHash)
            throw new Error(`Dependency notice hash mismatch: ${file}`);
          // Preserve source-relative paths so the notice index's links still work.
          this.emitFile({ type: "asset", fileName: `licenses/${file}`, source });
        }
      },
    },
    tailwindcss(),
    {
      name: "hermes-emojibase-assets",
      generateBundle() {
        for (const name of [
          "en/data.json",
          "en/messages.json",
          "en/shortcodes/emojibase.json",
        ])
          this.emitFile({
            type: "asset",
            fileName: `emojibase/${name}`,
            source: fs.readFileSync(
              path.join(root, "node_modules/emojibase-data", name),
            ),
          });
      },
    },
  ],
  css: { postcss: { plugins: [] } },
  resolve: {
    alias: [
      {
        find: "@/debug/dev-only",
        replacement: path.join(desktop, "src/debug/dev-only.noop.ts"),
      },
      {
        find: "@hermes/plugin-sdk",
        replacement: path.join(desktop, "src/sdk/index.ts"),
      },
      {
        find: "@hermes/shared/billing",
        replacement: path.join(
          root,
          "vendor/hermes/apps/shared/src/billing-types.ts",
        ),
      },
      {
        find: "@hermes/shared/color",
        replacement: path.join(root, "vendor/hermes/apps/shared/src/color.ts"),
      },
      {
        find: "@hermes/shared",
        replacement: path.join(root, "vendor/hermes/apps/shared/src"),
      },
      { find: "@", replacement: path.join(desktop, "src") },
      {
        find: "driver.js/dist/driver.js.iife.js?raw",
        replacement: path.join(driver, "driver.js.iife.js") + "?raw",
      },
      {
        find: "driver.js/dist/driver.js.iife.js",
        replacement: path.join(driver, "driver.js.iife.js"),
      },
    ],
    dedupe: ["react", "react-dom", "react-router", "@tanstack/react-query"],
  },
  optimizeDeps: {
    exclude: [
      "radix-ui",
      "@radix-ui/react-context-menu",
      "driver.js",
      "driver.js/dist/driver.js.iife.js",
      "driver.js/dist/driver.js.iife.js?raw",
      "driver.js/dist/driver.css?raw",
    ],
  },
  test: {
    include: ["tests/**/*.test.{ts,tsx}"],
    // Bound JVM-backed regressions and notice-file I/O on the Windows host.
    maxWorkers: 4,
  },
  server: { host: "127.0.0.1", port: 18766, strictPort: true },
  build: {
    target: "es2022",
    manifest: true,
    chunkSizeWarningLimit: 25000,
    rolldownOptions: {
      output: {
        advancedChunks: {
          groups: [
            {
              name: "vendor-react",
              test: /node_modules[\\/](react|react-dom|scheduler|react-router|@tanstack[\\/]react-query)[\\/]/,
            },
            {
              name: "vendor-md",
              test: /node_modules[\\/](property-information|hast-util-[^\\/]+|mdast-util-[^\\/]+|micromark[^\\/]*|unist-util-[^\\/]+|vfile[^\\/]*|unified|stringify-entities|space-separated-tokens|comma-separated-tokens|zwitch|html-void-elements|devlop|style-to-js|style-to-object|clsx)[\\/]/,
            },
            {
              name: "vendor-util",
              test: /node_modules[\\/](lodash-es|es-toolkit|uuid|dayjs|d3-array|d3-color|d3-force|d3-interpolate|d3-time[^\\/]*|dompurify|stylis)[\\/]/,
            },
            {
              name: "mermaid",
              test: /node_modules[\\/](mermaid|cytoscape|dagre|khroma|elkjs|d3|d3-[^\\/]+|@mermaid-js)[\\/]/,
            },
            {
              name: "shiki",
              test: /node_modules[\\/](shiki|@shikijs|react-shiki|@streamdown[\\/]code|oniguruma-to-es|oniguruma-parser|regex(-[^\\/]+)?)[\\/]/,
            },
            { name: "katex", test: /node_modules[\\/]katex[\\/]/ },
          ],
        },
      },
    },
  },
});
