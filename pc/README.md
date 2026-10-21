# Historical optional PC adapter

This folder preserves earlier compatibility-adapter source and its synthetic tests.
It added `desktop.bootstrap` / `desktop.call` around a pinned Hermes backend. It is
Windows-first, tightly version-bound and not a supported general installer.

**The current Android host does not require or use this adapter.** It uses Hermes's
native REST contract and WebSocket path. Do not activate the adapter, restart a live
Hermes service, or change account/profile/tunnel settings merely to try the app.

The source is retained, not converted into fake successful stubs. Optional proofs
reference a separate compatible Hermes checkout and use example paths; they have not
been validated as a portable public support matrix. Host-owned permissions, profile
homes and native credentials must remain bounded. Private deployment/startup records
are not part of this source export.

See [Android setup](../README.md), [architecture](../docs/ARCHITECTURE.md),
[compatibility](../docs/COMPATIBILITY.md), and [trusted-home design](TRUSTED-PROFILE-HOMES.md).
