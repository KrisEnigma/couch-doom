"""Download, validate, stage, and apply packaged application updates."""
from __future__ import annotations

import dataclasses
import hashlib
import io
import json
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

from .update import ReleaseAsset, https_context

CHUNK = 256 * 1024
RESULT_FILE = "update-result.json"

# progress(phase, done, total): phases arrive in this order; done/total are bytes while downloading,
# files while unpacking, and 0/None otherwise.
PHASES = ("checking", "downloading", "verifying", "unpacking", "preparing")
Progress = Callable[[str, int, "int | None"], None]


class UpdateError(Exception):
    """A safe, user-displayable update failure."""


@dataclass(frozen=True)
class StagedUpdate:
    version: str
    root: Path
    app_path: Path
    archive_path: Path
    helper: Path | None = None  # set by prepare_apply_helper


STAGING_PREFIX = "couchdoom-update-"


def discard_staged(staged: StagedUpdate) -> None:
    shutil.rmtree(staged.root, ignore_errors=True)


def purge_stale_update_dirs(staging_root: Path) -> None:
    """Remove leftover couchdoom-update-* folders from interrupted downloads or failed applies."""
    if not staging_root.is_dir():
        return
    for path in staging_root.iterdir():
        if path.is_dir() and path.name.startswith(STAGING_PREFIX):
            shutil.rmtree(path, ignore_errors=True)


def _request(url: str):
    allowed = url.startswith("https://github.com/") or (
        bool(os.environ.get("COUCHDOOM_UPDATE_TEST_MANIFEST")) and url.startswith("file://"))
    if not allowed:
        raise UpdateError("The release download URL was invalid.")
    req = urllib.request.Request(url, headers={"User-Agent": "CouchDoom updater"})
    # file:// is the local test manifest. https uses the bundled CAs: see https_context.
    context = https_context() if url.startswith("https://") else None
    return urllib.request.urlopen(req, timeout=30, context=context)


def _read(url: str) -> bytes:
    try:
        with _request(url) as response:
            return response.read(4096)
    except (OSError, ValueError) as exc:
        raise UpdateError(f"Could not download update metadata: {exc}") from exc


def download_and_stage(asset: ReleaseAsset, version: str, *, staging_root: Path,
                       platform: str, progress: Progress | None = None,
                       cancel: threading.Event | None = None) -> StagedUpdate:
    if not asset.name.startswith(f"CouchDoom-v{version}-"):
        raise UpdateError("The release archive name did not match its version.")
    report = progress or (lambda phase, done, total: None)
    staging_root.mkdir(parents=True, exist_ok=True)
    purge_stale_update_dirs(staging_root)
    root = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=staging_root))
    archive_path = root / asset.name
    partial = archive_path.with_suffix(archive_path.suffix + ".part")
    try:
        report("checking", 0, None)
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
                report("downloading", 0, total_length)
                while True:
                    _check_cancel(cancel)
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    total += len(chunk)
                    report("downloading", total, total_length)
        except (OSError, ValueError) as exc:
            raise UpdateError(f"Could not download the update: {exc}") from exc
        report("verifying", 0, None)
        if digest.hexdigest().lower() != expected[0].lower():
            raise UpdateError("The downloaded update failed its SHA-256 check.")
        partial.replace(archive_path)
        extracted = root / "extracted"
        unpacked = lambda done, count: report("unpacking", done, count)
        if asset.name.endswith(".zip"):
            _extract_zip(archive_path, extracted, unpacked, cancel)
        elif asset.name.endswith(".tar.gz"):
            _extract_tar(archive_path, extracted, unpacked, cancel)
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


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel and cancel.is_set():
        raise UpdateError("Update cancelled.")


def _extract_zip(source: Path | bytes, destination: Path, progress: Callable[[int, int], None] | None = None,
                 cancel: threading.Event | None = None) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    try:
        # A path is read member by member; the whole archive never sits in memory.
        with zipfile.ZipFile(io.BytesIO(source) if isinstance(source, bytes) else source) as archive:
            members = [(item, _safe_destination(destination, item.filename)) for item in archive.infolist()]
            links = {path for item, path in members if ((item.external_attr >> 16) & 0o170000) == 0o120000}
            for item, path in members:
                if any(parent in links for parent in path.parents):
                    raise UpdateError("The release archive placed a file beneath a symbolic link.")
            for done, (item, path) in enumerate(members):
                _check_cancel(cancel)
                if progress:
                    progress(done, len(members))
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
            if progress:
                progress(len(members), len(members))
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError(f"Could not unpack update: {exc}") from exc


def _extract_tar(archive_path: Path, destination: Path, progress: Callable[[int, int], None] | None = None,
                 cancel: threading.Event | None = None) -> None:
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
            for done, (item, path) in enumerate(members):
                _check_cancel(cancel)
                if progress:
                    progress(done, len(members))
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
            if progress:
                progress(len(members), len(members))
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


