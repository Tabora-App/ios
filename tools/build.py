#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Builds Tabora for iPhone.

On iPhone a browser may use only the system engine (WebKit), so the base is Firefox for iOS:
it runs entirely on WebKit. Its sources are not stored in the repository: this tool downloads
the pinned commit into .build/firefox-ios and applies our changes from the overlay/ directory.

Commands:
  fetch            download the Firefox for iOS sources (the commit from tabora.json, section ios)
  prepare          build tools: settings generator (pinned script), user scripts
  import           apply the changes from the overlay/ directory to the sources
  export           turn edits made directly in the sources into patches in overlay/
  reset            return the sources to clean Firefox for iOS
  build [--device] build the app: for the simulator (default) or for a phone
  build --device --sign   the same for a phone, with development signing (for your own phone)
  run              install into the simulator and launch
  shot <file.png>  screenshot of the simulator
  status           version, commit, what is applied

Requires: Xcode (the version from the README of the sources), Node.js. About 12 GB of disk space.
Python 3.9+ standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "tabora.json").read_text())
IOS = CONFIG["ios"]
WORK = ROOT / ".build"
TREE = WORK / "firefox-ios"
APP = TREE / "firefox-ios"
SRC = ROOT / "overlay"
DERIVED = WORK / "DerivedData"
PACKAGES = WORK / "SourcePackages"
ADDED = TREE / ".tabora-added"  # files that Firefox for iOS does not have: reset removes them
SIMULATOR = os.environ.get("TABORA_IOS_SIMULATOR", "iPhone 17")


def log(text: str) -> None:
    # the output may be cut off (… | head): that must not stop the work halfway, for example
    # import between applying the patches and replacing the product name in UI strings
    try:
        print(f"\033[1;32m›\033[0m {text}", flush=True)
    except BrokenPipeError:
        sys.stdout = open(os.devnull, "w")


def die(text: str) -> None:
    print(f"\033[1;31m✗\033[0m {text}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], cwd: Path | None = None, check: bool = True, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, **kw)


def git(*args: str, capture: bool = False) -> str:
    r = run(["git", *args], cwd=TREE, capture_output=capture, text=True)
    return r.stdout if capture else ""


def need_tree() -> None:
    if not (TREE / ".git").is_dir():
        die("no sources: run tools/build.py fetch")
    head = git("rev-parse", "HEAD", capture=True).strip()
    if head != IOS["commit"]:
        die(f".build/firefox-ios is at commit {head[:12]}, tabora.json has {IOS['commit'][:12]}: run tools/build.py fetch")


# ---- sources -----------------------------------------------------------------------------------

def cmd_fetch(args: argparse.Namespace) -> None:
    """One commit without history: its hash is the integrity check of the content."""
    WORK.mkdir(parents=True, exist_ok=True)
    if not (TREE / ".git").is_dir():
        TREE.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "-q"], cwd=TREE)
        run(["git", "remote", "add", "origin", IOS["repository"]], cwd=TREE)
    head = run(["git", "rev-parse", "-q", "--verify", "HEAD"], cwd=TREE, check=False, capture_output=True, text=True).stdout.strip()
    if head == IOS["commit"]:
        log(f"sources are in place: {IOS['tag']} ({head[:12]})")
        return
    log(f"downloading Firefox for iOS {IOS['tag']} ({IOS['commit'][:12]})")
    reset_tree()
    git("fetch", "-q", "--depth", "1", "origin", IOS["commit"])
    git("checkout", "-q", "FETCH_HEAD")
    if git("rev-parse", "HEAD", capture=True).strip() != IOS["commit"]:
        die("fetched a different commit than expected")
    log("done: next run prepare and import")


def reset_tree() -> None:
    if not (TREE / ".git").is_dir() or not run(["git", "rev-parse", "-q", "--verify", "HEAD"], cwd=TREE, check=False, capture_output=True).stdout:
        return
    git("checkout", "-q", "--", ".")
    if ADDED.exists():
        for rel in ADDED.read_text().splitlines():
            target = TREE / rel
            if rel and target.is_file():
                target.unlink()
        ADDED.unlink()


