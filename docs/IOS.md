# Tabora for iPhone

iPhone only (not iPad). On iPhone a browser may use only one engine: the system WebKit, the same one
Safari uses. So the Gecko engine that Tabora uses on desktop and Android is not used here. The base is
Firefox for iOS (mozilla-mobile/firefox-ios, MPL 2.0 license): it runs entirely on WebKit and provides
a ready-made browser shell. Mozilla services are removed from it, and the name, mark, colors and
shortcuts are our own.

## How to build

Requires Xcode 27.1 or newer (tested with 27.2), Node.js and about 12 GB of disk space.

```sh
python3 tools/build.py fetch      # Firefox for iOS sources: the commit from tabora.json, section ios
python3 tools/build.py prepare    # settings generator (pinned script), user scripts
python3 tools/build.py import     # apply our changes from the overlay/ directory
python3 tools/build.py build      # the app for the iPhone Simulator
python3 tools/build.py run        # install into the simulator and launch
python3 tools/build.py shot a.png # screenshot of the simulator
```

Signing is not turned off for the simulator (Xcode signs by itself, no profiles are needed): only a
signed app has the shared app group storage. Without it the app starts but does not save tabs.

The Firefox for iOS sources are not stored in the repository: they are downloaded into
`.build/firefox-ios` (one pinned commit without history). All our changes live in the `overlay/`
directory at the repository root and mirror the paths of the source tree:
`<file>.patch` is a change to an existing file, everything else is whole files. Edits made directly in
the source tree are turned into patches by `tools/build.py export`; `reset` restores clean Firefox for
iOS.

`import` does two things by itself, without patches, because the files are huge and change in every
release:

- the Xcode project file: iPhone only, no alternate Firefox app icons, no extra extensions;
- the product name in UI strings: "Firefox" → "Tabora" in the translations for all languages (only in
  the string value, not in the key) and in the English strings in `Strings.swift`.

The build on GitHub is the **Build** workflow (`.github/workflows/build.yml`, started manually): it
builds the app for the simulator from scratch.

Images (app icon, launch screen, the mark that replaces the Firefox logos and fox, the wordmark in the
header) are drawn by `tools/assets.py`; the generated files are stored in `overlay/`.

## What is changed

- The name Tabora, bundle id `app.tabora.browser`, the same version as the other Tabora builds.
  Websites are told the version of Firefox for iOS the app is based on (the `FxiOS/160.0` token), not
  the Tabora release number.
- The app icon, the launch screen and all images with the Firefox logo and fox are replaced with the
  Tabora mark.
- Colors: the Tabora palette, the same as in the Android app (the Nova design).
- Shortcuts on the home page: Tabora mail (`app.tabora.app`) comes first.
- Languages: all that Firefox for iOS has, including Russian, English, Ukrainian and Spanish.
- Ad blocking is on from the first launch (in Firefox it is turned on by hand), and tracking
  protection is strict: the trackers themselves are blocked, not only their cookies. The ad blocking
  list is loaded at launch and is updated together with the remote settings. Ad blocking can be
  turned off in "Settings → Browsing".

Help links: every "Get help" and "Learn more" link that led to Mozilla's help pages leads to the
Tabora support site, https://support.tabora.app (requests with a Tabora account or without one);
links to Mozilla's terms and privacy notice lead to the Tabora website
(`BrowserKit/Sources/Shared/SupportUtils.swift.patch`).

Turned off for everyone and cannot be turned on in the settings:

- telemetry (Glean), crash reports (Sentry), Mozilla experiments and surveys;
- the Firefox onboarding: Mozilla terms of use, consent to sending data, account sign-in;
- the Mozilla account and sync: sign-in in the settings and in the menu, tabs from other devices,
  "Send to Device", notifications through the Mozilla server;
- sponsored shortcuts, the stories feed, Firefox Suggest suggestions, the Google shortcut with a
  partner code;
- Firefox partner codes in search queries;
- page summaries on Mozilla servers, Relay, VPN, "Report Broken Site";
- install data for ad attribution (SKAdNetwork);
- the settings sections for sending data, feedback, Mozilla help, Mozilla notifications and rating
  Firefox in the App Store; the "set as default browser" banner in the menu (until Apple grants the
  entitlement).

One connection remains: the Mozilla settings server (Remote Settings). The app gets the list of search
engines, the ad blocker lists and the page translation models from it. No personal data is sent there.

In a development build a given screen can be opened at launch. This is how the checks take screenshots
without taps: `SIMCTL_CHILD_TABORA_OPEN="tabora://deep-link?url=/settings/general" xcrun simctl launch
"iPhone 17" app.tabora.browser`. Besides a link, the words `menu` (main menu) and `tabs` (tab tray)
are accepted; the app language is set with the launch arguments `-AppleLanguages "(en)"`.

## What is not there yet

- Tabora account sections in the app: mail opens from a shortcut, in the web version.
- The wallet: Apple accepts wallets only from developers registered as organizations.
- Widgets, stickers and password autofill in other apps: in Firefox they are drawn with its logos or
  work through the Mozilla account, so for now they are not embedded in the app.
- "Learn more" links to our own help: they lead to Mozilla help.
- Hiding ad slots on the page: requests to ad servers and trackers are cancelled (from the first
  request and on a cold start), but the ad placeholders on the test page stay visible. On desktop and
  Android our own blocker hides them; here the Firefox for iOS lists are used.
- The "default browser" choice: it needs a separate Apple entitlement
  (`com.apple.developer.web-browser`), which is requested from Apple under the developer account.

## Building for your own iPhone

```sh
python3 tools/build.py build --device --sign   # release configuration, development signing
```

Required: being signed in to the developer account in Xcode (Settings → Accounts) and an Apple
Development certificate in the keychain. On the first such build Xcode itself creates in the developer
account (the team is `macTeamId` from `tabora.json`) the identifiers `app.tabora.browser`,
`app.tabora.browser.ShareTo`, `app.tabora.browser.ActionExtension`, the app group
`group.app.tabora.browser` and development profiles for them (done on November 12, 2026). An app with
development signing can be installed only on phones from the account's device list and works for a
year, while the profile is valid.

The build and signing are verified; installing on a phone has not been tried yet. The app is installed
with `xcrun devicectl device install app --device <phone name> <Client.app>`; Developer Mode must be
turned on on the phone (Settings → Privacy & Security).

## What is needed for the App Store

Publishing requires actions in the Apple developer account, which the account owner performs:

1. Distribution profiles for the three identifiers above (the Apple Distribution certificate is
   already on the maintainer's computer).
2. An app record in App Store Connect, a description, screenshots, a privacy policy URL.
3. A request to Apple for the entitlement to be the default browser.
