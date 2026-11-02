from types import SimpleNamespace

import pygame

from couch_doom import ui
from couch_doom.ui import App

ACCENT = (200, 40, 30)
ART = (10, 120, 200)


def wipe_app(ready_after_frames: int | None):
    """An App with just what the wipe touches. The backdrop becomes ready after `ready_after_frames`
    flips (None: before the first frame), standing in for HD art that's slow to build."""
    pygame.init()
    app = App.__new__(App)
    app.w, app.h, app.s = 320, 180, 0.25
    app.screen = pygame.Surface((app.w, app.h))
    app.theme = SimpleNamespace(accent=ACCENT)
    app._draw = lambda now: app.screen.fill((0, 0, 0))
    frames: list[pygame.Surface] = []
    app._flip = lambda: frames.append(app.screen.copy())
    backdrop = pygame.Surface((app.w, app.h))
    backdrop.fill(ART)
    app._start_loading_backdrop = lambda: (
        lambda: backdrop if ready_after_frames is None or len(frames) >= ready_after_frames else None)
    app._loading_screen = lambda name, art=None: (art, (0, 0))
    return app, frames


def test_wipe_uncovers_the_art_when_its_ready_from_the_start():
    app, frames = wipe_app(None)

    app._play_wipe("Game")

    assert frames[len(frames) // 2].get_at((0, app.h // 2))[:3] == ART
    assert frames[-1].get_at((app.w - 1, 0))[:3] == ART


def test_wipe_shows_accent_until_slow_art_is_ready_then_ends_on_the_art(monkeypatch):
    monkeypatch.setattr(ui, "LAUNCH_WIPE_SECONDS", 0.3)
    app, frames = wipe_app(ready_after_frames=6)

    app._play_wipe("Game")

    # Before the art exists, the blade uncovers plain accent instead of a half-drawn screen.
    assert frames[3].get_at((0, app.h // 2))[:3] == ACCENT
    assert frames[-1].get_at((app.w // 2, app.h // 2))[:3] == ART


def test_wipe_waits_for_art_that_finishes_after_the_sweep(monkeypatch):
    monkeypatch.setattr(ui, "LAUNCH_WIPE_SECONDS", 0.05)
    app, frames = wipe_app(ready_after_frames=10_000)
    calls = []
    ready = pygame.Surface((app.w, app.h))
    ready.fill(ART)

    def poll():
        calls.append(1)
        return ready if len(calls) > 40 else None  # far more polls than the sweep's few frames
    app._start_loading_backdrop = lambda: poll

    app._play_wipe("Game")

    assert all(frame.get_at((0, app.h // 2))[:3] != ART for frame in frames[:-1])
    assert frames[-1].get_at((app.w // 2, app.h // 2))[:3] == ART
