"""Recognize the running frozen app when the user browses for a launcher."""
from __future__ import annotations

import sys
from pathlib import Path


def _same_path(left: Path, right: Path, *, platform: str) -> bool:
    a, b = str(left.resolve(strict=False)), str(right.resolve(strict=False))
    return a.casefold() == b.casefold() if platform == "win32" else a == b


def is_self_selection(
    selected: Path,
    *,
    executable: Path | None = None,
    frozen: bool | None = None,
    platform: str | None = None,
) -> bool:
    """Return true for this executable, or its enclosing macOS .app bundle."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if not frozen:
        return False
    executable = Path(sys.executable if executable is None else executable)
    selected = Path(selected)
    platform = sys.platform if platform is None else platform
    if _same_path(selected, executable, platform=platform):
        return True
    if platform == "darwin":
        bundle = next((parent for parent in executable.parents if parent.suffix.casefold() == ".app"), None)
        return bundle is not None and _same_path(selected, bundle, platform=platform)
    return False
