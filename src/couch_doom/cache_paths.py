"""Shared platform-specific cache root."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_directory(path: Path) -> Path:
    """Create ``path`` as a directory, replacing a non-directory occupant (e.g. a dangling junction)."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except (FileExistsError, OSError):
        if path.is_dir():
            raise
        # A file or reparse point occupies the name; do not follow the target.
        path.unlink()
        path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    if override := os.environ.get("COUCHDOOM_CACHE_DIR"):
        path = Path(override)
    elif sys.platform == "darwin":
        path = Path(os.environ.get("HOME") or Path.home()) / "Library" / "Caches" / "CouchDoom"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        path = base / "CouchDoom" / "cache"
    else:
        xdg = os.environ.get("XDG_CACHE_HOME")
        base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path(os.environ.get("HOME") or Path.home()) / ".cache"
        path = base / "couch-doom"
    return _ensure_directory(path)
