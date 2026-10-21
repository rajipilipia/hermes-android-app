# Hermes Android

An unofficial Android client built from the open-source **Hermes Agent / Hermes Desktop**
source by [Nous Research](https://github.com/NousResearch/hermes-agent).
The app runs the pinned Desktop renderer in Android WebView. Your own Hermes server
runs the agent, models, tools, memory and conversations; the phone is not the agent.

**Status:** development/debug source, not a production release. Basic phone operation
has been exercised, but full Desktop parity, reliable background completion alerts
and intermittent first-attempt sign-in recovery are not accepted. No claim of
compatibility with every Hermes server version or auth provider.

## Connect to your own Hermes

The current app has a server-setup screen; no source edit is needed to select a server.
Enter your own HTTPS DNS origin and confirm the host in the native dialog. The app
uses the server's native sign-in flow in your system browser, then opens the Hermes
WebSocket with a fresh single-use ticket. Return to the app to finish token exchange.

Use a valid HTTPS certificate, for example through Tailscale Serve or a reverse
proxy/tunnel. The app rejects IP literals, local-only names and URL credentials;
there is no TLS bypass. Do not use the author's personal server. `gateway.example.com`
in legacy fixtures is only a placeholder, not a service to connect to.

The current host uses contract-allowlisted native REST and Hermes's own WebSocket,
not a required custom PC adapter. Real end-to-end compatibility with a separate
stock server remains unverified. The historical optional adapter source is retained
in [pc/](pc/README.md); do not install or activate it for normal setup.

- [Official Hermes documentation](https://hermes-agent.nousresearch.com/docs/)
- [Desktop](https://hermes-agent.nousresearch.com/docs/user-guide/desktop)
- [Native sign-in](https://hermes-agent.nousresearch.com/docs/guides/desktop-native-signin)
- [Local build instructions](docs/BUILDING.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Compatibility and limits](docs/COMPATIBILITY.md)
- [Security](SECURITY.md)

## Source and licensing

Hermes is open source under the **MIT License**. Its license permits use, copying,
modification, publication and redistribution, provided its copyright and permission
notice are retained. This project preserves those notices; Hermes source reuse is
not a missing-permission blocker.

- Official source: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent).
- Official license: [MIT, Copyright (c) 2025 Nous Research](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE).
- Preserved local copies: [LICENSE.upstream](LICENSE.upstream) and [vendor/hermes/LICENSE](vendor/hermes/LICENSE).
- Android integration code: [MIT, Pilipia.us](LICENSE).
- [Third-party notices](THIRD_PARTY_NOTICES.md), including the [full dependency index](vendor/THIRD_PARTY_NOTICES.md).
  noVNC retains MPL-2.0; bundled fonts retain their OFL notices. These are not
  relicensed as MIT merely because Hermes itself is MIT.

The renderer snapshot is pinned in [source-manifest.json](vendor/hermes/source-manifest.json).
Vendor source and notice bytes are preserved, with Android compatibility implemented
outside the vendor tree. The pin identifies a local-patches Hermes revision; availability
of that revision from public upstream is not assumed. The included snapshot is what
the local build consumes.

This is an independent project, not an official Nous Research Android release or an
endorsement. Original upstream credits remain intact. This local source package
contains no private Git history, signing key, credentials, private logs or APK.
