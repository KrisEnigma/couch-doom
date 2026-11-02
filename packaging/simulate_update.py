"""Try an update the way a player gets it, without touching your own CouchDoom folder or settings.

  quick   Run this checkout from source as if you had just updated from --from (default 1.2.0).
          Opens straight on the What's new screen. No build needed.

  full    Download a real older release (--old, default 1.2.2), give it a fake "newer release" built from this
          checkout, and start the old app. Choose Update and restart, and the new build opens on What's new.
          Windows and Linux only; builds with PyInstaller first (a few minutes).

Both copy your settings (launcher choice, favorites) into the sandbox so the list looks like yours.
Run from the repo root:  uv run python packaging/simulate_update.py quick
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from couch_doom import __version__  # noqa: E402
from couch_doom.update import asset_for_platform  # noqa: E402
from tests.make_update_test_manifest import write_manifest  # noqa: E402

RELEASES = "https://github.com/KrisEnigma/couch-doom/releases/download"


def _settings(seen: str | None) -> dict:
    """Your own settings file, minus the version it last saw (that's what the simulation sets)."""
    data: dict = {}
    try:
        data = json.loads((ROOT / "state" / "last_played.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"language": "en", "language_source": "menu"}  # still a returning player, just without your list
    data.pop("seen_version", None)
    if seen:
        data["seen_version"] = seen
    return data


def _write_state(state_dir: Path, seen: str | None) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "last_played.json").write_text(json.dumps(_settings(seen), indent=2), encoding="utf-8")


def quick(sandbox: Path, previous: str) -> None:
    data = sandbox / "quick"
    shutil.rmtree(data, ignore_errors=True)
    _write_state(data / "state", previous)
    env = {**os.environ, "COUCHDOOM_DATA_DIR": str(data), "COUCHDOOM_NO_UPDATE_CHECK": "1"}
    print(f"Running {__version__} from source as if updated from {previous}. Settings sandbox: {data}")
    subprocess.run([sys.executable, "-m", "couch_doom", "--windowed"], cwd=ROOT, env=env, check=False)


def _extract(archive: Path, into: Path) -> None:
    shutil.rmtree(into, ignore_errors=True)
    into.mkdir(parents=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(into)
    else:
        with tarfile.open(archive) as t:
            t.extractall(into, filter="tar")


def _build(sandbox: Path, target: str) -> Path:
    """Package this checkout the way the release workflow does, so the updater accepts it."""
    work = sandbox / "build"
    shutil.rmtree(work, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(work / "dist"),
                    "--workpath", str(work / "work"), str(ROOT / "packaging" / "CouchDoom.spec")], cwd=ROOT, check=True)
    stage = work / "stage" / "CouchDoom"
    shutil.copytree(work / "dist" / "CouchDoom", stage)
    for name in ("packaging/How to use.txt", "LICENSE"):
        shutil.copy2(ROOT / name, stage)
    subprocess.run([sys.executable, str(ROOT / "packaging" / "make_changelog_txt.py"), str(ROOT / "CHANGELOG.md"),
                    str(stage / "CHANGELOG.txt")], check=True)
    base = work / f"CouchDoom-v{__version__}-{target}"
    if target.startswith("windows-"):
        return Path(shutil.make_archive(str(base), "zip", stage.parent, "CouchDoom"))
    return Path(shutil.make_archive(str(base), "gztar", stage.parent, "CouchDoom"))


def full(sandbox: Path, old: str, previous: str | None, launch: bool = True) -> None:
    target = asset_for_platform(sys.platform, platform.machine())
    if not target or target.startswith("macos-"):
        raise SystemExit("The full simulation runs on Windows and Linux; use `quick` here.")
    suffix = ".zip" if target.startswith("windows-") else ".tar.gz"
    name = f"CouchDoom-v{old}-{target}{suffix}"
    downloads = sandbox / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    if not (old_archive := downloads / name).is_file():
        print(f"Downloading {name}")
        urllib.request.urlretrieve(f"{RELEASES}/v{old}/{name}", old_archive)

    print(f"Building {__version__} from this checkout")
    new_archive = _build(sandbox, target)
    manifest = write_manifest(new_archive, sandbox / "feed", target=target, version=__version__)
    release = json.loads(manifest.read_text(encoding="utf-8"))
    section = []
    for line in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("**New in "):
            if section:
                break
            if line == f"**New in {__version__}**":
                section.append(line)
        elif section:
            section.append(line)
    release["body"] = "\n".join(section) or release["body"]  # the notice shows what the real release would say
    manifest.write_text(json.dumps(release, indent=2), encoding="utf-8")

    app = sandbox / "app"
    _extract(old_archive, app)
    install = app / "CouchDoom"
    _write_state(install / "state", previous)  # an old release ignores seen_version; only the new build reads it
    exe = install / ("CouchDoom.exe" if target.startswith("windows-") else "CouchDoom")
    env = {**os.environ, "COUCHDOOM_UPDATE_TEST_MANIFEST": str(manifest)}
    env.pop("COUCHDOOM_DATA_DIR", None)
    if not launch:
        print(f"Ready: {exe}\nStart it with COUCHDOOM_UPDATE_TEST_MANIFEST={manifest}")
        return
    print(f"Starting {old} from {install}. Wait for the update notice, then choose Update and restart.")
    subprocess.Popen([str(exe)], cwd=install, env=env)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("quick", "full"))
    parser.add_argument("--from", dest="previous", default=None,
                        help="Version the player last ran. quick: default 1.2.0. full: default none, as every "
                             "release before 1.2.3 leaves it unrecorded")
    parser.add_argument("--old", default="1.2.2", help="full: the release to start from")
    parser.add_argument("--sandbox", type=Path, default=Path.home() / "couchdoom-update-sim")
    parser.add_argument("--no-launch", action="store_true", help="full: prepare everything but don't start the app")
    args = parser.parse_args()
    if args.mode == "quick":
        quick(args.sandbox, args.previous or "1.2.0")
    else:
        full(args.sandbox, args.old, args.previous, launch=not args.no_launch)


if __name__ == "__main__":
    main()
