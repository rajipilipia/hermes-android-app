# Security

This is a development/debug Android client, not a release-hardened product.
Connecting it to Hermes can expose the tools and files allowed by your server's
account permissions. Use a server you control, an authentication gate and valid TLS.
See [official Hermes security guidance](https://hermes-agent.nousresearch.com/docs/user-guide/security).

## Boundaries implemented

- Native Java owns access credentials. Only refresh/provider/rotation state is
  encrypted with a nonexportable Android Keystore key in app-private no-backup storage.
  Access tokens, socket tickets and PKCE material are not persisted.
- Explicit local sign-out waits for deletion acknowledgement before UI reload.
  It does not sign out system-browser cookies or promise remote token revocation.
- The privileged page is a constrained bundled local asset document at the selected
  server origin. Exact-page native bridges have finite schemas; no arbitrary privileged
  URL, header or fetch bridge. TLS validation is not bypassed.
- The guest browser pane is a separate unprivileged WebView, with no JavaScript
  interface, no file/content access, and no navigation to the Hermes server origin.
- Background ticket/refresh/REST calls defer to foreground; stale queued work is fenced.
  Uncertain prompt delivery and ambiguous rotating refresh are never automatically replayed.
- Sign-in/turn work can use a demand-scoped nonsticky foreground service. It does not
  bypass native foreground HTTP guards, guarantee delivery, or add process-death push.
- Document selection and microphone access require scoped native checks and user consent.
  There is no broad storage or camera permission. Never weaken phone-wide security to test.

## Before a production APK release

Remove WebView/application debugging and opt-in debug cleartext/mixed-content paths;
review CSP and all native bridges; establish protected release signing and updates;
then repeat source-matched device/auth/privacy/lifecycle tests. The debug builder
is not a release builder. Background completion and sign-in recovery still have open gates.

Do not publish credentials, callback URLs, tickets, signing/ADB keys, raw logs or chat
content in an issue. Do not run a personal-account sign-in or paid model call as a test
without explicit consent. This source package does not establish a security support
service or an independent security audit. See [limits](docs/COMPATIBILITY.md).
