import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ChatController } from "./chat";
const defaultController = new ChatController();
const debugBuild =
  import.meta.env.DEV || import.meta.env.VITE_DEBUG_LOCAL === "true";
export function App({
  controller = defaultController,
}: {
  controller?: ChatController;
}) {
  const s = useSyncExternalStore(controller.subscribe, controller.snapshot);
  const [settings, setSettings] = useState(true),
    [drawer, setDrawer] = useState(false);
  const [endpoint, setEndpoint] = useState("wss://gateway.example.com/api/ws"),
    [token, setToken] = useState(""),
    [debug, setDebug] = useState(false),
    [localError, setLocalError] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [s.messages, s.busy]);
  const act = (action: () => Promise<unknown>) => {
    setLocalError("");
    void action().catch((e: unknown) =>
      setLocalError(e instanceof Error ? e.message : "Action failed."),
    );
  };
  return (
    <div className="shell">
      <aside
        className={drawer ? "sidebar visible" : "sidebar"}
        aria-label="Conversations"
      >
        <div className="brand">
          <div className="monogram" aria-hidden="true">
            H
          </div>
          <div>
            Hermes<span>YOUR AGENT, ANYWHERE</span>
          </div>
          <button
            className="mobile close"
            aria-label="Close conversations"
            onClick={() => setDrawer(false)}
          >
            ×
          </button>
        </div>
        <button
          className="new-chat"
          disabled={!s.connected || s.syncing}
          onClick={() =>
            act(async () => {
              await controller.create();
              setDrawer(false);
            })
          }
        >
          <b aria-hidden="true">＋</b>New chat<span aria-hidden="true">↗</span>
        </button>
        <div className="section-label">
          CONVERSATIONS
          <button
            aria-label="Refresh conversations"
            disabled={!s.connected}
            onClick={() => act(() => controller.refresh())}
          >
            ↻
          </button>
        </div>
        <nav aria-label="Recent sessions">
          {s.sessions.length === 0 ? (
            <p className="empty-list">
              {s.connected
                ? "Your conversations will appear here."
                : "Connect your gateway to see your conversations."}
            </p>
          ) : (
            s.sessions.map((row) => (
              <button
                key={row.id}
                aria-label={row.title || "Untitled conversation"}
                className={
                  "session " + (s.storedId === row.id ? "selected" : "")
                }
                disabled={!s.connected || s.syncing}
                onClick={() =>
                  act(async () => {
                    await controller.open(row.id);
                    setDrawer(false);
                  })
                }
              >
                <span className="session-icon" aria-hidden="true">
                  ◌
                </span>
                <span>
                  <strong>{row.title || "Untitled conversation"}</strong>
                  <small>
                    {row.preview || `${row.message_count ?? 0} messages`}
                  </small>
                </span>
              </button>
            ))
          )}
        </nav>
        <div className="sidebar-bottom">
          <div className="privacy-icon" aria-hidden="true">
            ◇
          </div>
          <div>
            Direct to your PC<small>Your existing Nous sign-in.</small>
          </div>
        </div>
      </aside>
      {drawer && (
        <button
          className="scrim"
          aria-label="Close menu"
          onClick={() => setDrawer(false)}
        />
      )}
      <main>
        <header>
          <button
            className="mobile menu"
            aria-label="Show conversations"
            onClick={() => setDrawer(true)}
          >
            ☰
          </button>
          <div className="chat-title">
            {s.runtimeId ? s.title : "Your workspace"}
            <span className="prototype">PROTOTYPE</span>
          </div>
          <button
            className="connection"
            aria-label="Connection settings"
            onClick={() => {
              setSettings(true);
              setLocalError("");
            }}
          >
            <i className={s.connected ? "dot online" : "dot"} />
            <span>
              {s.status === "connected"
                ? "Connected"
                : s.status === "reconnecting"
                  ? "Reconnecting"
                  : "Connect"}
            </span>
            <span aria-hidden="true">⚙</span>
          </button>
        </header>
        {(s.error || localError) && !settings && (
          <div className="notice" role="alert">
            {localError || s.error}
          </div>
        )}
        <div
          className="transcript"
          role="log"
          aria-label="Conversation"
          aria-live="polite"
          aria-relevant="additions text"
        >
          {s.messages.length === 0 ? (
            <section className="welcome">
              <div className="hero-symbol" aria-hidden="true">
                H<span>✦</span>
              </div>
              <div className="eyebrow">A LITTLE CURIOSITY GOES A LONG WAY</div>
              <h1>What’s on your mind?</h1>
              <p>
                Your Hermes agent. Your tools and context.
                <br />
                One conversation, wherever you are.
              </p>
              <div className="welcome-note">
                <i className={s.connected ? "dot online" : "dot"} />
                {s.syncing
                  ? "Opening conversation…"
                  : s.connected
                    ? "Open a conversation or start a new chat."
                    : "Connect to your gateway to get started."}
              </div>
            </section>
          ) : (
            s.messages.map((m, i) => (
              <article
                key={m.rowId ?? `live-${i}`}
                className={"message " + m.role}
              >
                <div className="avatar" aria-hidden="true">
                  {m.role === "assistant" ? "H" : "Y"}
                </div>
                <div>
                  <div className="message-label">
                    {m.role === "assistant" ? "Hermes" : "You"}
                  </div>
                  <div className="message-body">{m.text}</div>
                </div>
              </article>
            ))
          )}
          {s.busy && (
            <div className="thinking" role="status">
              <span />
              Hermes is working…
            </div>
          )}
          <div ref={end} />
        </div>
        <div className="compose-area">
          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              act(() => controller.send(s.draft));
            }}
          >
            <textarea
              aria-label="Message Hermes"
              placeholder={
                s.connected ? "Message Hermes…" : "Connect your gateway first…"
              }
              value={s.draft}
              onChange={(e) => controller.setDraft(e.target.value)}
              disabled={!s.connected || s.syncing || !s.runtimeId}
              rows={2}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  if (s.draft.trim() && !s.busy)
                    act(() => controller.send(s.draft));
                }
              }}
            />
            <div className="composer-bottom">
              <span>
                {s.busy
                  ? "Response in progress"
                  : s.runtimeId
                    ? "Shift + Enter for a new line"
                    : "Start or open a chat to write"}
              </span>
              <button
                className="send"
                aria-label="Send message"
                disabled={
                  !s.connected ||
                  s.syncing ||
                  s.busy ||
                  !s.runtimeId ||
                  !s.draft.trim()
                }
                type="submit"
              >
                ↑
              </button>
            </div>
          </form>
          <p className="footnote">
            Direct connection <span>·</span> Tokens stay in memory{" "}
            <span>·</span> No automatic resend
          </p>
        </div>
      </main>
      {settings && (
        <div className="modal-backdrop">
          <section
            className="settings"
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
          >
            <div className="modal-heading">
              <span className="eyebrow">YOUR PRIVATE CONNECTION</span>
              <button
                aria-label="Close settings"
                onClick={() => setSettings(false)}
              >
                ×
              </button>
            </div>
            <h2 id="settings-title">Connect your Hermes</h2>
            <p>
              Use your existing gateway. Your provider keys stay on the server.
            </p>
            <button className="primary" type="button" disabled={s.status === "connecting"} onClick={() => act(async () => { await controller.connectPc(); setToken(""); setSettings(false); })}>
              {s.status === "connecting" ? "Waiting for sign-in…" : "Sign in to this PC"}
            </button>
            <p>Opens your phone’s system browser for the same Nous sign-in as your laptop. Return here after approval. Connected to gateway.example.com. Sign-in is encrypted on this Android device.</p>
            <details><summary>Manual / debug connection</summary>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                act(async () => {
                  await controller.connect(
                    endpoint,
                    token,
                    debugBuild && debug,
                  );
                  setToken("");
                  setSettings(false);
                });
              }}
            >
              <label>
                Gateway endpoint
                <input
                  aria-label="Gateway endpoint"
                  type="url"
                  required
                  value={endpoint}
                  placeholder="wss://your-hermes.example/ws"
                  spellCheck={false}
                  autoCapitalize="none"
                  onChange={(e) => setEndpoint(e.target.value)}
                />
              </label>
              <label>
                Access token
                <input
                  aria-label="Access token"
                  type="password"
                  value={token}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(e) => setToken(e.target.value)}
                />
              </label>
              <div className="security-note">
                <span aria-hidden="true">◇</span> WSS required. Token is used
                only for this connection and is never saved.
              </div>
              {debugBuild && (
                <label className="check">
                  <input
                    type="checkbox"
                    checked={debug}
                    onChange={(e) => setDebug(e.target.checked)}
                  />
                  Debug only: allow ws://localhost, 127.0.0.1 or 10.0.2.2
                </label>
              )}
              {(localError || s.error) && (
                <div className="form-error" role="alert">
                  {localError || s.error}
                </div>
              )}
              <div className="modal-actions">
                {(s.connected || s.status === "reconnecting") && (
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => {
                      controller.disconnect();
                      setToken("");
                      setLocalError("");
                    }}
                  >
                    Disconnect
                  </button>
                )}
                <button
                  className="primary"
                  type="submit"
                  disabled={s.status === "connecting"}
                >
                  {s.status === "connecting" ? "Connecting…" : "Connect"}
                </button>
              </div>
            </form>
            </details>
            {s.status === "connecting" && <button className="secondary" type="button" onClick={() => controller.disconnect()}>Cancel sign-in</button>}
            {localError || s.error ? <p role="alert">{localError || s.error}</p> : null}
          </section>
        </div>
      )}
    </div>
  );
}
