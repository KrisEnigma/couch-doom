import pygame

from couch_doom import ui
from couch_doom.ui import App

ART = (10, 120, 200)
MARK = (250, 250, 0)


def wipe_app(ready_after_polls: int | None, dims=None):
    """An App with just what the launch transition touches. The backdrop becomes ready after
    `ready_after_polls` polls (None: at once), standing in for HD art that's slow to build."""
    pygame.init()
    app = App.__new__(App)
    app.w, app.h, app.s = 640, 360, 0.5
    app.screen = pygame.Surface((app.w, app.h))
    app.art_rect = pygame.Rect(320, 0, 320, 259)
    app._draw = lambda now: app.screen.fill((90, 90, 90))
    frames: list[pygame.Surface] = []
    app._flip = lambda: frames.append(app.screen.copy())
    backdrop = pygame.Surface((app.w, app.h))
    backdrop.fill(ART)
    polls = []

    def poll():
        polls.append(1)
        return (backdrop, dims, None) if ready_after_polls is None or len(polls) > ready_after_polls else None

    app._start_loading_backdrop = lambda: poll
    app._loading_screen = lambda name, art=None: (art, (0, 0))
    return app, frames


def test_transition_ends_on_the_loading_screen():
    app, frames = wipe_app(None)

    app._play_wipe("Game")

    assert frames[-1].get_at((0, app.h - 1))[:3] == ART
    assert frames[-1].get_at((app.w - 1, 0))[:3] == ART


def test_transition_shades_the_list_until_slow_art_is_ready(monkeypatch):
    monkeypatch.setattr(ui, "LAUNCH_WIPE_SECONDS", 0.05)
    app, frames = wipe_app(ready_after_polls=40)  # far more polls than the transition's own length

    app._play_wipe("Game")

    waiting = [f for f in frames[:-1] if f.get_at((app.w // 2, app.h // 2))[:3] != ART]
    assert len(waiting) > 3  # it kept drawing while the art was built, instead of freezing
    shade = [f.get_at((10, 10))[0] for f in waiting]
    assert shade == sorted(shade, reverse=True) and shade[-1] < 90  # the list darkens, never brightens back
    assert frames[-1].get_at((app.w // 2, app.h // 2))[:3] == ART


def test_transition_gives_up_on_art_that_never_arrives(monkeypatch):
    monkeypatch.setattr(ui, "LAUNCH_WIPE_SECONDS", 0.05)
    monkeypatch.setattr(ui, "LAUNCH_ART_WAIT_SECONDS", 0.1)
    app, frames = wipe_app(ready_after_polls=10**9)  # a cold unpack on a slow drive
    plain = pygame.Surface((app.w, app.h))
    plain.fill(MARK)
    app._plain_backdrop = lambda: plain

    app._play_wipe("Game")

    assert frames[-1].get_at((app.w // 2, app.h // 2))[:3] == MARK


def test_zoom_starts_with_the_art_where_the_panel_shows_it():
    pygame.init()
    app = App.__new__(App)
    app.w, app.h, app.s = 640, 360, 0.5
    app.screen = pygame.Surface((app.w, app.h))
    app.art_rect = pygame.Rect(320, 0, 320, 259)
    dims = (320, 200, 1.2)
    (s0, x0, y0), (s1, x1, y1) = app._zoom_path(dims)
    u, v = 200, 90  # a point of the art, in its own pixels
    backdrop = pygame.Surface((app.w, app.h))
    backdrop.fill(ART)
    backdrop.fill(MARK, (round(x1 + s1 * u) - 4, round(y1 + s1 * 1.2 * v) - 4, 9, 9))

    app._blit_zoomed(backdrop, app._zoom_path(dims), 0.0, app.screen.get_rect(), 1.0)

    assert app.screen.get_at((round(x0 + s0 * u), round(y0 + s0 * 1.2 * v)))[:3] == MARK
    app._blit_zoomed(backdrop, app._zoom_path(dims), 1.0, app.screen.get_rect(), 1.0)
    assert app.screen.get_at((round(x1 + s1 * u), round(y1 + s1 * 1.2 * v)))[:3] == MARK
