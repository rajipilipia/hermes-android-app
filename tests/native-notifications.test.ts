import { expect, it } from "vitest";
import { spawnSync } from "node:child_process";
it("executes the real native notification controller under JVM framework fixtures and compiles against Android 36", () => {
  const result = spawnSync(process.env.PYTHON ?? "python", ["android/tests/test-native-notifications.py"], { encoding: "utf8", timeout: 120_000 });
  expect(result.status, result.stdout + result.stderr).toBe(0);
  expect(result.stdout).toContain("PASS NativeNotifications JVM fixture assertions:");
  expect(result.stdout).toContain("PASS NativeNotifications source compiles against android-36 (no APK).");
}, 120_000);
