"""Download, validate, stage, and apply packaged application updates."""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .update import ReleaseAsset

CHUNK = 256 * 1024


class UpdateError(Exception):
    """A safe, user-displayable update failure."""


@dataclass(frozen=True)
class StagedUpdate:
    version: str
    root: Path
    app_path: Path
    archive_path: Path


def discard_staged(staged: StagedUpdate) -> None:
    shutil.rmtree(staged.root, ignore_errors=True)


def _request(url: str):
    allowed = url.startswith("https://github.com/") or (
        bool(os.environ.get("COUCHDOOM_UPDATE_TEST_MANIFEST")) and url.startswith("file://"))
    if not allowed:
        raise UpdateError("The release download URL was invalid.")
    req = urllib.request.Request(url, headers={"User-Agent": "CouchDoom updater"})
    return urllib.request.urlopen(req, timeout=30)


def _read(url: str) -> bytes:
    try:
        with _request(url) as response:
            return response.read(4096)
    except (OSError, ValueError) as exc:
        raise UpdateError(f"Could not download update metadata: {exc}") from exc


def download_and_stage(asset: ReleaseAsset, version: str, *, staging_root: Path,
                       platform: str, progress: Callable[[int, int | None], None] | None = None,
                       cancel: threading.Event | None = None) -> StagedUpdate:
    if not asset.name.startswith(f"CouchDoom-v{version}-"):
        raise UpdateError("The release archive name did not match its version.")
    staging_root.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="couchdoom-update-", dir=staging_root))
    archive_path = root / asset.name
    partial = archive_path.with_suffix(archive_path.suffix + ".part")
    try:
        expected = _read(asset.sha256_url).decode("ascii", "strict").strip().split()
        if (len(expected) != 2 or expected[1].lstrip("* ") != asset.name or len(expected[0]) != 64
                or any(c not in "0123456789abcdefABCDEF" for c in expected[0])):
            raise UpdateError("The release checksum file was malformed.")
        digest = hashlib.sha256()
        total = 0
        try:
            with _request(asset.url) as response, partial.open("wb") as output:
                length = response.headers.get("Content-Length")
                total_length = int(length) if length and length.isdigit() else None
                while True:
                    if cancel and cancel.is_set():
                        raise UpdateError("Update cancelled.")
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    total += len(chunk)
                    if progress:
                        progress(total, total_length)
        except (OSError, ValueError) as exc:
            raise UpdateError(f"Could not download the update: {exc}") from exc
        if digest.hexdigest().lower() != expected[0].lower():
            raise UpdateError("The downloaded update failed its SHA-256 check.")
        partial.replace(archive_path)
        extracted = root / "extracted"
        if asset.name.endswith(".zip"):
            _extract_zip(archive_path.read_bytes(), extracted)
        elif asset.name.endswith(".tar.gz"):
            _extract_tar(archive_path, extracted)
        else:
            raise UpdateError("The release archive format was not supported.")
        if platform.startswith("macos-"):
            app_path = extracted / "CouchDoom" / "CouchDoom.app"
        else:
            app_path = extracted / "CouchDoom"
        if not app_path.is_dir():
            raise UpdateError("The release archive did not contain the expected app.")
        return StagedUpdate(version, root, app_path, archive_path)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def _safe_destination(root: Path, name: str) -> Path:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise UpdateError("The release archive contained an unsafe path.")
    dest = (root / path).resolve()
    if not dest.is_relative_to(root.resolve()):
        raise UpdateError("The release archive contained an unsafe path.")
    return dest


def _safe_link(root: Path, path: Path, target: str) -> str:
    linked = Path(target)
    if linked.is_absolute() or (linked.drive if os.name == "nt" else False):
        raise UpdateError("The release archive contained an unsafe symbolic link.")
    destination = Path(os.path.abspath(path.parent / linked))
    if not destination.is_relative_to(root.resolve()):
        raise UpdateError("The release archive contained an unsafe symbolic link.")
    return target


