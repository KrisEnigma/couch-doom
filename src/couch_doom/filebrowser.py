"""Read-only, one-directory-at-a-time filesystem browsing for the manual launcher picker."""
from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Collection, Mapping

from .i18n import t as tr


@dataclass(frozen=True)
class Entry:
    path: Path
    is_dir: bool
    root_selector: bool = False
    parent_selector: bool = False
    location_selector: bool = False
    detail: str = ""  # shown beside the name: the launcher a file belongs to, or a drive's volume name
    launcher: bool = False  # a file CouchDoom recognizes as a launcher or its settings

    @property
    def display_name(self) -> str:
        if self.parent_selector:
            if self.location_selector:
                return tr("browser.drives_home")
            return tr("browser.parent")
        if self.root_selector:
            if self.path == Path.home():
                return tr("browser.home", path=self.path)
            return str(self.path)
        return self.path.name


def _windows_roots() -> list[Path]:
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return _drive_roots(mask)


def _drive_roots(mask: int) -> list[Path]:
    return [Path(f"{chr(65 + i)}:/") for i in range(26) if mask & (1 << i)]


DRIVE_REMOTE = 4
SEM_FAILCRITICALERRORS = 0x0001


def volume_label(root: Path) -> str:
    """A Windows drive's name ("Games"), or "" when it has none or asking could stall. Network drives are
    skipped because a disconnected share can block for seconds; empty card readers fail without a dialog."""
    if os.name != "nt":
        return ""
    try:
        kernel32 = ctypes.windll.kernel32
        if kernel32.GetDriveTypeW(str(root)) == DRIVE_REMOTE:
            return ""
        previous = kernel32.SetErrorMode(SEM_FAILCRITICALERRORS)
        try:
            buffer = ctypes.create_unicode_buffer(261)
            ok = kernel32.GetVolumeInformationW(str(root), buffer, len(buffer), None, None, None, None, 0)
        finally:
            kernel32.SetErrorMode(previous)
        return buffer.value if ok else ""
    except (AttributeError, OSError):
        return ""


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
    include: Callable[[os.DirEntry], bool] | None = None,
    labels: Mapping[str, str] | None = None,
) -> list[Entry]:
    """List child directories and matching files without recursing.

    Directory symlinks count as directories so linked game folders can be entered; `.app` bundles stay files.
    Dot entries are hidden unless `show_all`, and `include` adds entries matched by something other than name.
    `labels` maps file names or suffixes (casefolded) to the launcher they belong to; those files come first,
    since finding one is the point of browsing.
    """
    wanted_names = {name.casefold() for name in names}
    wanted_suffixes = {suffix.casefold() for suffix in suffixes}
    labels = {key.casefold(): value for key, value in (labels or {}).items()}
    if app_bundles:
        wanted_suffixes.add(".app")
    entries: list[Entry] = []
    try:
        with os.scandir(directory) as scan:
            for item in scan:
                if item.name.startswith(".") and not show_all:
                    continue
                try:
                    is_bundle = app_bundles and item.name.casefold().endswith(".app") and item.is_dir(follow_symlinks=False)
                    is_dir = item.is_dir(follow_symlinks=True) and not is_bundle
                    is_file = is_bundle or item.is_file(follow_symlinks=True)
                    extra = bool(include and include(item))
                    if is_dir or extra or (is_file and (show_all or item.name.casefold() in wanted_names
                                                        or Path(item.name).suffix.casefold() in wanted_suffixes)):
                        label = "" if is_dir else labels.get(item.name.casefold()) or labels.get(Path(item.name).suffix.casefold(), "")
                        entries.append(Entry(Path(item.path), is_dir, detail=label, launcher=bool(label)))
                except OSError:
                    continue
    except OSError:
        return []
    return sorted(entries, key=lambda e: (not e.launcher, not e.is_dir, e.path.name.casefold(), e.path.name))


class Browser:
    """Small navigation state model; UI code decides how actions and rows are presented."""

    def __init__(self, home: Path | None = None, *, candidates: Collection[Path] | None = None,
                 names: Collection[str] = (), suffixes: Collection[str] = (".zdl",),
                 app_bundles: bool = sys.platform == "darwin",
                 include: Callable[[os.DirEntry], bool] | None = None,
                 start: Path | None = None,
                 labels: Mapping[str, str] | None = None,
                 volume_label: Callable[[Path], str] = volume_label):
        self.roots = roots(home, candidates=candidates)
        self.labels = dict(labels or {})
        self._volume_label = volume_label
        self._volumes: dict[Path, str] = {}  # asked once per browser: a slow drive should only cost once
        if start is not None and Path(start).is_dir():
            start = Path(start)
            self.directory = start
        else:
            self.directory = self.roots[0]
        self.selecting_root = parent(self.directory) is None
        self.names, self.suffixes = tuple(names), tuple(suffixes)
        self.app_bundles = app_bundles
        self.include = include
        self.show_all = False
        self.selected = 0
        self.entries: list[Entry] = []
        self.refresh()
        if self.selecting_root:
            self.selected = next((i for i, entry in enumerate(self.entries) if entry.path == self.directory), 0)

    def refresh(self) -> None:
        if self.selecting_root:
            self.entries = [Entry(root, True, root_selector=True, detail=self._volume(root)) for root in self.roots]
        else:
            self.entries = list_entries(self.directory, show_all=self.show_all, names=self.names, suffixes=self.suffixes,
                                        app_bundles=self.app_bundles, include=self.include, labels=self.labels)
            above = parent(self.directory)
            if above is None:
                self.entries.insert(0, Entry(self.directory, True, parent_selector=True, location_selector=True))
            else:
                self.entries.insert(0, Entry(above, True, parent_selector=True))
        self.selected = max(0, min(self.selected, len(self.entries) - 1))

    def _volume(self, root: Path) -> str:
        if root == Path.home():
            return ""
        if root not in self._volumes:
            self._volumes[root] = self._volume_label(root)
        return self._volumes[root]

    @property
    def empty(self) -> bool:
        """Inside a folder with nothing to open but the way back up."""
        return not self.selecting_root and all(entry.parent_selector for entry in self.entries)

    def move(self, amount: int, *, wrap: bool = True) -> None:
        if self.entries:
            target = self.selected + amount
            self.selected = target % len(self.entries) if wrap else max(0, min(len(self.entries) - 1, target))

    def toggle_all(self) -> None:
        self.show_all = not self.show_all
        self.selected = 0
        self.refresh()

    def open_selected(self) -> Path | None:
        if not self.entries:
            return None
        entry = self.entries[self.selected]
        if entry.root_selector or entry.parent_selector:
            return None
        if entry.is_dir:
            self.directory = entry.path
            self.selected = 0
            self.refresh()
            return None
        return entry.path

    def back(self) -> bool:
        if self.selecting_root:
            return False
        above = parent(self.directory)
        if above is None:
            self.selecting_root = True
            self.refresh()
            self.selected = next((i for i, e in enumerate(self.entries) if e.path == self.directory), 0)
            return True
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

    def select_root(self, root: Path) -> None:
        root = Path(root)
        if root not in self.roots:
            return
        self.directory = root
        self.selecting_root = False
        self.selected = 0
        self.refresh()
