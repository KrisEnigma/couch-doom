"""Retake the README screenshots from your own launcher library.

Run from a source checkout: PYTHONPATH=src python packaging/readme_screenshots.py [--only FILE ...] [--out DIR]

Shots are listed in packaging/readme-screenshots.json by preset or category name, so they only come out as
intended with a library that has those games. Each one starts from the plain list. The app draws into a hidden
window with controller prompts and no audio; your saved state (favorites, last played, settings) is put back
afterwards. Pick games whose art gives the gallery different colours.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from pathlib import Path, PureWindowsPath

os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["COUCHDOOM_NO_UPDATE_CHECK"] = "1"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame

from couch_doom import config, gamepad, ui
from couch_doom.config import STATE_FILE
from couch_doom.gamepad import Action
from couch_doom.i18n import set_language
from couch_doom.launchers import Launchers
from couch_doom.state import State
from couch_doom.ui import App

ROOT = Path(__file__).resolve().parent.parent
CONFIG = Path(__file__).with_name("readme-screenshots.json")

for _cls in vars(gamepad).values():
    if isinstance(_cls, type) and isinstance(getattr(_cls, "pad_mode", None), property):
        _cls.pad_mode = property(lambda self: True)
        _cls.family = property(lambda self: "xbox")


class ShownChoice:
    """A picker row that displays a stand-in path, so screenshots don't publish the author's folders."""

    def __init__(self, choice, path: str):
        self.choice, self.path = choice, PureWindowsPath(path)
        self.id, self.name, self.source = choice.id, choice.name, choice.source


def make_app(render_size: tuple[int, int], language: str) -> App:
    def create_window(self) -> None:
        self.window, self.dpi = None, 1.0
        self.screen = pygame.display.set_mode(render_size, pygame.HIDDEN)
        self._layout()

    App._create_window = create_window
    ui._force_foreground = lambda: None
    state = State(STATE_FILE)
    state.music = state.menu_sounds = False  # no title music renders between shots
    state.recent_group = False
    set_language(language)
    launchers = Launchers(state)
    launchers.startup()
    app = App(launchers.load(), state, windowed=True, launchers=launchers)
    app.collapsed_sections = set()
    app._rebuild_rows()
    return app


def settle(app: App, seconds: float) -> None:
    clock = pygame.time.Clock()
    last = time.monotonic()
    end = last + seconds
    while (now := time.monotonic()) < end:
        pygame.event.pump()
        app.tick(now, now - last)
        last = now
        app._draw(now)
        clock.tick(60)


def select_preset(app: App, name: str) -> None:
    index = next(i for i, p in enumerate(app.opts.presets) if p.name == name)
    app._select_row(next(r for r, row in enumerate(app.rows) if row.kind == "preset" and row.preset == index and not row.fav))
    end = time.monotonic() + 8.0
    while time.monotonic() < end and not (app.current in app.art_cache and app.current in app.readmes):
        settle(app, 0.25)
    settle(app, 1.6)  # art crossfade, detail slide and theme blend


def take(app: App, shot: dict, picker_paths: dict[str, str]) -> None:
    now = time.monotonic
    app.mode = "list"
    app._set_filter(shot.get("search", ""))
    if "category" in shot:
        app._select_row(next(r for r, row in enumerate(app.rows) if row.kind == "header" and row.text == shot["category"]))
        settle(app, 2.0)
        return
    select_preset(app, shot["preset"])
    screen = shot.get("screen")
    if "search" in shot:
        app._open_search(now())
    elif screen == "menu":
        app.state.music = app.state.menu_sounds = True  # show the defaults; audio is the dummy driver
        app._on_action(Action.MENU, now())
    elif screen in ("readme", "endoom"):
        app._open_info(now())
        if screen == "endoom":
            settle(app, 0.3)
            app._on_action(Action.NEXT_SECTION, now())
    elif screen == "picker":
        for choice in app.launchers.choices:
            app.launchers.preview(choice)  # the preset counts beside each launcher
        app._open_picker()
        app.picker = [ShownChoice(c, picker_paths.get(c.source.key, str(c.path))) for c in app.launchers.choices] + [None]
    elif screen == "loading":
        name = app.opts.presets[app.current].name
        backdrop = app._loading_backdrop(app.current, app._layers_for(app.theme)["bg"][0])[0]
        app._loading_screen(name, backdrop)
        app._draw_loading(name, 1.6)
        return
    settle(app, 1.0)
    if screen == "menu":
        app.state.music = app.state.menu_sounds = False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="+", metavar="FILE", help="Retake just these files")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "screenshots")
    args = ap.parse_args()
    plan = json.loads(CONFIG.read_text(encoding="utf-8"))
    shots = [s for s in plan["shots"] if not args.only or s["file"] in args.only]

    backup = Path(tempfile.mkdtemp(prefix="couchdoom-shots-")) / "state"
    shutil.copytree(config.STATE_DIR, backup)
    try:
        pygame.init()
        app = make_app(tuple(plan["render_size"]), plan["language"])
        args.out.mkdir(parents=True, exist_ok=True)
        for shot in shots:
            take(app, shot, plan["picker_paths"])
            path = args.out / shot["file"]
            pygame.image.save(pygame.transform.smoothscale(app.screen, tuple(plan["save_size"])), str(path))
            print("saved", path)
    finally:
        pygame.quit()
        shutil.rmtree(config.STATE_DIR, ignore_errors=True)
        shutil.copytree(backup, config.STATE_DIR)
        shutil.rmtree(backup.parent, ignore_errors=True)


if __name__ == "__main__":
    main()
