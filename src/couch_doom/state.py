from __future__ import annotations

import json
from configparser import ConfigParser
from pathlib import Path

from . import log
from .i18n import LANGUAGE_CODES, detect_system_language
from .theme import MANUAL_PALETTE_KEYS

HISTORY_LIMIT = 10

# Hand-edited settings. Comments are rewritten on every save so they stay up to date.
_INI_HEADER = """\
; CouchDoom settings. Lines that start with ; are comments.
; Delete a value (leave it blank) to clear it. true/false are case-insensitive.
"""


class State:
    def __init__(self, path: Path):
        self.path = path
        self.last_played: str | None = None
        self.history: list[str] = []
        self.music = True
        self.menu_sounds = True
        self.recent_group = False
        self.windowed = False  # last Alt+Enter or menu choice; fullscreen unless the player picked a window
        self.window_size: tuple[int, int] | None = None  # last dragged or snapped size; None keeps the default
        self.favorites: list[str] = []
        self.launcher: tuple[str, str] | None = None  # (source key, settings path) the player last picked
        self.added: list[tuple[str, str]] = []  # launchers dropped onto the window, kept for the picker
        self.color_palette = "auto"  # app-wide Colors choice; automatic keeps art-derived themes
        self.language = "en"
        self.language_source = "auto"  # "auto" (detected from the OS) or "menu" (picked by the player)
        self.update_check = True  # set false in the file to never contact GitHub
        self.update_skip: str | None = None  # a release the player said not to be reminded about
        self.seen_version: str | None = None  # the last CouchDoom version that ran with this file
        self.cache_dir: str | None = None  # optional art/music cache root; None uses the platform default
        self.returning = False  # a settings file already existed: not a first run
        self._load()

    def _load(self) -> None:
        data: dict = {}
        unreadable = False
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            text = None
        except OSError:
            text, unreadable = None, True
        if text is not None:
            try:
                data = _parse_settings(text)
            except ValueError:
                unreadable = True
                data = {}
        if not isinstance(data, dict):
            data, unreadable = {}, True
        self.returning = bool(data) or unreadable
        if data:
            self.last_played = data.get("last_played") or None
            self.history = list(data.get("history") or [])
            self.music = bool(data.get("music", True))
            self.menu_sounds = bool(data.get("menu_sounds", True))
            self.recent_group = bool(data.get("recent_group", False))
            self.windowed = data.get("windowed") is True
            self.window_size = _window_size(data.get("window_size"))
            self.favorites = [f for f in data.get("favorites") or [] if isinstance(f, str)]
            if (pick := _pair(data.get("launcher"))) is not None:
                self.launcher = pick
            self.added = [p for item in data.get("added_launchers") or [] if (p := _pair(item)) is not None]
            palette = data.get("color_palette", "auto")
            self.color_palette = palette if isinstance(palette, str) and palette in MANUAL_PALETTE_KEYS else "auto"
            self.update_check = bool(data.get("update_check", True))
            skip = data.get("update_skip")
            self.update_skip = skip if isinstance(skip, str) and skip else None
            seen = data.get("seen_version")
            self.seen_version = seen if isinstance(seen, str) and seen else None
            cache = data.get("cache_dir")
            self.cache_dir = cache if isinstance(cache, str) and cache.strip() else None
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

    def set_windowed(self, on: bool) -> None:
        self.windowed = on
        self._save()

    def set_window_size(self, size: tuple[int, int]) -> None:
        self.window_size = (int(size[0]), int(size[1]))
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
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        data = {
            "last_played": self.last_played,
            "history": self.history,
            "music": self.music,
            "menu_sounds": self.menu_sounds,
            "recent_group": self.recent_group,
            "windowed": self.windowed,
            "window_size": list(self.window_size) if self.window_size else None,
            "favorites": self.favorites,
            "launcher": {"source": self.launcher[0], "path": self.launcher[1]} if self.launcher else None,
            "added_launchers": [{"source": k, "path": p} for k, p in self.added],
            "color_palette": self.color_palette,
            "language": self.language,
            "language_source": self.language_source,
            "update_check": self.update_check,
            "update_skip": self.update_skip,
            "seen_version": self.seen_version,
            "cache_dir": self.cache_dir,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(dumps_settings(data), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            log.write("settings not saved", f"{self.path}: {exc}")


def adopt_legacy_json_settings(legacy: Path, dest: Path) -> None:
    """Convert last_played.json / settings.json into settings.ini, then remove the JSON file."""
    data = json.loads(legacy.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("legacy settings were not an object")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(dumps_settings(_normalize_loaded(data)), encoding="utf-8")
    legacy.unlink()


def dumps_settings(data: dict) -> str:
    """Write a commented INI players can edit by hand."""
    last_played = data.get("last_played") or ""
    history = _list_lines(data.get("history") or [])
    favorites = _list_lines(data.get("favorites") or [])
    window = data.get("window_size")
    width = window[0] if isinstance(window, (list, tuple)) and len(window) == 2 else ""
    height = window[1] if isinstance(window, (list, tuple)) and len(window) == 2 else ""
    launcher = data.get("launcher") if isinstance(data.get("launcher"), dict) else {}
    added_lines = []
    for item in data.get("added_launchers") or []:
        if isinstance(item, dict) and item.get("source") and item.get("path"):
            added_lines.append(f"{item['source']}|{item['path']}")
    added = _list_lines(added_lines)
    return (
        _INI_HEADER
        + "\n[general]\n"
        + _field("Last game you played.", "last_played", last_played)
        + _field("Title music while browsing.", "music", _bool(data.get("music", True)))
        + _field("Menu click sounds.", "menu_sounds", _bool(data.get("menu_sounds", True)))
        + _field("Show a Recently Played group at the top of the list.", "recent_group",
                 _bool(data.get("recent_group", False)))
        + _field("Start in a window instead of full screen.", "windowed", _bool(data.get("windowed", False)))
        + _field("Remembered window size (leave blank for the default).", "window_width", width)
        + _field(None, "window_height", height)
        + _field('Colors: "auto" follows each game\'s art, or lock one named palette.',
                 "color_palette", data.get("color_palette") or "auto")
        + _field("Interface language code (en, es, pt-BR, fr, de).", "language", data.get("language") or "en")
        + _field('"auto" = detected from the OS; "menu" = you picked it.',
                 "language_source", data.get("language_source") or "auto")
        + _field("Set to false to never check GitHub for updates.", "update_check",
                 _bool(data.get("update_check", True)))
        + _field("A release you asked not to be reminded about.", "update_skip", data.get("update_skip") or "")
        + _field("Last CouchDoom version that ran with this file (managed by the app).",
                 "seen_version", data.get("seen_version") or "")
        + _field(
            "Art and music cache folder. Leave blank for the default in your user folder, "
            "or set a path (relative to the CouchDoom folder, or absolute anywhere).",
            "cache_dir", data.get("cache_dir") or "")
        + "\n[history]\n"
        + _field("Recent games, newest first. One name per line.", "items", history)
        + "\n[favorites]\n"
        + _field("Favorite games. One name per line.", "items", favorites)
        + "\n[launcher]\n"
        + _field("Which launcher CouchDoom is showing.", "source", launcher.get("source") or "")
        + _field(None, "path", launcher.get("path") or "")
        + "\n[added_launchers]\n"
        + _field("Launchers you dropped onto the window. One source|path per line.", "items", added)
    )


def _parse_settings(text: str) -> dict:
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("settings JSON was not an object")
        return _normalize_loaded(data)
    parser = ConfigParser(interpolation=None)
    parser.optionxform = str  # keep key case
    try:
        parser.read_string(text)
    except Exception as exc:
        raise ValueError(f"settings INI could not be read: {exc}") from exc
    if not parser.sections():
        return {}
    general = parser["general"] if parser.has_section("general") else {}
    width = general.get("window_width", "").strip()
    height = general.get("window_height", "").strip()
    window_size = None
    if width.isdigit() and height.isdigit():
        window_size = [int(width), int(height)]
    source = parser["launcher"].get("source", "").strip() if parser.has_section("launcher") else ""
    path = parser["launcher"].get("path", "").strip() if parser.has_section("launcher") else ""
    launcher = {"source": source, "path": path} if source and path else None
    added = []
    if parser.has_section("added_launchers"):
        for line in _split_lines(parser["added_launchers"].get("items", "")):
            if "|" not in line:
                continue
            src, pth = line.split("|", 1)
            src, pth = src.strip(), pth.strip()
            if src and pth:
                added.append({"source": src, "path": pth})
    return _normalize_loaded({
        "last_played": general.get("last_played", "").strip() or None,
        "history": _split_lines(parser["history"].get("items", "") if parser.has_section("history") else ""),
        "music": _read_bool(general.get("music", "true"), True),
        "menu_sounds": _read_bool(general.get("menu_sounds", "true"), True),
        "recent_group": _read_bool(general.get("recent_group", "false"), False),
        "windowed": _read_bool(general.get("windowed", "false"), False),
        "window_size": window_size,
        "favorites": _split_lines(parser["favorites"].get("items", "") if parser.has_section("favorites") else ""),
        "launcher": launcher,
        "added_launchers": added,
        "color_palette": general.get("color_palette", "auto").strip() or "auto",
        "language": general.get("language", "en").strip() or "en",
        # Blank/missing keeps the 1.2.0 "undecided English" redetect path in State._load.
        "language_source": general.get("language_source", "").strip() or None,
        "update_check": _read_bool(general.get("update_check", "true"), True),
        "update_skip": general.get("update_skip", "").strip() or None,
        "seen_version": general.get("seen_version", "").strip() or None,
        "cache_dir": general.get("cache_dir", "").strip() or None,
    })


def _normalize_loaded(data: dict) -> dict:
    """Map a JSON-shaped dict (from a legacy file or tests) into the fields State expects."""
    last = data.get("last_played")
    return {
        "last_played": last if isinstance(last, str) and last else None,
        "history": [h for h in (data.get("history") or []) if isinstance(h, str)],
        "music": bool(data.get("music", True)),
        "menu_sounds": bool(data.get("menu_sounds", True)),
        "recent_group": bool(data.get("recent_group", False)),
        "windowed": data.get("windowed") is True,
        "window_size": data.get("window_size"),
        "favorites": [f for f in (data.get("favorites") or []) if isinstance(f, str)],
        "launcher": data.get("launcher"),
        "added_launchers": data.get("added_launchers") or [],
        "color_palette": data.get("color_palette", "auto"),
        "language": data.get("language", "en"),
        "language_source": data.get("language_source") if isinstance(data.get("language_source"), str) else None,
        "update_check": bool(data.get("update_check", True)),
        "update_skip": data.get("update_skip") if isinstance(data.get("update_skip"), str) else None,
        "seen_version": data.get("seen_version") if isinstance(data.get("seen_version"), str) else None,
        "cache_dir": data.get("cache_dir") if isinstance(data.get("cache_dir"), str) else None,
    }


def _field(comment: str | None, key: str, value) -> str:
    lines = []
    if comment:
        lines.append(f"; {comment}")
    if isinstance(value, str) and "\n" in value:
        lines.append(f"{key} =")
        for part in value.splitlines():
            lines.append(f"    {part}")
        lines.append("")
        return "\n".join(lines)
    lines.append(f"{key} = {value}")
    lines.append("")
    return "\n".join(lines)


def _list_lines(items: list[str]) -> str:
    return "\n".join(items)


def _split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _read_bool(value: str, default: bool) -> bool:
    text = (value or "").strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off"):
        return False
    return default


def _window_size(value) -> tuple[int, int] | None:
    """A saved width and height. Anything else, including a zero, is the default size."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    width, height = value
    if isinstance(width, bool) or isinstance(height, bool):
        return None
    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
        return None
    width, height = int(width), int(height)
    if width < 1 or height < 1:
        return None
    return (width, height)


def _pair(item) -> tuple[str, str] | None:
    if isinstance(item, dict) and isinstance(item.get("source"), str) and isinstance(item.get("path"), str):
        return item["source"], item["path"]
    return None
