# Architecture

Hermes runs on your server; Android is the client. The app imports the actual pinned
Desktop React renderer, not a replacement skin or an on-phone agent. No Electron or
Node process is shipped as the Android runtime.

1. Native setup validates a chosen HTTPS origin and confirms a new host. Before
   selection, the page uses an app-local setup origin that cannot be a server.
2. Standard system-browser native OAuth uses PKCE and a bounded loopback listener.
   Token exchange waits for the Activity to return to foreground.
3. Native Java stores refresh-only login state encrypted with Android Keystore and
   mints short-lived single-use WebSocket tickets. JavaScript never gets access tokens.
4. The local asset document shares the selected server's origin. The host issues only
   native contract-allowlisted REST operations; chat and streams use Hermes WebSockets.
5. Upstream stores/reconciles chat history and runtime/session identity. Android's local
   per-origin profile memory never changes the server primary or creates an account.
6. Android-only touch/layout, bootstrap retry, guest browser, notification and active-work
   adapters live outside `vendor/`. A checked Vite transform handles native text selection;
   original vendor files and licenses remain unchanged.

Pre-render recovery retries reads, never prompts. Native foreground epochs fence stale
queued work. Active-work demand requests a bounded nonsticky foreground service, not
permanent background delivery. See [security](../SECURITY.md) and
[limits](COMPATIBILITY.md). Historical prototype files and optional `pc/` compatibility
source remain for context; they are not the current required connection path.