def automatic(rel: str) -> bool:
    """Edits that import makes by itself (project file, product name in UI strings): not exported to patches."""
    return rel.endswith((".strings", ".stringsdict", "project.pbxproj", "/Info.plist")) or rel == "firefox-ios/Shared/Strings.swift"


def unexported() -> list[str]:
    """Source files whose edits differ from the patch in overlay/: reset would lose them."""
    if not (TREE / ".git").is_dir() or not ADDED.exists():
        return []
    lost = []
    for rel in git("diff", "--name-only", capture=True).splitlines():
        if not rel or automatic(rel) or (SRC / rel).is_file():
            continue
        patch = SRC / (rel + ".patch")
        if not patch.is_file() or patch.read_text() != git("diff", "--", rel, capture=True):
            lost.append(rel)
    return lost


def guard_unexported(args: argparse.Namespace) -> None:
    lost = unexported()
    if lost and not getattr(args, "force", False):
        die("the sources have edits not exported to overlay/ (run export first, or use --force to discard them):\n  " + "\n  ".join(lost[:12]))


def cmd_reset(args: argparse.Namespace) -> None:
    need_tree()
    guard_unexported(args)
    reset_tree()
    log("sources returned to clean Firefox for iOS")


# ---- our changes -------------------------------------------------------------------------------

def source_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*") if p.is_file() and p.name != ".DS_Store") if SRC.is_dir() else []


def cmd_import(args: argparse.Namespace) -> None:
    """The overlay/ directory mirrors the paths of the sources: "<file>.patch" is an edit of an existing
    file, everything else is whole files (new or replacing)."""
    need_tree()
    guard_unexported(args)
    reset_tree()
    patches, copied, added = 0, 0, []
    for path in source_files():
        rel = path.relative_to(SRC)
        if path.suffix == ".patch":
            r = run(["git", "apply", "--whitespace=nowarn", str(path)], cwd=TREE, check=False, capture_output=True, text=True)
            if r.returncode:
                die(f"patch does not apply: overlay/{rel}\n{r.stderr.strip()[:600]}")
            patches += 1
        else:
            target = TREE / rel
            if not target.exists():
                added.append(str(rel))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied += 1
    ADDED.write_text("\n".join(added) + ("\n" if added else ""))
    log(f"overlay/: patches applied {patches}, files copied {copied}")
    project_edits()
    rebrand_strings()


# Extensions that are not embedded in the app: widgets and stickers are drawn with Firefox logos,
# notifications and password autofill in other apps work through the Mozilla account.
DROPPED_EXTENSIONS = ["WidgetKitExtension", "NotificationService", "CredentialProvider", "Sticker"]


def project_edits() -> None:
    """Edits of the Xcode project file. It is huge and changes in every Firefox for iOS release, so
    instead of a patch there are pattern replacements, each with a check that the pattern was found."""
    pbx = APP / "Client.xcodeproj" / "project.pbxproj"
    text = pbx.read_text()

    def sub(pattern: str, to: str, what: str) -> None:
        nonlocal text
        text, count = re.subn(pattern, to, text)
        if not count:
            die(f"project file: no match for the edit '{what}': the format has changed")

    sub(r'TARGETED_DEVICE_FAMILY = "(?:1,2|iPhone, iPad)";', "TARGETED_DEVICE_FAMILY = 1;", "iPhone only")
    # the alternate app icons are Firefox logos: they are not put into the bundle
    sub(r'ASSETCATALOG_COMPILER_ALTERNATE_APPICON_NAMES = "[^"]*";', 'ASSETCATALOG_COMPILER_ALTERNATE_APPICON_NAMES = "";', "alternate app icons")
    sub(r"ASSETCATALOG_COMPILER_INCLUDE_ALL_APPICON_ASSETS = YES;", "ASSETCATALOG_COMPILER_INCLUDE_ALL_APPICON_ASSETS = NO;", "alternate app icons")
    for name in DROPPED_EXTENSIONS:
        sub(rf"\n\t+[0-9A-F]{{24}} /\* {name}\.appex in Embed App Extensions \*/,", "", f"extension {name}")
        # and they are not built either: otherwise signing for a phone would require a separate
        # identifier and profile in the developer account for each of them
        deps = re.findall(rf"\n\t\t([0-9A-F]{{24}}) /\* PBXTargetDependency \*/ = \{{\n\t+isa = PBXTargetDependency;\n\t+target = [0-9A-F]{{24}} /\* {name} \*/;", text)
        if not deps:
            die(f"project file: dependency on the extension {name} not found: the format has changed")
        for dep in deps:
            text = re.sub(rf"\n\t+{dep} /\* PBXTargetDependency \*/,", "", text)
    pbx.write_text(text)
    log(f"project file: iPhone only, no alternate app icons, without the extensions {', '.join(DROPPED_EXTENSIONS)}")


