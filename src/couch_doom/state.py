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

    def record(self, preset_name: str) -> None:
        self.last_played = preset_name
        self.history = [preset_name, *(h for h in self.history if h != preset_name)][:HISTORY_LIMIT]
        self._save()

    def set_music(self, on: bool) -> None:
        self.music = on
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
        data = {"last_played": self.last_played, "history": self.history, "music": self.music, "favorites": self.favorites}
        tmp.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)
