from __future__ import annotations

import json
from pathlib import Path

HISTORY_LIMIT = 10


class State:
    def __init__(self, path: Path):
        self.path = path
        self.last_played: str | None = None
        self.history: list[str] = []
        self.music = True
        self.favorites: list[str] = []
        self.launcher: tuple[str, str] | None = None  # (source key, settings path) the player last picked
        self.added: list[tuple[str, str]] = []  # launchers dropped onto the window, kept for the picker
        self.update_check = True  # set false in the file to never contact GitHub
        self.update_skip: str | None = None  # a release the player said not to be reminded about
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.last_played = data.get("last_played")
        self.history = list(data.get("history") or [])
        self.music = bool(data.get("music", True))
        self.favorites = [f for f in data.get("favorites") or [] if isinstance(f, str)]
        if (pick := _pair(data.get("launcher"))) is not None:
            self.launcher = pick
        self.added = [p for item in data.get("added_launchers") or [] if (p := _pair(item)) is not None]
        self.update_check = bool(data.get("update_check", True))
        skip = data.get("update_skip")
        self.update_skip = skip if isinstance(skip, str) else None

    def skip_update(self, version: str) -> None:
        self.update_skip = version
        self._save()

    def record(self, preset_name: str) -> None:
        self.last_played = preset_name
        self.history = [preset_name, *(h for h in self.history if h != preset_name)][:HISTORY_LIMIT]
        self._save()

    def set_music(self, on: bool) -> None:
        self.music = on
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        data = {
            "last_played": self.last_played,
            "history": self.history,
            "music": self.music,
            "favorites": self.favorites,
            "launcher": {"source": self.launcher[0], "path": self.launcher[1]} if self.launcher else None,
            "added_launchers": [{"source": k, "path": p} for k, p in self.added],
            "update_check": self.update_check,
            "update_skip": self.update_skip,
        }
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)


def _pair(item) -> tuple[str, str] | None:
    if isinstance(item, dict) and isinstance(item.get("source"), str) and isinstance(item.get("path"), str):
        return item["source"], item["path"]
    return None