def cmd_export(args: argparse.Namespace) -> None:
    """Edits of text files in the sources → patches. Files that are kept whole in overlay/
    are updated by copying."""
    need_tree()
    whole = {str(p.relative_to(SRC)) for p in source_files() if p.suffix != ".patch"}
    if whole and not ADDED.exists():
        die("overlay/ has files not yet applied to the sources: run tools/build.py import first")
    changed = [line for line in git("diff", "--name-only", capture=True).splitlines() if line and not automatic(line)]
    patches, copies = 0, 0
    for rel in changed:
        if rel in whole:
            shutil.copy2(TREE / rel, SRC / rel)
            copies += 1
            continue
        numstat = git("diff", "--numstat", "--", rel, capture=True)
        if numstat.startswith("-\t-"):
            die(f"binary file changed: {rel}: put the whole file into overlay/")
        diff = git("diff", "--", rel, capture=True)
        out = SRC / (rel + ".patch")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(diff)
        patches += 1
    stale = [p for p in source_files() if p.suffix == ".patch" and str(p.relative_to(SRC))[:-6] not in changed]
    for p in stale:
        p.unlink()
    # git diff does not show new files (those that Firefox for iOS does not have): they are known from
    # the list that import keeps. Without import the files from overlay/ are not in the sources yet,
    # so they are left alone.
    added = set(ADDED.read_text().splitlines()) if ADDED.exists() else set()
    for rel in sorted(whole & added):
        if (TREE / rel).is_file() and (TREE / rel).read_bytes() != (SRC / rel).read_bytes():
            shutil.copy2(TREE / rel, SRC / rel)
            copies += 1
    log(f"overlay/: patches {patches}, files updated {copies}, stale patches removed {len(stale)}")


# The product name in UI strings. In code the app name is AppName (a patch in overlay/), but the
# translations have hundreds of strings where translators wrote "Firefox" literally, in about a
# hundred languages. They cannot be maintained as patches, so the replacement is done in place on
# every import, and only in the string value, not in the key.
STRINGS_LINE = re.compile(r'^(\s*(?:"(?:[^"\\]|\\.)*"|[\w.-]+)\s*=\s*")((?:[^"\\]|\\.)*)(".*)$')
SWIFT_VALUE = re.compile(r'(\bvalue:\s*")((?:[^"\\]|\\.)*)(")')
STRING_ROOTS = ["firefox-ios/Shared", "firefox-ios/Client", "firefox-ios/Extensions", "firefox-ios/WidgetKit", "BrowserKit/Sources"]


