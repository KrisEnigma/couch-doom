"""Which launcher's presets are on screen: the saved pick, the only one found, or the player's choice."""
from __future__ import annotations

from pathlib import Path

from .options import Options, OptionsError
from .sources import BY_KEY, Choice, discover, identify, load_choice, not_found, plan
from .state import State


class Launchers:
    def __init__(self, state: State, only: str | None = None, explicit: Choice | None = None):
        self.state = state
        self.only = only  # --launcher: the picker and auto-detection stay within it
        self.current = explicit
        self.choices: list[Choice] = []
        self._loaded: dict[str, Options | OptionsError] = {}

    def _saved(self, item: tuple[str, str] | None) -> Choice | None:
        if item is None or item[0] not in BY_KEY or (self.only and item[0] != self.only):
            return None
        return Choice(BY_KEY[item[0]], Path(item[1]))

    def refresh(self) -> list[Choice]:
        remembered = [c for item in self.state.added if (c := self._saved(item))]
        self.choices = discover(remembered, self.only)
        if self.current and self.current.id not in {c.id for c in self.choices}:
            self.choices.insert(0, self.current)
        self._loaded.clear()
        return self.choices

    def startup(self) -> Choice | None:
        """The launcher to open with, or None when the player has to pick (several found) or add one (none)."""
        if self.current is None:
            saved = self._saved(self.state.launcher)
            if saved and saved.path.is_file():
                self.current = saved
        self.refresh()
        if self.current is None and len(self.choices) == 1:
            self.current = self.choices[0]
        return self.current

    def preview(self, choice: Choice) -> Options | OptionsError:
        """Loaded once per picker visit so it can show preset counts; reused if that launcher is chosen."""
        if choice.id not in self._loaded:
            try:
                self._loaded[choice.id] = load_choice(choice)
            except OptionsError as exc:
                self._loaded[choice.id] = exc
        return self._loaded[choice.id]

    @property
    def must_pick(self) -> bool:
        return self.current is None and len(self.choices) > 1

    def pick_error(self) -> OptionsError:
        names = ", ".join(dict.fromkeys(c.source.name for c in self.choices))
        return OptionsError("Pick a launcher", f"CouchDoom found more than one launcher's settings ({names}):",
                            [c.path for c in self.choices], hint="Press A or Enter to choose. You can switch any time with {pick}.")

    def load(self) -> Options:
        if self.current is None:
            self.startup()  # nothing was found before: look again, the player may have set one up since
        if self.must_pick:
            raise self.pick_error()
        if self.current is None:
            raise not_found(plan(None, self.only))
        if not self.current.path.is_file():
            raise not_found([(self.current.source, self.current.path)])
        return load_choice(self.current)

    def choose(self, choice: Choice, added: bool = False) -> Options:
        result = self._loaded.pop(choice.id, None)
        opts = result if isinstance(result, Options) else load_choice(choice)
        self.current = choice
        self.state.set_launcher(choice.source.key, str(choice.path), added)
        return opts

    def add(self, path: Path) -> Choice | None:
        choice = identify(path)
        if choice and (self.only and choice.source.key != self.only):
            return None
        return choice
