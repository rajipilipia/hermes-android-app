import { it, expect } from 'vitest';
import { spawnSync } from 'node:child_process';

// Executes real builder helpers/orchestration against synthetic on-disk fixtures.
// No npm/APK build, real signer, SDK, device or root dist mutation occurs here.
for (const optimized of [false, true]) {
  it(`APK publication, captured provenance, containment, collisions and signer pin fail closed${optimized ? ' under Python -O' : ''}`, () => {
    const result = spawnSync('python3', [
      ...(optimized ? ['-O'] : []), '-B', 'scripts/tests/apk_builder_test.py',
    ], { encoding: 'utf8', timeout: 120_000, maxBuffer: 4 * 1024 * 1024 });
    expect(result.error, result.error?.message).toBeUndefined();
    expect(result.status, result.stdout + result.stderr).toBe(0);
    expect(result.stderr).toMatch(/Ran \d+ tests/);
    expect(result.stderr.trim().endsWith('OK')).toBe(true);
  }, 120_000);
}