def rebrand_strings() -> None:
    files = values = 0
    for root in STRING_ROOTS:
        for path in sorted((TREE / root).rglob("*.strings")) + sorted((TREE / root).rglob("*.stringsdict")):
            raw = path.read_bytes()
            # some old translation files are stored in UTF-16: the file encoding is preserved
            encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
            text = raw.decode(encoding)
            if "Firefox" not in text:
                continue
            out, changed = [], 0
            for line in text.split("\n"):
                if path.suffix == ".strings":
                    m = STRINGS_LINE.match(line)
                    if m and "Firefox" in m.group(2):
                        line = m.group(1) + m.group(2).replace("Firefox", "Tabora") + m.group(3)
                        changed += 1
                elif "<string>" in line and "Firefox" in line:
                    line = line.replace("Firefox", "Tabora")
                    changed += 1
                out.append(line)
            if changed:
                path.write_bytes("\n".join(out).encode(encoding))
                files += 1
                values += changed
    # Info.plist of the app and of the extensions: the texts of the system permission prompts and the
    # name of the "Open in …" action (image names such as logoFirefoxLarge are not UI strings and
    # are left alone)
    plists = [TREE / "firefox-ios" / "Client" / "Info.plist", *sorted((TREE / "firefox-ios" / "Extensions").glob("*/Info.plist"))]
    for path in plists:
        text = path.read_text(encoding="utf-8")
        out = [line.replace("Firefox", "Tabora") if "<string>" in line and " " in line.strip() and "Firefox" in line else line for line in text.split("\n")]
        if out != text.split("\n"):
            path.write_text("\n".join(out), encoding="utf-8")
            files += 1
    # the English strings are written in code as default values
    code = TREE / "firefox-ios" / "Shared" / "Strings.swift"
    text, count = SWIFT_VALUE.subn(lambda m: m.group(1) + m.group(2).replace("Firefox", "Tabora") + m.group(3) if "Firefox" in m.group(2) else m.group(0), code.read_text(encoding="utf-8"))
    code.write_text(text, encoding="utf-8")
    log(f"product name in UI strings: translation files {files}, strings {values}; Strings.swift updated")


# ---- build tools -------------------------------------------------------------------------------

def cmd_prepare(args: argparse.Namespace) -> None:
    """The same as bootstrap.sh of the sources, but without "download the latest from the network and
    run it": the settings generator script is taken from a pinned commit and verified by SHA-256, the
    dependencies of the user scripts are installed strictly from package-lock.json and without
    install scripts."""
    need_tree()
    nimbus = IOS["nimbus"]
    target = APP / "bin" / "nimbus-fml.sh"
    url = f"https://raw.githubusercontent.com/mozilla/application-services/{nimbus['commit']}/components/nimbus/ios/scripts/nimbus-fml.sh"
    data = urllib.request.urlopen(url, timeout=60).read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != nimbus["sha256"]:
        die(f"nimbus-fml.sh: SHA-256 {digest}, expected {nimbus['sha256']}")
    target.write_bytes(data)
    target.chmod(0o755)
    log("settings generator: the script is in place and verified")
    run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=TREE, stdout=subprocess.DEVNULL)
    run(["npm", "run", "build"], cwd=TREE, stdout=subprocess.DEVNULL)
    log("user scripts built")


# ---- build and run -----------------------------------------------------------------------------

def products(device: bool) -> Path:
    return DERIVED / "Build" / "Products" / ("Firefox-iphoneos" if device else "Debug-iphonesimulator") / "Client.app"


