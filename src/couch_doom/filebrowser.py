"""Read-only, one-directory-at-a-time filesystem browsing for the manual launcher picker."""
from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Collection


@dataclass(frozen=True)
class Entry:
    path: Path
    is_dir: bool

    @property
    def display_name(self) -> str:
        return self.path.name + ("/" if self.is_dir else "")


def _windows_roots() -> list[Path]:
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return _drive_roots(mask)


def _drive_roots(mask: int) -> list[Path]:
    return [Path(f"{chr(65 + i)}:/") for i in range(26) if mask & (1 << i)]


def roots(home: Path | None = None, *, candidates: Collection[Path] | None = None) -> list[Path]:
    """Navigable roots with home first. `candidates` is exposed for deterministic platform tests."""
    home = Path.home() if home is None else Path(home)
    if candidates is None:
        candidates = _windows_roots() if os.name == "nt" else [Path("/")]
    out = [home]
    for path in candidates:
        path = Path(path)
        if path not in out:
            out.append(path)
    return out


def parent(directory: Path) -> Path | None:
    directory = Path(directory)
    result = directory.parent
    return result if result != directory else None


def list_entries(
    directory: Path,
    *,
    show_all: bool = False,
    names: Collection[str] = (),
    suffixes: Collection[str] = (".zdl",),
    app_bundles: bool = sys.platform == "darwin",
) -> list[Entry]:
    """List child directories and matching files, without following directory symlinks or recursing."""
    wanted_names = {name.casefold() for name in names}
    wanted_suffixes = {suffix.casefold() for suffix in suffixes}
    if app_bundles:
        wanted_suffixes.add(".app")
    entries: list[Entry] = []
    try:
        with os.scandir(directory) as scan:
            for item in scan:
                try:
                    is_bundle = app_bundles and item.name.casefold().endswith(".app") and item.is_dir(follow_symlinks=False)
                    is_dir = item.is_dir(follow_symlinks=False) and not is_bundle
                    is_file = is_bundle or item.is_file(follow_symlinks=True)
                    if is_dir or (is_file and (show_all or item.name.casefold() in wanted_names
                                               or Path(item.name).suffix.casefold() in wanted_suffixes)):
                        entries.append(Entry(Path(item.path), is_dir))
                except OSError:
                    continue
    except OSError:
        return []
    return sorted(entries, key=lambda e: (not e.is_dir, e.path.name.casefold(), e.path.name))


class Browser:
    """Small navigation state model; UI code decides how actions and rows are presented."""

    def __init__(self, home: Path | None = None, *, candidates: Collection[Path] | None = None,
                 names: Collection[str] = (), suffixes: Collection[str] = (".zdl",),
                 app_bundles: bool = sys.platform == "darwin"):
        self.roots = roots(home, candidates=candidates)
        self.directory = self.roots[0]
        self.names, self.suffixes = tuple(names), tuple(suffixes)
        self.app_bundles = app_bundles
        self.show_all = False
        self.selected = 0
        self.entries: list[Entry] = []
        self.refresh()

    def refresh(self) -> None:
        self.entries = list_entries(self.directory, show_all=self.show_all, names=self.names, suffixes=self.suffixes,
                                    app_bundles=self.app_bundles)
        self.selected = max(0, min(self.selected, len(self.entries) - 1))

    def move(self, amount: int) -> None:
        if self.entries:
            self.selected = max(0, min(len(self.entries) - 1, self.selected + amount))

    def toggle_all(self) -> None:
        self.show_all = not self.show_all
        self.selected = 0
        self.refresh()

    def open_selected(self) -> Path | None:
        if not self.entries:
            return None
        entry = self.entries[self.selected]
        if entry.is_dir:
            self.directory = entry.path
            self.selected = 0
            self.refresh()
            return None
        return entry.path

    def back(self) -> bool:
        above = parent(self.directory)
        if above is None:
            return False
        old = self.directory
        self.directory = above
        self.refresh()
        self.selected = next((i for i, e in enumerate(self.entries) if e.path == old), 0)
        return True

    def change_root(self, amount: int) -> None:
        try:
            current = next(i for i, root in enumerate(self.roots) if root == self.directory)
        except StopIteration:
            # From a nested folder, left/right jumps from the closest listed root.
            current = max((i for i, root in enumerate(self.roots) if self.directory == root or root in self.directory.parents), default=0)
        self.directory = self.roots[max(0, min(len(self.roots) - 1, current + amount))]
        self.selected = 0
        self.refresh()