def _extract_zip(data: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = [(item, _safe_destination(destination, item.filename)) for item in archive.infolist()]
            links = {path for item, path in members if ((item.external_attr >> 16) & 0o170000) == 0o120000}
            for item, path in members:
                if any(parent in links for parent in path.parents):
                    raise UpdateError("The release archive placed a file beneath a symbolic link.")
            for item, path in members:
                kind = (item.external_attr >> 16) & 0o170000
                if item.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                elif kind == 0o120000:
                    target = archive.read(item).decode("utf-8", "strict")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(_safe_link(destination, path, target), path)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(item) as src, path.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    permissions = (item.external_attr >> 16) & 0o777 if item.create_system == 3 else 0
                    if permissions:
                        path.chmod(permissions)
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError(f"Could not unpack update: {exc}") from exc


def _extract_tar(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = [(item, _safe_destination(destination, item.name)) for item in archive.getmembers()]
            if any(item.islnk() or not (item.isfile() or item.isdir() or item.issym()) for item, _ in members):
                raise UpdateError("The release archive contained an unsupported link or file type.")
            links = {path for item, path in members if item.issym()}
            for item, path in members:
                if any(parent in links for parent in path.parents):
                    raise UpdateError("The release archive placed a file beneath a symbolic link.")
            for item, path in members:
                if item.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                elif item.issym():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(_safe_link(destination, path, item.linkname), path)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(item)
                    if source is None:
                        raise UpdateError("The release archive contained an unreadable file.")
                    with source, path.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    path.chmod(item.mode & 0o777)
    except (OSError, tarfile.TarError) as exc:
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError(f"Could not unpack update: {exc}") from exc


def installation_path(executable: Path, platform: str) -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    executable = executable.resolve()
    if platform.startswith("macos-"):
        for parent in executable.parents:
            if parent.suffix == ".app":
                return parent
        return None
    return executable.parent


def helper_executable(app_path: Path, platform: str) -> Path:
    if platform.startswith("macos-"):
        return app_path / "Contents" / "MacOS" / "CouchDoom"
    return app_path / ("CouchDoom.exe" if platform.startswith("windows-") else "CouchDoom")


def _installed_app_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("COUCHDOOM_UPDATE_TEST_MANIFEST", None)
    return env


def launch_apply_helper(staged: StagedUpdate, install_path: Path, pid: int, platform: str) -> None:
    helper_root = staged.root / "apply-helper"
    helper_root.mkdir(parents=True, exist_ok=True)
    helper_app = helper_root / staged.app_path.name
    shutil.copytree(staged.app_path, helper_app, symlinks=True)
    helper = helper_executable(helper_app, platform)
    if not helper.is_file() or (os.name != "nt" and not os.access(helper, os.X_OK)):
        raise UpdateError("The staged update helper was missing.")
    subprocess.Popen([str(helper), "--apply-update", str(staged.app_path), str(install_path), str(pid), platform, str(staged.root)],
                     cwd=str(helper_root), close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def _wait_for_exit(pid: int, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.2)
    raise UpdateError("CouchDoom did not exit in time to apply the update.")


def apply_staged_update(staged_app: Path, install_path: Path, *, pid: int, platform: str,
                        relaunch: bool = True, cleanup_root: Path | None = None) -> int:
    staged_app, install_path = staged_app.resolve(), install_path.resolve()
    if not staged_app.is_dir() or not install_path.is_dir() or staged_app == install_path:
        raise UpdateError("The update or installation path was invalid.")
    _wait_for_exit(pid)
    backup = install_path.with_name(f".{install_path.name}.old-{pid}")
    if backup.exists():
        raise UpdateError("A previous update backup needs attention before another update can be installed.")
    moved_new = False
    try:
        if not platform.startswith("macos-"):
            for name in ("state", "soundfonts"):
                source = install_path / name
                if source.exists():
                    destination = staged_app / name
                    if destination.exists():
                        shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
                    shutil.copytree(source, destination) if source.is_dir() else shutil.copy2(source, destination)
        install_path.rename(backup)
        try:
            shutil.move(str(staged_app), str(install_path))
            moved_new = True
        except OSError:
            backup.rename(install_path)
            raise
        if relaunch:
            subprocess.Popen([str(helper_executable(install_path, platform))], cwd=str(install_path.parent),
                             close_fds=True, env=_installed_app_environment(), stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception as exc:
        try:
            if moved_new and install_path.exists():
                failed = install_path.with_name(f".{install_path.name}.failed-{pid}")
                install_path.rename(failed)
            if backup.exists():
                backup.rename(install_path)
            if "failed" in locals():
                shutil.rmtree(failed, ignore_errors=True)
            if relaunch and install_path.exists():
                subprocess.Popen([str(helper_executable(install_path, platform))], cwd=str(install_path.parent),
                                 close_fds=True, env=_installed_app_environment(), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError(f"Could not install the update: {exc}") from exc
    shutil.rmtree(backup, ignore_errors=True)
    if cleanup_root:
        shutil.rmtree(cleanup_root, ignore_errors=True)
    return 0