def cmd_build(args: argparse.Namespace) -> None:
    need_tree()
    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / ("build-device.log" if args.device else "build-sim.log")
    cmd = [
        "xcodebuild", "-project", str(APP / "Client.xcodeproj"), "-scheme", "Fennec",
        "-derivedDataPath", str(DERIVED),
        # packages are kept apart from the object files (4.6 GB: no download again after cleaning the
        # build) and only the versions recorded in Package.resolved are used
        "-clonedSourcePackagesDirPath", str(PACKAGES), "-onlyUsePackageVersionsFromResolvedFile",
        # Xcode asks to approve package macros and plugins in a dialog; a command-line build has no
        # dialog, and the packages are pinned in Package.resolved
        "-skipMacroValidation", "-skipPackagePluginValidation",
    ]
    if args.device and args.sign:
        # Development signing for your own phone: Xcode itself creates the app and extension
        # identifiers, the app group and the profiles in the developer account
        # (-allowProvisioningUpdates; requires being signed in to the account in Xcode settings).
        # The targets in the project file carry the Mozilla team and its profiles, some of them with
        # the [sdk=iphoneos*] condition: it overrides a plain setting, and a condition cannot be
        # written on the command line, so the signing settings are passed as a file.
        team = IOS.get("teamId") or CONFIG["macTeamId"]
        settings = {"CODE_SIGN_STYLE": "Automatic", "DEVELOPMENT_TEAM": team, "CODE_SIGN_IDENTITY": "Apple Development", "PROVISIONING_PROFILE_SPECIFIER": ""}
        sign = WORK / "sign.xcconfig"
        sign.write_text("".join(f"{key} = {value}\n{key}[sdk=iphoneos*] = {value}\n" for key, value in settings.items()))
        cmd += ["-configuration", "Firefox", "-destination", "generic/platform=iOS", "-allowProvisioningUpdates", "-xcconfig", str(sign)]
    elif args.device:
        cmd += ["-configuration", "Firefox", "-destination", "generic/platform=iOS", "CODE_SIGNING_ALLOWED=NO"]
    else:
        # the Debug configuration of the project is the "Fennec" development build (Client/Configuration/Fennec.xcconfig).
        # Signing is not turned off: for the simulator Xcode signs by itself, without profiles, and
        # only then the app gets its entitlements: the shared app group storage and the keychain.
        # Without them it starts but does not save tabs and works without some of the settings.
        cmd += ["-configuration", "Debug", "-destination", f"platform=iOS Simulator,name={SIMULATOR}"]
    cmd += ["build"]
    log(f"building ({'phone' if args.device else 'simulator'}): log {out.relative_to(ROOT)}")
    with out.open("w") as f:
        r = run(cmd, cwd=APP, check=False, stdout=f, stderr=subprocess.STDOUT)
    if r.returncode:
        errors = [line for line in out.read_text(errors="replace").splitlines() if " error: " in line or line.startswith("error:")]
        print("\n".join(dict.fromkeys(errors[:25])))
        die(f"build failed, exit code {r.returncode}")
    log(f"built: {products(args.device).relative_to(ROOT)}")


def simctl(*args: str, check: bool = True, capture: bool = False) -> str:
    r = run(["xcrun", "simctl", *args], check=check, capture_output=capture, text=True)
    return r.stdout if capture else ""


def bundle_id(app: Path) -> str:
    return run(["/usr/libexec/PlistBuddy", "-c", "Print :CFBundleIdentifier", str(app / "Info.plist")], capture_output=True, text=True).stdout.strip()


def cmd_run(args: argparse.Namespace) -> None:
    app = products(False)
    if not app.is_dir():
        die("the app is not built: run tools/build.py build")
    simctl("boot", SIMULATOR, check=False, capture=True)
    simctl("bootstatus", SIMULATOR, capture=True)
    simctl("install", SIMULATOR, str(app))
    simctl("launch", SIMULATOR, bundle_id(app), *args.args, capture=True)
    log(f"launched in the simulator '{SIMULATOR}': {bundle_id(app)}")


def cmd_shot(args: argparse.Namespace) -> None:
    simctl("io", SIMULATOR, "screenshot", args.file, capture=True)
    log(f"screenshot: {args.file}")


def cmd_status(args: argparse.Namespace) -> None:
    print(f"Firefox for iOS: {IOS['tag']} ({IOS['commit'][:12]})")
    print(f"sources: {'present' if (TREE / '.git').is_dir() else 'missing'} ({TREE.relative_to(ROOT)})")
    files = source_files()
    print(f"overlay/: patches {sum(p.suffix == '.patch' for p in files)}, files {sum(p.suffix != '.patch' for p in files)}")
    for device in (False, True):
        app = products(device)
        if app.is_dir():
            print(f"built ({'phone' if device else 'simulator'}): {bundle_id(app)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Builds Tabora for iPhone")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in [("fetch", cmd_fetch), ("prepare", cmd_prepare), ("export", cmd_export), ("status", cmd_status)]:
        sub.add_parser(name).set_defaults(fn=fn)
    for name, fn in [("import", cmd_import), ("reset", cmd_reset)]:
        p = sub.add_parser(name)
        p.add_argument("--force", action="store_true", help="discard source edits not exported to overlay/")
        p.set_defaults(fn=fn)
    p = sub.add_parser("build")
    p.add_argument("--device", action="store_true", help="release configuration for a phone (unsigned)")
    p.add_argument("--sign", action="store_true", help="with --device: sign for your own phone (development signing)")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("run")
    p.add_argument("args", nargs="*")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("shot")
    p.add_argument("file")
    p.set_defaults(fn=cmd_shot)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
