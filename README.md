# Tabora for iPhone

The iPhone app of [Tabora](https://github.com/Tabora-App/browser), an ad-free browser with mail
and a wallet built in.

On iOS every browser runs on WebKit, so this app is not built from the desktop engine. It is
Mozilla's [Firefox for iOS](https://github.com/mozilla-mobile/firefox-ios) at a pinned release with
our changes laid over it.

**Status: in development.** The app builds and runs in the iOS Simulator and in CI. It is not in
the App Store yet, and the Tabora account, sync and mail have not been brought to it.

## What is changed

- Tabora name, icons and colors instead of Firefox branding.
- Mozilla telemetry, crash reports, experiments, sponsored tiles, stories, search partner codes and
  ad attribution are switched off.
- Mozilla account sign-in and sync entry points are removed.
- Ad blocking and strict tracking protection are on by default.

The full list, with the reasons, is in [docs/IOS.md](docs/IOS.md).

## Build

```sh
python3 tools/build.py fetch      # Firefox for iOS sources at the pinned commit, into .build/
python3 tools/build.py prepare    # build tools and user scripts
python3 tools/build.py import     # lay our changes from overlay/ over the sources
python3 tools/build.py build      # build for the Simulator
python3 tools/build.py run        # install into the Simulator and start
```

Requires Xcode (the version named in the Firefox for iOS README), Node.js and about 12 GB of disk
space. The tool itself needs only the Python standard library. `build --device` builds the release
configuration for a phone; `status` shows what is applied; edits made directly in the sources
become patches with `export`.

## Layout

| Path | Contents |
|---|---|
| `tabora.json` | The pinned Firefox for iOS release and commit, the bundle identifier |
| `overlay/` | Our changes, mirroring the Firefox for iOS tree: `*.patch` for edited files, new files as is |
| `tools/build.py` | The build tool |
| `tools/assets.py` | Generates the icons and images of the app from the Tabora mark |
| `docs/IOS.md` | What is changed and why, signing, what is left to do |

Firefox for iOS sources are not stored here: they are downloaded into `.build/`.

## License

[Mozilla Public License 2.0](LICENSE), the same as Firefox for iOS.

Tabora is an independent project. It is not affiliated with or endorsed by Mozilla. Firefox is a
trademark of the Mozilla Foundation.
