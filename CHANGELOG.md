# Changelog

Debug builds only. All dates are 2026.

## 0.3.1 - 29 Oct (source only, no new APK on Releases)

- Hermes Desktop source updated to v0.22.5 (`925ede7`). It stays byte-exact in `vendor/`; phone changes are build-time adapters.
- Codex Live voice calls: a foreground service keeps the call alive, and you can end it from the notification. A bug that ended a call when the first message renamed a "+" tab is fixed (checked with a test and a phone probe). Needs a server with Codex Live support.
- Tabs: "+" tabs show again in the compact layout.
- Composer: native phone keyboard behavior. Spell check is on, Enter makes a new line, Send sends.
- Layout: tool rows wrap, the right panel opens, and more buttons have screen-reader names.
- Voice tasks: fixed the "cannot dial registry connections" error on the second task and later.
- New: an app file log and verbose diagnostics. The API contract has 79 operations (was 69).
- Checked: the tests pass on a laptop build (79 test files; one timing test can fail under load and passes when run alone), and a private build of this source runs on one real phone. Not checked: a call with the screen off for over 2 minutes, and the first voice task in a brand-new "+" tab.

## 0.1.0-alpha.2 - 22 Oct

- Status-bar profile picker. The clipped "Smart" label is fixed. New README with screenshots.

## 0.1.0-alpha.1 - 21 Oct

- First public source and debug APK.
