"""Create a local fake latest-release manifest for packaged updater testing."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from couch_doom.update import asset_for_platform  # noqa: E402


def write_manifest(archive_path: Path, output_dir: Path, *, target: str | None = None,
                   version: str = "99.0.0") -> Path:
    archive_path, output_dir = Path(archive_path), Path(output_dir)
    target = target or asset_for_platform(sys.platform, platform.machine())
    if not target:
        raise ValueError("Could not map this OS/arch to a CouchDoom release target.")
    if not archive_path.is_file():
        raise ValueError("Pass a CouchDoom release archive (.zip or .tar.gz).")
    suffix = "".join(archive_path.suffixes)
    if suffix not in (".zip", ".tar.gz"):
        raise ValueError("Archive must be a .zip or .tar.gz.")
    output_dir.mkdir(parents=True, exist_ok=True)
    name = f"CouchDoom-v{version}-{target}{suffix}"
    local_archive = output_dir / name
    shutil.copyfile(archive_path, local_archive)
    digest_path = output_dir / (name + ".sha256")
    digest_path.write_text(f"{hashlib.sha256(local_archive.read_bytes()).hexdigest()}  {name}\n", encoding="ascii")
    manifest = {
        "tag_name": f"v{version}",
        "html_url": f"https://github.com/KrisEnigma/couch-doom/releases/tag/v{version}",
        "body": f"**New in {version}**\n- Local updater test\n",
        "assets": [
            {"name": name, "browser_download_url": local_archive.as_uri()},
            {"name": name + ".sha256", "browser_download_url": digest_path.as_uri()},
        ],
    }
    manifest_path = output_dir / "latest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Downloaded CouchDoom release archive (.zip or .tar.gz)")
    parser.add_argument("--output", type=Path, default=Path.home() / "couchdoom-update-test",
                        help="Folder for the renamed test archive and local manifest")
    parser.add_argument("--target", default=None,
                        help="Release target override, e.g. windows-x64 (default: this machine)")
    parser.add_argument("--version", default="99.0.0", help="Fake newer version tag without the leading v")
    args = parser.parse_args()
    print(write_manifest(args.archive, args.output, target=args.target, version=args.version))


if __name__ == "__main__":
    main()