def prepare_apply_helper(staged: StagedUpdate, platform: str) -> StagedUpdate:
    """Copy the staged app to run the swap from. Hundreds of files: call it off the UI thread."""
    helper_root = staged.root / "apply-helper"
    helper_root.mkdir(parents=True, exist_ok=True)
    helper_app = helper_root / staged.app_path.name
    shutil.copytree(staged.app_path, helper_app, symlinks=True)
    helper = helper_executable(helper_app, platform)
    if not helper.is_file() or (os.name != "nt" and not os.access(helper, os.X_OK)):
        raise UpdateError("The staged update helper was missing.")
    return dataclasses.replace(staged, helper=helper)


def download_and_prepare(asset: ReleaseAsset, version: str, *, staging_root: Path, platform: str,
                         progress: Progress | None = None, cancel: threading.Event | None = None) -> StagedUpdate:
    """Everything up to the restart. Cancel is honoured until "preparing" starts, and not after."""
    staged = download_and_stage(asset, version, staging_root=staging_root, platform=platform,
                                progress=progress, cancel=cancel)
    try:
        _check_cancel(cancel)
        if progress:
            progress("preparing", 0, None)
        return prepare_apply_helper(staged, platform)
    except Exception:
        discard_staged(staged)
        raise


def launch_apply_helper(staged: StagedUpdate, install_path: Path, pid: int, platform: str,
                        result_file: Path | None = None) -> None:
    """Start the prepared helper, which waits for this process to exit before swapping folders."""
    if staged.helper is None or not staged.helper.is_file():
        raise UpdateError("The staged update helper was missing.")
    argv = [str(staged.helper), "--apply-update", str(staged.app_path), str(install_path), str(pid), platform, str(staged.root)]
    if result_file is not None:
        argv.append(str(result_file))
    subprocess.Popen(argv, cwd=str(staged.root / "apply-helper"), close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def write_result(path: Path | None, ok: bool, error: str = "") -> None:
    """Leave the outcome for the next CouchDoom to report; the helper has no window of its own."""
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"ok": ok, "error": error}), encoding="utf-8")
    except OSError:
        pass


def take_result(path: Path) -> dict | None:
    """Read and remove the helper's outcome, so it's reported once."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    return data if isinstance(data, dict) and isinstance(data.get("ok"), bool) else None


def _wait_for_exit(pid: int, timeout: float = 120) -> None:
    if os.name == "nt":
        # os.kill(pid, 0) is TerminateProcess on Windows: it would end CouchDoom mid-exit, not check on it.
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return  # already gone
        try:
            if kernel32.WaitForSingleObject(ctypes.c_void_p(handle), int(timeout * 1000)) != 0:
                raise UpdateError("CouchDoom did not exit in time to apply the update.")
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.2)
    raise UpdateError("CouchDoom did not exit in time to apply the update.")


def _rename_when_free(source: Path, destination: Path, timeout: float = 10) -> None:
    """Windows keeps a just-exited program's files busy for a moment, and antivirus may scan them; retry briefly."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            source.rename(destination)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def _relaunch(install_path: Path, platform: str) -> None:
    subprocess.Popen([str(helper_executable(install_path, platform))], cwd=str(install_path.parent),
                     close_fds=True, env=_installed_app_environment(), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def apply_staged_update(staged_app: Path, install_path: Path, *, pid: int, platform: str,
                        relaunch: bool = True, cleanup_root: Path | None = None,
                        result_file: Path | None = None) -> int:
    """Swap the staged app into place and relaunch. The result is written before any relaunch,
    so the app that starts next can say whether the update worked."""
    try:
        staged_app, install_path = staged_app.resolve(), install_path.resolve()
        if not staged_app.is_dir() or not install_path.is_dir() or staged_app == install_path:
            raise UpdateError("The update or installation path was invalid.")
        _wait_for_exit(pid)
    except UpdateError as exc:
        write_result(result_file, False, str(exc))
        raise
    backup = install_path.with_name(f".{install_path.name}.old-{pid}")
    if backup.exists():
        message = "A previous update backup needs attention before another update can be installed."
        write_result(result_file, False, message)
        if relaunch:
            try:
                _relaunch(install_path, platform)
            except OSError:
                pass
        raise UpdateError(message)
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
        _rename_when_free(install_path, backup)
        try:
            shutil.move(str(staged_app), str(install_path))
            moved_new = True
        except OSError:
            backup.rename(install_path)
            raise
        write_result(result_file, True)
        if relaunch:
            _relaunch(install_path, platform)
    except Exception as exc:
        error = exc if isinstance(exc, UpdateError) else UpdateError(f"Could not install the update: {exc}")
        try:
            if moved_new and install_path.exists():
                failed = install_path.with_name(f".{install_path.name}.failed-{pid}")
                install_path.rename(failed)
            if backup.exists():
                backup.rename(install_path)
            if "failed" in locals():
                shutil.rmtree(failed, ignore_errors=True)
            write_result(result_file, False, str(error))
            if relaunch and install_path.exists():
                _relaunch(install_path, platform)
        except OSError:
            pass
        if error is exc:
            raise
        raise error from exc
    shutil.rmtree(backup, ignore_errors=True)
    if cleanup_root:
        shutil.rmtree(cleanup_root, ignore_errors=True)
    return 0
