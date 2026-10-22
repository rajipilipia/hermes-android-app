# Third-party notices and provenance

Vendored unchanged from NousResearch/hermes-agent, local commit
`93ac19694ea0c4cc1e1661ff37c2a171d96a1bc0`:

- `src/upstream/json-rpc-gateway.ts`
- `src/upstream/json-rpc-channel.ts`
- `src/upstream/gateway-events.ts`
- `src/upstream/gateway-contract.generated.ts`
- `src/upstream/gateway-contract.openrpc.json`

Source: https://github.com/NousResearch/hermes-agent (MIT).
Full upstream MIT notice is in `LICENSE.upstream` and bundled in the APK.
The generated contract is consumed, not independently reconstructed.
The browser WebSocket transport is reused without Electron or Node builtins.

React and React DOM: MIT, Meta Platforms, Inc. and affiliates.
Their distributed production bundles retain their license headers.
Dependency versions/integrity are pinned in package-lock.json; full dependency
licenses remain available in the respective node_modules packages.

New prototype application code: MIT; see LICENSE. This is an independent,
unofficial prototype, not an official Hermes mobile release.
