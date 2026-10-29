"""Persistent selection and encoded-stream caches for title music."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from hashlib import sha256
from pathlib import Path
from typing import Collection, Sequence

from .archive import ArchiveSource
from .cache_paths import cache_dir

MAX_STREAM_BYTES = 256 * 1024 * 1024
MANIFEST_VERSION = 1
FINDER_VERSION = 1
STALE_PART_SECONDS = 24 * 60 * 60
_LOCK = threading.RLock()


def music_dir() -> Path:
    path = cache_dir() / "music"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_dir() -> Path:
    path = music_dir() / "index"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest_path(key: str) -> Path:
    return _index_dir() / f"{sha256(key.encode('utf-8', 'replace')).hexdigest()}.json"


def selection_key(asset_key: str, iwad: Path | None = None, files: Sequence[Path] = ()) -> str:
    """Key a finder result by the existing preset key and every actual music-finder input."""
    parts = [asset_key, str(FINDER_VERSION)]
    for label, path in ([('iwad', iwad)] if iwad else []) + [('file', path) for path in files]:
        try:
            stat = path.stat()
            parts.append(f"{label}:{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}")
        except OSError:
            parts.append(f"{label}:{path.resolve()}")
    return sha256("\0".join(parts).encode("utf-8", "replace")).hexdigest()


def get_selection(key: str) -> tuple[bool, dict | None]:
    try:
        path = _manifest_path(key)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != MANIFEST_VERSION or not isinstance(data.get("result"), dict):
            return False, None
        try:
            os.utime(path, None)
        except OSError:
            pass
        return True, data["result"]
    except (OSError, ValueError, TypeError):
        return False, None


def put_selection(key: str, result: dict) -> None:
    path = _manifest_path(key)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".part", delete=False) as f:
            temp_path = Path(f.name)
            json.dump({"version": MANIFEST_VERSION, "result": result}, f, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        if temp_path:
            temp_path.unlink(missing_ok=True)
        raise


def invalidate_selections(present_keys: set[str]) -> None:
    """Remove manifests whose base preset/input key is no longer present."""
    active = {_manifest_path(key).name for key in present_keys}
    try:
        for path in _index_dir().glob("*.json"):
            if path.name not in active:
                try:
                    path.unlink()
                except OSError:
                    pass
    except OSError:
        pass


def _stream_path(source: ArchiveSource, suffix: str) -> Path:
    suffix = suffix.lower().lstrip(".")
    if suffix not in {"ogg", "mp3", "flac", "wav", "it", "xm", "s3m", "mod"}:
        raise ValueError(f"unsupported stream suffix: {suffix}")
    return music_dir() / f"{source.identity}.{suffix}"


def cache_stream(source: ArchiveSource, suffix: str, cancel: threading.Event,
                 protected: Collection[Path] = ()) -> Path:
    path = _stream_path(source, suffix)
    with _LOCK:
        if path.is_file():
            try:
                if path.stat().st_size == source.size:
                    os.utime(path, None)
                    prune({*protected, path})
                    return path
            except OSError:
                pass
            path.unlink(missing_ok=True)
        if cancel.is_set():
            raise InterruptedError("music cache population cancelled")
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=path.name + ".", suffix=".part",
                                             delete=False) as f:
                temp_path = Path(f.name)
                copied = source.copy_to(f, cancel)
                f.flush()
                os.fsync(f.fileno())
            if copied != source.size or temp_path.stat().st_size != source.size:
                raise OSError(f"incomplete music extraction: expected {source.size}, copied {copied}")
            if cancel.is_set():
                raise InterruptedError("music cache population cancelled")
            os.replace(temp_path, path)
            temp_path = None
            prune({*protected, path})
            return path
        except Exception:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise


def prune(protected: Collection[Path] = (), max_bytes: int | None = None) -> None:
    """Evict by atime toward the cap; protected in-use files may temporarily exceed it."""
    with _LOCK:
        cap = MAX_STREAM_BYTES if max_bytes is None else max_bytes
        keep = {p.resolve() for p in protected}
        now = time.time()
        try:
            directory = music_dir()
            files = []
            for folder in (directory, _index_dir()):
                for path in folder.iterdir():
                    if not path.is_file():
                        continue
                    try:
                        stat = path.stat()
                        if path.name.endswith(".part"):
                            if now - stat.st_mtime > STALE_PART_SECONDS:
                                path.unlink(missing_ok=True)
                            continue
                        if folder == directory and path.suffix.lower() != ".json":
                            files.append((stat.st_atime, stat.st_size, path))
                    except OSError:
                        continue
            total = sum(size for _, size, _ in files)
            for _, size, path in sorted(files, key=lambda row: row[0]):
                if total <= cap:
                    break
                try:
                    if path.resolve() in keep:
                        continue
                    path.unlink()
                    total -= size
                except OSError:
                    pass
        except OSError:
            pass
