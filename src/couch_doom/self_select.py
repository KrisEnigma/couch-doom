"""Path comparison helpers for recognizing the running app."""
from __future__ import annotations

import sys
from pathlib import Path


def same_path(left: Path, right: Path, *, platform: str | None = None) -> bool:
    """Compare resolved paths, case-insensitively where the platform's default filesystem is."""
    platform = sys.platform if platform is None else platform
    a, b = str(left.resolve(strict=False)), str(right.resolve(strict=False))
    return a.casefold() == b.casefold() if platform in ("win32", "darwin") else a == b
