interface StartupHost {
  bootstrap(): Promise<unknown>;
  dispose(): void;
}
interface StartupOptions {
  root: HTMLElement;
  createHost(): StartupHost;
  mount(): Promise<void>;
  requireSignIn(): void;
  failureText: string;
}

/** Retry only pre-render startup reads, never a renderer operation or a prompt. */
export function startDesktopWithRecovery(options: StartupOptions): () => void {
  let host: StartupHost | undefined;
  let inFlight = false;
  let failed = false;
  let rendererStarted = false;
  let stopped = false;
  let foreground = document.visibilityState !== "hidden";
  let paused = !foreground;
  let returned = false;
  let automaticRetryUsed = false;
  let attempted = false;
  const disposeHost = () => { host?.dispose(); host = undefined; };
  const stop = () => {
    stopped = true;
    window.removeEventListener("pagehide", stop);
    window.removeEventListener("hermes:native-lifecycle", onLifecycle);
    document.removeEventListener("visibilitychange", onVisibility);
    disposeHost();
  };
  const retryAfterReturn = () => {
    if (!failed || !returned || !foreground || automaticRetryUsed || stopped || inFlight || rendererStarted) return;
    automaticRetryUsed = true;
    void attempt();
  };
  const setForeground = (value: boolean) => {
    foreground = value;
    if (!value) { paused = true; return; }
    if (!attempted) { paused = false; void attempt(); return; }
    if (!paused) return;
    paused = false;
    returned = true;
    retryAfterReturn();
  };
  const onLifecycle = (event: Event) => {
    const state = (event as CustomEvent<{ state?: string }>).detail?.state;
    if (state === "pause" || state === "resume") setForeground(state === "resume");
  };
  const onVisibility = () => setForeground(document.visibilityState !== "hidden");
  const attempt = async () => {
    if (stopped || inFlight || rendererStarted || !foreground) return;
    inFlight = true;
    attempted = true;
    failed = false;
    returned = false;
    options.root.textContent = "Connecting to Hermes…";
    try {
      host = options.createHost();
      await host.bootstrap();
      if (stopped) return;
      rendererStarted = true;
      options.root.replaceChildren();
      await options.mount();
    } catch (error: unknown) {
      disposeHost();
      if (stopped) return;
      if (!rendererStarted && error instanceof Error && error.name === "PcSignInRequired") {
        stop();
        options.requireSignIn();
        return;
      }
      if (rendererStarted) {
        options.root.textContent = "The Hermes Desktop renderer could not start. Reopen the app to retry.";
        return;
      }
      failed = true;
      options.root.textContent = options.failureText;
      const retry = document.createElement("button");
      retry.type = "button";
      retry.textContent = "Retry";
      retry.style.cssText = "display:block;min-height:48px;padding:12px 20px;margin-top:12px;cursor:pointer";
      retry.addEventListener("click", () => { if (failed) void attempt(); });
      options.root.append(retry);
    } finally {
      inFlight = false;
      // A foreground event may have arrived before the pending bootstrap rejected.
      retryAfterReturn();
    }
  };
  window.addEventListener("pagehide", stop);
  window.addEventListener("hermes:native-lifecycle", onLifecycle);
  document.addEventListener("visibilitychange", onVisibility);
  void attempt();
  return stop;
}
