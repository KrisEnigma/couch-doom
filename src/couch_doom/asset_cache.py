"""Disk cache for extracted title art, logos, readmes and endoom.

Caches raw extracted assets (not pygame Surfaces) keyed by preset identity so
large pk3s like Project Brutality only need to be scanned once across runs.
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .endoom import Endoom
from .options import Preset
from .readme import Readme
from .titleart import Art
from .cache_paths import cache_dir as _shared_cache_dir


def cache_dir() -> Path:
    """Platform-appropriate cache directory."""
    return _shared_cache_dir()


def _assets_dir() -> Path:
    d = cache_dir() / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def key_for(preset: Preset, iwad: Path | None, files: list[Path]) -> str:
    """Stable key for a preset's asset set based on file identities."""
    import hashlib

    # The selected entries, not only the expanded files: a bundle and its members added loose can have different
    # readmes. Bump the version when what gets cached changes, so stale results are not reused.
    parts: list[str] = ["v3", preset.name, preset.section, preset.engine_id or "",
                        "maps-after-mods" if preset.load_maps_after_mods else "maps-before-mods",
                        *(f"map:{p}" for p in preset.mappacks), *(f"mod:{p}" for p in preset.mods)]
    if iwad:
        try:
            st = iwad.stat()
            parts.append(f"iwad:{iwad.resolve()}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"iwad:{iwad.resolve()}")
    for p in files:
        try:
            st = p.stat()
            parts.append(f"file:{p.resolve()}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"file:{p.resolve()}")
    h = hashlib.sha256("\x00".join(parts).encode("utf-8", errors="replace")).hexdigest()
    return h


def _art_to_dict(a: Art | None) -> dict[str, Any] | None:
    if a is None:
        return None
    d = asdict(a)
    # bytes -> base64
    for k in ("data", "palette", "mask"):
        if k in d and isinstance(d[k], bytes):
            d[k] = base64.b64encode(d[k]).decode("ascii")
    return d


def _art_from_dict(d: dict[str, Any] | None) -> Art | None:
    if d is None:
        return None
    for k in ("data", "palette", "mask"):
        if k in d and isinstance(d[k], str):
            d[k] = base64.b64decode(d[k])
    try:
        return Art(**d)
    except Exception:
        return None


def _readme_to_dict(r: Readme | None) -> dict[str, Any] | None:
    if r is None:
        return None
    d = asdict(r)
    return d


def _readme_from_dict(d: dict[str, Any] | None) -> Readme | None:
    if d is None:
        return None
    try:
        return Readme(**d)
    except Exception:
        return None


def _endoom_to_dict(e: Endoom | None) -> dict[str, Any] | None:
    if e is None:
        return None
    d = asdict(e)
    d["data"] = base64.b64encode(d["data"]).decode("ascii")
    return d


def _endoom_from_dict(d: dict[str, Any] | None) -> Endoom | None:
    if d is None:
        return None
    try:
        if "data" in d and isinstance(d["data"], str):
            d["data"] = base64.b64decode(d["data"])
        return Endoom(**d)
    except Exception:
        return None


class CachedAssets:
    def __init__(self, art: Art | None, readme: Readme | None, endoom: Endoom | None, logo: Art | None,
                 readme_stamp: str | None = None):
        self.art = art
        self.readme = readme
        self.endoom = endoom
        self.logo = logo
        self.readme_stamp = readme_stamp  # None: written before stamps existed


def get(key: str) -> CachedAssets | None:
    path = _assets_dir() / f"{key}.json"
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        art = _art_from_dict(data.get("art"))
        readme = _readme_from_dict(data.get("readme"))
        endoom = _endoom_from_dict(data.get("endoom"))
        logo = _art_from_dict(data.get("logo"))
        # touch for LRU
        try:
            os.utime(path, None)
        except OSError:
            pass
        return CachedAssets(art, readme, endoom, logo, data.get("readme_stamp"))
    except Exception:
        return None


def put(key: str, assets: CachedAssets) -> None:
    path = _assets_dir() / f"{key}.json"
    # The art pool and the cache warmer can write the same key at once; each writes its own file and swaps it in.
    tmp = path.with_name(f"{key}.{os.getpid()}-{threading.get_ident()}.tmp")
    try:
        data = {
            "art": _art_to_dict(assets.art),
            "readme": _readme_to_dict(assets.readme),
            "endoom": _endoom_to_dict(assets.endoom),
            "logo": _art_to_dict(assets.logo),
            "readme_stamp": assets.readme_stamp,
            "ts": time.time(),
        }
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _preset_index_path() -> Path:
    return cache_dir() / "preset_keys.json"


def load_preset_keys() -> dict[str, str]:
    """Last cache key for each preset, remembered without file times.

    A missing drive changes the live key, and the old file can only be kept if we still know its name."""
    try:
        data = json.loads(_preset_index_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, str)}


def save_preset_keys(mapping: dict[str, str]) -> None:
    path = _preset_index_path()
    tmp: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"preset_keys.{os.getpid()}-{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(mapping), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def preset_identity(preset: Preset) -> str:
    """Identity that stays put when a drive is unplugged. Names are not unique; the paths tell them apart."""
    import hashlib

    iwad = getattr(preset, "iwad", None)
    maps = getattr(preset, "mappacks", None) or []
    mods = getattr(preset, "mods", None) or []
    parts = [
        getattr(preset, "name", "") or "",
        getattr(preset, "section", "") or "",
        getattr(preset, "engine_id", "") or "",
        "maps-after-mods" if getattr(preset, "load_maps_after_mods", False) else "maps-before-mods",
        str(iwad or ""),
        *(str(p) for p in maps),
        *(str(p) for p in mods),
    ]
    return hashlib.sha256("\x00".join(parts).encode("utf-8", "replace")).hexdigest()


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def volume_unavailable(path: Path) -> bool:
    """The file's volume isn't mounted. A deleted file on a mounted drive is a real change, not this.

    exists() on a UNC path can sit for half a minute when the server is down, so those are left alone.
    """
    drive = path.drive
    if drive.startswith("\\\\") or drive.startswith("//"):
        return False
    if len(drive) == 2 and drive[1] == ":":
        return not _path_exists(Path(drive + "\\"))
    text = path.as_posix()
    if not text.startswith("/"):
        return False
    # (prefix, how many path parts name the volume itself). A file directly in /mnt is not a volume.
    for root, depth in (("/run/media/", 2), ("/Volumes/", 1), ("/mnt/", 1), ("/media/", 1)):
        if not text.startswith(root):
            continue
        parts = [part for part in text[len(root):].split("/") if part]
        if len(parts) <= depth:
            return False
        return not _path_exists(Path(root + "/".join(parts[:depth])))
    return False


def configured_paths(preset: Preset) -> list[Path]:
    """Paths the preset names, including ones load_order skips because the file is missing."""
    paths: list[Path] = []
    iwad = getattr(preset, "iwad", None)
    if isinstance(iwad, Path):
        paths.append(iwad)
    for attr in ("mappacks", "mods"):
        for item in getattr(preset, attr, None) or []:
            if isinstance(item, Path):
                paths.append(item)
    return paths


def preset_offline(preset: Preset) -> bool:
    return any(volume_unavailable(path) for path in configured_paths(preset))


def invalidate_missing(present_keys: set[str]) -> None:
    try:
        d = _assets_dir()
        for p in d.glob("*.json"):
            if p.stem not in present_keys:
                try:
                    p.unlink()
                except OSError:
                    pass
    except Exception:
        pass


def prune(max_bytes: int = 512 * 1024 * 1024) -> None:
    try:
        d = _assets_dir()
        files = []
        for p in d.glob("*.json"):
            try:
                st = p.stat()
                files.append((st.st_atime, st.st_size, p))
            except OSError:
                continue
        files.sort(key=lambda x: x[0])  # oldest first
        total = sum(f[1] for f in files)
        for _, sz, p in files:
            if total <= max_bytes:
                break
            try:
                p.unlink()
                total -= sz
            except OSError:
                pass
    except Exception:
        pass
