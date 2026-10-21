# Compatibility and known limits

## Implemented does not mean accepted everywhere

The app uses a bundled pinned Hermes Desktop renderer and native Android adapters.
Its current connection path uses Hermes's own REST contract and WebSocket, without
requiring the historical PC adapter. The server must provide compatible native sign-in,
tickets, profile/session APIs and the relevant feature contracts. Missing server
capabilities must not be presented as working features.

Server selection accepts an HTTPS DNS host and optional port, not an IP, path, query,
fragment or URL credentials. Cloud setup accepts a user-provided supported agent URL;
this is not a claim of Cloud provisioning or fresh live Cloud acceptance. No built-in
SSH tunnel, arbitrary HTTP mode, provider API-key vault or on-phone agent is promised.

## Evidence boundary

The private development build has physical-phone observations of authenticated
launch, saved profile/chat restoration after restart, real reply/history recovery
and an active foreground work service. Those observations do not validate your server,
auth provider, network, handset, this sanitized source build, or the entire Desktop UI.

Still open or unaccepted:

- reliable completion notification while the app remains backgrounded;
- intermittent first-attempt interactive sign-in recovery;
- a fresh complete end-to-end run against a separate stock Hermes server;
- every Cloud/auth-provider combination, cross-profile notification tap, cellular
  reconnect, reboot, fold/IME, attachment/voice/approval and full-feature edge case;
- full Desktop parity, release hardening and public APK/update acceptance.

Do not automatically resend after uncertain delivery. Keep a working client available
for unsupported or untested workflows. Source-only local tests use synthetic peers
and do not call a paid model or establish device acceptance. The local export manifest
is an inventory, not a production-ready certificate.
