from __future__ import annotations

import json
from pathlib import Path

from . import log
from .i18n import LANGUAGE_CODES, detect_system_language
from .theme import MANUAL_PALETTE_KEYS

HISTORY_LIMIT = 10


class State:
    def __init__(self, path: Path):
        self.path = path
        self.last_played: str | None = None
        self.history: list[str] = []
        self.music = True
        self.menu_sounds = True
        self.recent_group = False
        self.favorites: list[str] = []
        self.launcher: tuple[str, str] | None = None  # (source key, settings path) the player last picked
        self.added: list[tuple[str, str]] = []  # launchers dropped onto the window, kept for the picker
        self.color_palette = "auto"  # app-wide Colors choice; automatic keeps art-derived themes
        self.language = "en"
        self.language_source = "auto"  # "auto" (detected from the OS) or "menu" (picked by the player)
        self.update_check = True  # set false in the file to never contact GitHub
        self.update_skip: str | None = None  # a release the player said not to be reminded about
        self.seen_version: str | None = None  # the last CouchDoom version that ran with this file
        self.returning = False  # a settings file already existed: not a first run
        self._load()

    def _load(self) -> None:
        data: dict = {}
        unreadable = False
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            unreadable = True
        if not isinstance(data, dict):
            data, unreadable = {}, True
        self.returning = bool(data) or unreadable
        if data:
            self.last_played = data.get("last_played")
            self.history = list(data.get("history") or [])
            self.music = bool(data.get("music", True))
            self.menu_sounds = bool(data.get("menu_sounds", True))
            self.recent_group = bool(data.get("recent_group", False))
            self.favorites = [f for f in data.get("favorites") or [] if isinstance(f, str)]
            if (pick := _pair(data.get("launcher"))) is not None:
                self.launcher = pick
            self.added = [p for item in data.get("added_launchers") or [] if (p := _pair(item)) is not None]
            palette = data.get("color_palette", "auto")
            self.color_palette = palette if isinstance(palette, str) and palette in MANUAL_PALETTE_KEYS else "auto"
            self.update_check = bool(data.get("update_check", True))
            skip = data.get("update_skip")
            self.update_skip = skip if isinstance(skip, str) else None
            seen = data.get("seen_version")
            self.seen_version = seen if isinstance(seen, str) else None
        lang = data.get("language")
        source = data.get("language_source")
        if source in ("auto", "menu"):
            self.language_source = source
        # 1.2.0 saved its detection without a source, and its Windows detection always said "en";
        # treat that one value as undecided so those players get detected properly once.
        if isinstance(lang, str) and lang in LANGUAGE_CODES and (source in ("auto", "menu") or lang != "en"):
            self.language = lang
        elif "language" in data and lang != "en":
            self.language = "en"  # an unknown code typed into the file; English until they pick one
        else:
            # First run, a pre-1.2 file, or 1.2.0's undecided "en": stick the OS locale so the menu starts there.
            # A damaged file is left for the player to recover until they change a setting.
            self.language = detect_system_language()
            self.language_source = "auto"
            if not unreadable:
                self._save()  # if this can't be written, detection simply runs again next launch

    def skip_update(self, version: str) -> None:
        self.update_skip = version
        self._save()

    def set_seen_version(self, version: str) -> None:
        self.seen_version = version
        self._save()

    def record(self, preset_name: str) -> None:
        self.last_played = preset_name
        self.history = [preset_name, *(h for h in self.history if h != preset_name)][:HISTORY_LIMIT]
        self._save()

    def set_music(self, on: bool) -> None:
        self.music = on
        self._save()

    def set_menu_sounds(self, on: bool) -> None:
        self.menu_sounds = on
        self._save()

    def set_recent_group(self, on: bool) -> None:
        self.recent_group = on
        self._save()

    def set_color_palette(self, palette: str) -> None:
        self.color_palette = palette if palette in MANUAL_PALETTE_KEYS else "auto"
        self._save()

    def set_language(self, code: str) -> None:
        self.language = code if code in LANGUAGE_CODES else "en"
        self.language_source = "menu"
        self._save()

    def set_launcher(self, key: str, path: str, added: bool = False) -> None:
        self.launcher = (key, path)
        if added and (key, path) not in self.added:
            self.added.append((key, path))
        self._save()

    def toggle_favorite(self, preset_name: str) -> bool:
        """Returns True if the preset is a favorite afterwards."""
        on = preset_name not in self.favorites
        if on:
            self.favorites.append(preset_name)
        else:
            self.favorites.remove(preset_name)
        self._save()
        return on

    def _save(self) -> None:
        """Never raises: antivirus or a sync client briefly holding the file (or a read-only folder) must not
        crash a favorite toggle. The change still applies for this session."""
        tmp = self.path.with_suffix(".tmp")
        data = {
            "last_played": self.last_played,
            "history": self.history,
            "music": self.music,
            "menu_sounds": self.menu_sounds,
            "recent_group": self.recent_group,
            "favorites": self.favorites,
            "launcher": {"source": self.launcher[0], "path": self.launcher[1]} if self.launcher else None,
            "added_launchers": [{"source": k, "path": p} for k, p in self.added],
            "color_palette": self.color_palette,
            "language": self.language,
            "language_source": self.language_source,
            "update_check": self.update_check,
            "update_skip": self.update_skip,
            "seen_version": self.seen_version,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            log.write("settings not saved", f"{self.path}: {exc}")


def _pair(item) -> tuple[str, str] | None:
    if isinstance(item, dict) and isinstance(item.get("source"), str) and isinstance(item.get("path"), str):
        return item["source"], item["path"]
    return None
