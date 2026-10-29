// Android build adapter: the Hermes Bots plugin re-runs its "hide Bot Mode sessions" sweep on EVERY
// gateway 'open' event. Android drops the app's network a few seconds after it leaves the screen,
// so every return fired about 11 slow /api/profiles/sessions?limit=200 calls at once and the app
// took 3 to 12 s to settle. Here the sweep still runs at plugin load and on the first 'open'; after
// that a later 'open' starts it at most once per 10 minutes. The sweep only hides old plumbing
// sessions, so a late run is harmless. Vendor bytes stay unchanged; the exact-match guard fails the
// build if the Desktop source moves.
export const HIDE_SWEEP_MIN_INTERVAL_MS = 10 * 60 * 1000;

function replaceOnce(code: string, before: string, after: string, label: string): string {
  if (code.split(before).length !== 2) throw new Error(`Android ${label} adapter: pinned Desktop source changed.`);
  return code.replace(before, after);
}

export function patchHideSweepThrottle(id: string, source: string): string | undefined {
  const file = id.replaceAll("\\", "/").split("?")[0];
  if (!file.endsWith("/vendor/hermes/apps/desktop/src/plugins/hermes-bots/session-sweep.ts")) return undefined;
  return replaceOnce(source, `  const stopGatewayListener = host.state.gateway.listen(state => {
    if (state === 'open') {
      schedule()
    }
  })`, `  // Android: the first 'open' runs; later ones at most every 10 minutes (see hide-sweep-throttle.ts).
  let lastOpenSweepAt = 0

  const stopGatewayListener = host.state.gateway.listen(state => {
    if (state === 'open' && (lastOpenSweepAt === 0 || Date.now() - lastOpenSweepAt >= ${HIDE_SWEEP_MIN_INTERVAL_MS})) {
      lastOpenSweepAt = Date.now()
      schedule()
    }
  })`, "hide sweep throttle");
}
