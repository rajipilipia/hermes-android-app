import { it, expect } from "vitest";
import { readFileSync } from "node:fs";
it("accounts for system bars and display cutouts in the phone WebView container", () => {
  const source = readFileSync(
    "android/src/us/pilipia/hermes/prototype/MainActivity.java",
    "utf8",
  );
  expect(source).toContain("WindowInsets.Type.systemBars()");
  expect(source).toContain("WindowInsets.Type.displayCutout()");
  expect(source).toContain("container.setPadding(");
});

it("system bars follow light/dark mode and match the page chrome, so a light page has no dark band", () => {
  const source = readFileSync("android/src/us/pilipia/hermes/prototype/MainActivity.java", "utf8");
  expect(source).toContain("private void applySystemBars()");
  expect(source).toContain("UI_MODE_NIGHT_MASK");
  expect(source).toContain("Color.rgb(246,248,250)");
  expect(source).toContain("Color.rgb(1,4,9)");
  expect(source).toContain("setSystemBarsAppearance(night?0:light,light)");
  // Applied once the container is attached, and again when the system theme changes (uiMode is in configChanges).
  expect(source).toMatch(/setContentView\(container\);\s+applySystemBars\(\);/);
  expect(source).toMatch(/super\.onConfigurationChanged\(configuration\);\s+applySystemBars\(\);/);
  expect(source).not.toContain("Color.rgb(19,22,23)");
  expect(readFileSync("android/AndroidManifest.xml", "utf8")).toMatch(/configChanges="[^"]*uiMode/);
});

it("the WebView page follows system light/dark (day/night theme)", () => {
  const manifest = readFileSync("android/AndroidManifest.xml", "utf8");
  expect(manifest).toContain('android:theme="@style/Hermes.App"');
  // WebView takes prefers-color-scheme from the theme's light/dark flag; a dark-only theme kept the page dark.
  expect(readFileSync("android/res/values/themes.xml", "utf8")).toContain("Theme.Material.Light.NoActionBar");
  expect(readFileSync("android/res/values-night/themes.xml", "utf8")).toContain("Theme.Material.NoActionBar");
});
