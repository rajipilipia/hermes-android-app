# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Phone port

### Adapter
A change the port makes to the vendored Desktop without editing its files: a build-time rewrite of one Desktop source file, or a runtime shim. A build-time adapter matches exact Desktop text and fails the build when Desktop has moved, so a Desktop update shows what to re-check.

### Compact phone mode
The layout the port switches on while the screen counts as one phone screen: a narrow window, or a device whose short side is narrow. A rotated phone, or a window shortened by the keyboard, stays compact. A wide screen, such as the unfolded Fold, keeps Desktop's own wide layout.

## Chat tabs and calls

### Session tile
A chat that Desktop shows as its own tab in the main tab strip, next to the first chat. Each tile owns its conversation and its composer. A tile made with the tab-strip "+" stays out of the sessions list until its first message is saved. Until then its tab takes its name from the composer, and after that from the saved session.

### Voice call
A hands-free conversation with the Codex Live voice model, started from one composer. A spoken request that needs Hermes is handed to Hermes as a delegation (a task), and the call says the result aloud in its own words.

A call lives as long as its composer stays on screen. It ends when the user ends it, on a spoken stop, when voice is switched off, when the connection fails, when its chat or owner changes, or when its composer is removed. Rebuilding the composer for any reason therefore ends the call.
