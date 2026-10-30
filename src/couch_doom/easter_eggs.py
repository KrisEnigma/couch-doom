"""Small, testable reactions to picking something that is really CouchDoom itself.

The matchers here are pure: the UI decides how to present a Reaction, so eggs can be tested without an App.
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .self_select import same_path

DOOMCEPTION_MESSAGE = "Doomception! I’m already running."


@dataclass(frozen=True)
class Reaction:
    message: str
    sound: str | None = "secret"


def self_paths() -> set[Path]:
    """Every path that identifies this app: frozen exe, console script, or the source-tree launchers.

    The Python interpreter is deliberately absent when running from source; picking it is not an egg.
    """
    candidates: set[Path] = set()
    if override := os.environ.get("COUCHDOOM_SELF"):
        candidates.add(Path(override))
    if getattr(sys, "frozen", False):
        candidates.add(Path(sys.executable))
    else:
        if console := shutil.which("couch-doom"):
            candidates.add(Path(console))
        if sys.argv and Path(sys.argv[0]).name.casefold().startswith("couch"):
            candidates.add(Path(sys.argv[0]))
        root = Path(__file__).resolve().parents[2]
        for relative in ("run.bat", "packaging/couch_doom_entry.py"):
            if (candidate := root / relative).is_file():
                candidates.add(candidate)
    return {path.resolve(strict=False) for path in candidates}


def _app_bundle(path: Path) -> Path | None:
    return next((parent for parent in path.parents if parent.suffix.casefold() == ".app"), None)


def _is_self(path: Path) -> bool:
    selected = path.resolve(strict=False)
    for candidate in self_paths():
        if same_path(selected, candidate):
            return True
        bundle = _app_bundle(candidate)
        if bundle is not None and same_path(selected, bundle):
            return True
        # Dropping the folder that holds the executable is a natural way to pick the app itself.
        if same_path(selected, candidate.parent):
            return True
    return False


def react_to_pick(path: Path) -> Reaction | None:
    """The reaction for picking one of our own paths, or None for an ordinary file."""
    return Reaction(DOOMCEPTION_MESSAGE) if _is_self(Path(path)) else None


def is_self_entry(entry: os.DirEntry) -> bool:
    """Browser predicate: compare resolved paths, not names, so another copy elsewhere stays a launcher."""
    return _is_self(Path(entry.path))
