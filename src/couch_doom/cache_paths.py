"""Shared platform-specific cache root."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def cache_dir() -> Path:
    if sys.platform == "darwin":
        path = Path(os.environ.get("HOME") or Path.home()) / "Library" / "Caches" / "CouchDoom"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        path = base / "CouchDoom" / "cache"
    else:
        xdg = os.environ.get("XDG_CACHE_HOME")
        base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path(os.environ.get("HOME") or Path.home()) / ".cache"
        path = base / "couch-doom"
    path.mkdir(parents=True, exist_ok=True)
    return path
