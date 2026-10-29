"""Disk cache for extracted title art, logos, readmes and endoom.

Caches raw extracted assets (not pygame Surfaces) keyed by preset identity so
large pk3s like Project Brutality only need to be scanned once across runs.
"""
from __future__ import annotations

import base64
import json
import os
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

    parts: list[str] = [preset.name, preset.section, preset.engine_id or ""]
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
    # cells might contain tuples
    return d


def _endoom_from_dict(d: dict[str, Any] | None) -> Endoom | None:
    if d is None:
        return None
    try:
        # cells are list of tuples
        if "cells" in d and isinstance(d["cells"], list):
            d["cells"] = [tuple(c) for c in d["cells"]]
        return Endoom(**d)
    except Exception:
        return None


class CachedAssets:
    def __init__(self, art: Art | None, readme: Readme | None, endoom: Endoom | None, logo: Art | None):
        self.art = art
        self.readme = readme
        self.endoom = endoom
        self.logo = logo


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
        return CachedAssets(art, readme, endoom, logo)
    except Exception:
        return None


def put(key: str, assets: CachedAssets) -> None:
    path = _assets_dir() / f"{key}.json"
    try:
        data = {
            "art": _art_to_dict(assets.art),
            "readme": _readme_to_dict(assets.readme),
            "endoom": _endoom_to_dict(assets.endoom),
            "logo": _art_to_dict(assets.logo),
            "ts": time.time(),
        }
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


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
