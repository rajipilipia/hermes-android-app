/** A UI scheduling hint only; native checks foreground again before any HTTP dispatch. */
const states = new WeakMap<Window, { paused: boolean }>();

export function isBackgrounded(): boolean {
  if (typeof window === "undefined") return false;
  let state = states.get(window);
  if (!state) {
    state = { paused: false };
    states.set(window, state);
    const current = state;
    window.addEventListener?.("hermes:native-lifecycle", event => {
      const next = (event as CustomEvent<{ state?: string }>).detail?.state;
      if (next === "pause" || next === "resume") current.paused = next === "pause";
    });
  }
  return state.paused || window.document?.visibilityState === "hidden";
}

export function foregroundRequired(): Error {
  return Object.assign(new Error("Return to Hermes to reconnect."), { name: "PcForegroundRequired" });
}
