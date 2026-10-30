"""Small, testable reactions to picking something that is really CouchDoom itself.

The matchers here are pure: the UI decides how to present a Reaction, so eggs can be tested without an App.
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import FROZEN, PROJECT_ROOT, SOURCE_TREE
from .self_select import same_path

DOOMCEPTION_MESSAGE = "Doomception! I’m already running."
SELF_EXECUTABLE_NAMES = {"couchdoom", "couchdoom.exe"}
_SELF_NAMES = {"couch-doom", "couch-doom.exe", "couch_doom_entry.py"}


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
    if FROZEN:
        executable = Path(sys.executable)
        if sys.platform == "darwin":
            bundled = next((parent for parent in executable.parents if parent.suffix.casefold() == ".app"), None)
            if bundled is not None:
                candidates.add(executable)
        elif same_path(executable.parent, PROJECT_ROOT):
            candidates.add(executable)
        if sys.platform == "darwin":
            packaged = PROJECT_ROOT / "CouchDoom.app" / "Contents" / "MacOS" / "CouchDoom"
        else:
            packaged = PROJECT_ROOT / ("CouchDoom.exe" if os.name == "nt" else "CouchDoom")
        if packaged.is_file():
            candidates.add(packaged)
    else:
        if console := shutil.which("couch-doom"):
            candidates.add(Path(console))
        if sys.argv and Path(sys.argv[0]).name.casefold() in _SELF_NAMES:
            candidates.add(Path(sys.argv[0]))
        root = Path(__file__).resolve().parents[2]
        for relative in ("run.bat", "packaging/couch_doom_entry.py"):
            if (candidate := root / relative).is_file():
                candidates.add(candidate)
    return {path.resolve(strict=False) for path in candidates}


def self_folders() -> set[Path]:
    """Folders that are the app itself: the install root or source tree, never a shared bin directory."""
    if getattr(sys, "frozen", False) or SOURCE_TREE:
        return {PROJECT_ROOT.resolve(strict=False)}
    return set()


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
    return False


def react_to_pick(path: Path) -> Reaction | None:
    """React to a packaged CouchDoom executable by name, or to the exact source-run identity."""
    selected = Path(path)
    if selected.is_dir() and selected.suffix.casefold() != ".app":
        return None
    if selected.name.casefold() in SELF_EXECUTABLE_NAMES:
        return Reaction(DOOMCEPTION_MESSAGE)
    if FROZEN:
        paths = self_paths()
        own_names = {candidate.name.casefold() for candidate in paths}
        own_names.update(bundle.name.casefold() for candidate in paths if (bundle := _app_bundle(candidate)))
        if selected.name.casefold() in own_names:
            return Reaction(DOOMCEPTION_MESSAGE)
    return Reaction(DOOMCEPTION_MESSAGE) if _is_self(selected) else None


def react_to_folder(path: Path) -> Reaction | None:
    """The reaction for picking the install/source folder itself; used only after launcher detection fails."""
    selected = Path(path)
    if not selected.is_dir():
        return None
    return Reaction(DOOMCEPTION_MESSAGE) if any(same_path(selected, folder) for folder in self_folders()) else None


def self_matcher() -> Callable[[os.DirEntry], bool]:
    """Browser predicate built once per Browser: cheap name check before resolving paths."""
    paths = self_paths()
    bundles = {bundle for path in paths if (bundle := _app_bundle(path))}
    candidates = tuple(paths | bundles)
    names = {path.name.casefold() for path in candidates}

    def match(entry: os.DirEntry) -> bool:
        if entry.name.casefold() not in names:
            return False
        if entry.is_dir(follow_symlinks=False) and not entry.name.casefold().endswith(".app"):
            return False
        selected = Path(entry.path).resolve(strict=False)
        return any(same_path(selected, candidate) for candidate in candidates)

    return match
