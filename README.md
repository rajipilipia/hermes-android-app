# Hermes Android

Use Hermes from your Android phone. Your own computer or server does the work.

**Unofficial. Experimental. Not ready for critical work.**

[Download the app](https://github.com/rajipilipia/hermes-android-app/releases) · [Known limits](docs/COMPATIBILITY.md) · [Report a bug](https://github.com/rajipilipia/hermes-android-app/issues)

## What this is

This is a phone app for [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research.
It uses the Hermes Desktop interface, with changes for a small touch screen.

The phone is a **client**: it shows the interface and connects to Hermes elsewhere.
It does **not** run the agent, its tools or its models on the phone.
It does not include a Hermes server or an artificial intelligence (AI) account.

This is an independent project. It is not an official Nous Research app.
It does not yet have every Desktop feature working reliably.

## What you need

- **Your own compatible Hermes server.** This is the computer or hosted service that runs Hermes and its tools.
- **A secure server address.** It must start with `https://` and use a web name, not a numeric network address.
  HTTPS is the secure form of a web connection. The server needs a valid security certificate.
- **A trusted Android phone.** The app allows Android 8 or later. The alpha.2 phone checks used Android 17; other versions are not fully checked.
- **An up-to-date Android System WebView.** WebView is the Android component that shows the app's web-based interface.
- Your server's sign-in details and a network connection to that server.

There is no general promise that every Hermes version or sign-in provider will work.
A complete test against a separate, unchanged Hermes server is still open.
You do not need to install the old optional PC adapter for the current connection path.

If you do not already have a server, start with the [official Hermes guide](https://hermes-agent.nousresearch.com/docs/).

## Screenshots

These app views use an Android emulator, a simulated phone, with the same alpha.2 app file.
All conversations, profiles and server names are made-up demo data.
No real account, server or AI reply was used. These images show the interface, not a complete feature test.
The phone's system bar is removed; the app's own controls remain visible.

| New session | Demo conversation |
| --- | --- |
| <img src="docs/screenshots/new-session.png" alt="Full compact app view with an empty new session, demo profile and bottom controls" width="320"> | <img src="docs/screenshots/demo-chat.png" alt="Full compact app view showing a made-up short conversation about a weekend walk" width="320"> |

| Profile picker | Appearance controls |
| --- | --- |
| <img src="docs/screenshots/profiles.png" alt="Full compact app view with the picker open for the fake demo, writing and research profiles" width="320"> | <img src="docs/screenshots/appearance.png" alt="Full compact app view of appearance and text-size controls in the demo emulator" width="320"> |

| Command menu | Server setup |
| --- | --- |
| <img src="docs/screenshots/commands.png" alt="Full compact app view with the command menu open over the demo interface" width="320"> | <img src="docs/screenshots/setup.png" alt="Full compact app view of the initial server setup screen, without any account connected" width="320"> |

## Words explained

> **APK:** the file that installs an Android app.
>
> **SHA-256:** a file's digital fingerprint. A matching fingerprint checks that you downloaded the expected file.
>
> **Sideload:** install an app from a file instead of an app store.
>
> **WebView:** Android's built-in way to show web content inside an app.
>
> **Debug build:** a development version with inspection tools still enabled. It is not a hardened public product.
>
> **Hermes server:** the computer or hosted service that runs Hermes and does the agent's work.

## Install in 6 steps

This is a **sideload**: you install an APK file, not a Play Store app.
**Check the SHA-256 before you install. Step 4 explains how.**

1. **Download.** Open [Releases](https://github.com/rajipilipia/hermes-android-app/releases).
   Choose `v0.1.0-alpha.2`. Download its APK and `SHA256SUMS`, the file with the expected digital fingerprint.
2. **Allow this source.** When Android asks, allow your browser or file app to install this file.
   Do not turn off phone-wide security checks.
3. **Install.** Open the checked APK and follow Android's prompts.
   If updating this app, keep the existing app installed. Do not clear its data.
4. **Check the SHA-256.** Compare the APK's fingerprint with `SHA256SUMS`.
   They must match exactly. Do not install or open a file with a different fingerprint.
   A Windows check is shown below. You can do this check before step 3.
5. **Open Hermes Android.** Keep the app in the foreground during setup.
6. **Sign in to your own server.** Follow the steps below. The app is not a public shared Hermes service.

On Windows, open Command Prompt in the download folder and run:

```text
certutil -hashfile hermes-android-v0.1.0-alpha.2-debug.apk SHA256
```

Compare the result with `SHA256SUMS`. This command was checked during release preparation.
You can remove the install permission from your browser or file app after installation.

**Update blocked? Stop.** A different signing key cannot update the existing app.
Do not uninstall or erase data to get past that check.
The public alpha.2 APK uses the same signing identity as alpha.1.

## First sign-in

1. On the connection screen, enter your server's secure address.
   Do not add a page path, a user name or a password. Use only the base address,
   such as `https://example.invalid`, even if the example placeholder shows `/hermes`.
2. Choose the sign-in option. Confirm the server in the Android dialog if asked.
3. Complete your server's sign-in in the phone's normal browser.
4. Return to the Hermes app. It needs to be in front to finish sign-in.
5. Let the connection check finish. If **Apply** appears, tap it after the check passes.

The exact browser sign-in page depends on your server.
Use your server login, not an AI provider key.
Never share your login, sign-in links or security codes.

## What works today

The app includes Hermes Desktop's chat, saved-conversation and profile views.
Their available features depend on your server.
Development phone tests have included real replies, but not every way of using the app has passed.

The exact alpha.2 APK passed these checks:

- Update in place, with the same app identity and permission grants.
- Existing sign-in remained available after the update.
- The phone status bar kept the profile picker available with the profile rail on or off.
  The profile rail is the side strip used to choose a profile.
- The **Smart** approval label stayed visible with the drawer open or closed.
- Long profile labels kept room for their first eight characters and an ellipsis (`…`).
- All four rail-on/off and drawer-open/closed states passed on the physical phone.

Source checks also passed 274 application tests, Android code checks and the web build.
This does not mean that every Desktop feature or every Android phone has passed.

## What does not work reliably yet

- Alerts when an agent finishes while the app is in the background.
- Recovery when the first sign-in attempt fails.
- Every feature from Hermes Desktop.
- A complete test with a separate, unchanged Hermes server.
- Checks for wide or unfolded screens with this APK.

The alpha.2 status-bar test did not send a chat message or repeat all sign-in, reply,
history and return-from-background tests.
Keep another working Hermes client available for important tasks.

See [all compatibility limits](docs/COMPATIBILITY.md).

## Safety

This is a **debug build**, a development version with inspection tools enabled.
Application debugging and WebView debugging are still on.
It is not a hardened production app or a Play Store release.

- Use only a trusted phone and a server you trust.
- Never share your server login, security codes or sign-in links.
- Do not bypass a security certificate warning.
- Do not turn off phone-wide security to make the app connect.
- Give microphone access only if you want to use a feature that needs it.
- Do not treat a background service as a promise that alerts will arrive.

Read the [security notes](SECURITY.md) before connecting a sensitive server.

## Troubleshooting

### The browser says sign-in finished, but the app is waiting

Return to the Hermes app. Sign-in network work waits for the app to be in front.
First-attempt sign-in recovery still has known limits. Do not keep submitting credentials blindly.

### Android refuses an update

Stop and check that the APK is from this project's release page.
Updates need the same signing identity. Do not uninstall the existing app or clear its data to force an update.

### No completion alert arrives in the background

Reliable background completion alerts are still an open item.
Return to the app and check the conversation. Do not send the same request again because an alert is missing.

## Build from source

This section is for developers. Normal phone users can use the APK in Releases.
The checked build environment is Windows with Git Bash, a window for typed commands.
It uses Node 26 and `npm` to install and check the web code, Python 3.11 or later to run build scripts,
Java Development Kit 21 to build the Android code, and the Android software development kit to package the app.

With the tools and test inputs from [the build guide](docs/BUILDING.md):

```text
npm ci --ignore-scripts
npm run typecheck
npm run build
npm test -- --maxWorkers=2 --testTimeout=30000
npm run test:native
```

Build before testing: one test reads the generated web page.
The build guide also explains the checked APK build and signing steps.
A source download does not include a signing key.
Other operating systems are not claimed as checked APK build environments.

## Credits and license

Built from [Hermes Agent / Hermes Desktop](https://github.com/NousResearch/hermes-agent) by Nous Research.
Hermes uses the MIT License, Copyright (c) 2025 Nous Research.
The MIT License allows reuse with its copyright and license notices kept.

- [Hermes license](LICENSE.upstream) and [preserved upstream copy](vendor/hermes/LICENSE).
- [Android integration license: MIT, Pilipia.us](LICENSE).
- [Third-party notices](THIRD_PARTY_NOTICES.md) and [full dependency notices](vendor/THIRD_PARTY_NOTICES.md).

Other components keep their own licenses. noVNC uses MPL-2.0; bundled fonts have their own OFL licenses.
Those licenses are not replaced by MIT.

The bundled Desktop version is recorded in [the source record](vendor/hermes/source-manifest.json).
The included source is what the build uses. This is not an official Nous Research release or endorsement.

## How to report a bug

Open an [issue](https://github.com/rajipilipia/hermes-android-app/issues) with:

- App release label, such as `alpha.2`.
- Phone model and Android version.
- Short steps to show the problem.
- What you expected and what happened.

**Do not include secrets, chat text, session titles, your server address, personal profile names or account details.**
Only attach a screenshot after checking every visible part for private data.
Do not attach a raw log or a sign-in link.
