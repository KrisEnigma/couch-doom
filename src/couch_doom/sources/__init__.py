"""Launchers CouchDoom reads presets from. Each turns its own settings into the same Options."""
from __future__ import annotations

import configparser
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from .. import shortcuts
from ..options import Options, OptionsError
from . import doomlauncher, doomlauncher667, doomrunner, gzdoom, zdl


@dataclass(frozen=True)
class Source:
    key: str
    module: ModuleType

    @property
    def name(self) -> str:
        return self.module.NAME


# Auto-detection order: the first launcher whose settings file exists wins. A bare source port comes last:
# its "settings file" is the port itself, listing the IWADs it would offer.
SOURCES = [Source("doomrunner", doomrunner), Source("zdl", zdl), Source("doomlauncher", doomlauncher),
           Source("doomlauncher667", doomlauncher667), Source("gzdoom", gzdoom)]
KEYS = [s.key for s in SOURCES]
BY_KEY = {s.key: s for s in SOURCES}


@dataclass(frozen=True)
class Choice:
    """One launcher's settings file, as the player picks between them."""
    source: Source
    path: Path

    @property
    def id(self) -> str:
        return os.path.normcase(os.path.abspath(self.path))

    @property
    def name(self) -> str:
        label = getattr(self.source.module, "label", None)
        return label(self.path) if label else self.source.name


def plan(cli_path: str | None, launcher: str | None) -> list[tuple[Source, Path]]:
    """Every (launcher, settings file) worth trying, in order. An explicit path is the only candidate:
    silently falling back to a different setup would be more confusing than an error."""
    sources = [s for s in SOURCES if not launcher or s.key == launcher]
    if cli_path:
        path = Path(cli_path)
        return [(next((s for s in sources if s.module.matches(path)), sources[0]), path)]
    return [(s, p) for s in sources for p in s.module.candidates()]


def _beside(source: Source, folder: Path) -> Path | None:
    if hook := getattr(source.module, "beside", None):
        return hook(folder)
    # Both Doom Launchers use DoomLauncher.sqlite, so the file's contents decide whose it is.
    return next((p for n in source.module.SETTINGS_NAMES if (p := folder / n).is_file() and source.module.matches(p)), None)


def _is_exe(source: Source, name: str) -> bool:
    if name in source.module.EXES:
        return True
    # AppImages carry the version in the name: DoomRunner-1.9.2-Linux-x86_64.AppImage
    stem = name.removesuffix(".appimage")
    return stem != name and any(stem.split("-")[0] == e for e in source.module.EXES)


def identify(path: Path) -> Choice | None:
    """What a dropped file or folder points at: a launcher's exe, its folder, or a settings file itself."""
    if path.is_dir():
        return next((Choice(s, p) for s in SOURCES if (p := _beside(s, path))), None)
    name = path.name.lower()
    for s in SOURCES:
        if _is_exe(s, name):
            if s.module.matches(path):
                return Choice(s, path)  # a source port is its own settings file
            # Portable builds keep settings beside the exe; installed ones in the user's app data.
            p = _beside(s, path.parent) or next((c for c in s.module.candidates() if c.is_file() and s.module.matches(c)), None)
            return Choice(s, p) if p else None
    if path.is_file():
        return next((Choice(s, path) for s in SOURCES if s.module.matches(path)), None)
    return None


def discover(remembered: list[Choice] = (), only: str | None = None) -> list[Choice]:
    """Every launcher setup on this PC: usual settings locations, launchers the user has shortcuts to,
    and ones dropped onto CouchDoom before."""
    sources = [s for s in SOURCES if not only or s.key == only]
    found: dict[str, Choice] = {}

    def add(c: Choice | None) -> None:
        if c and c.source in sources and c.path.is_file() and c.source.module.matches(c.path):
            found.setdefault(c.id, c)

    for s in sources:
        for p in s.module.candidates():
            add(Choice(s, p))
    for target in shortcuts.targets({e for s in sources for e in s.module.EXES}):
        add(identify(target))
    for c in remembered:
        add(c)
    return list(found.values())


def _names(sources: list[Source]) -> str:
    names = list(dict.fromkeys(s.name for s in sources))
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def load_choice(choice: Choice) -> Options:
    source, path = choice.source, choice.path
    for attempt in range(2):
        try:
            return source.module.load(path)
        except (OSError, ValueError, AttributeError, TypeError, KeyError, IndexError, configparser.Error, sqlite3.Error) as exc:
            if attempt == 0:
                time.sleep(0.4)  # the launcher may be mid-save; a second read usually gets the finished file
                continue
            raise OptionsError(f"{source.name}'s settings couldn't be read", f"{type(exc).__name__}: {exc}", [path], source.name) from exc
    raise AssertionError("unreachable")


def find_and_load(tried: list[tuple[Source, Path]]) -> Options:
    hit = next(((s, p) for s, p in tried if p.is_file()), None)
    if hit is None:
        sources = [s for s, _ in tried]
        raise OptionsError("No launcher settings found", f"Looked for {_names(sources)} settings here:", [p for _, p in tried])
    return load_choice(Choice(*hit))


def not_found(choices_looked: list[tuple[Source, Path]]) -> OptionsError:
    sources = list(dict.fromkeys(s for s, _ in choices_looked)) or SOURCES
    return OptionsError("No launcher settings found", f"Looked for {_names(sources)} settings here:",
                        [p for _, p in choices_looked])
