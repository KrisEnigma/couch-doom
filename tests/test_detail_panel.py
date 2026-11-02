import pygame

from couch_doom import i18n
from couch_doom.ui import App


def _app():
    app = App.__new__(App)
    app._detail_panel = None
    return app


def test_detail_panel_is_reused_until_what_it_shows_changes():
    app = _app()
    builds = []

    def build():
        builds.append(1)
        return pygame.Surface((4, 4), pygame.SRCALPHA)

    preset, readme = object(), object()
    first = app._cached_detail_panel((preset, readme), (True, (1, 2, 3)), build)
    assert app._cached_detail_panel((preset, readme), (True, (1, 2, 3)), build) is first
    assert len(builds) == 1

    app._cached_detail_panel((preset, object()), (True, (1, 2, 3)), build)  # a readme arrived
    app._cached_detail_panel((preset, readme), (True, (1, 2, 3)), build)  # back to the first preset
    app._cached_detail_panel((preset, readme), (False, (1, 2, 3)), build)  # the logo decision landed
    assert len(builds) == 4


def test_overflowing_meta_line_reports_the_rest_in_the_current_language():
    pygame.font.init()
    font = pygame.font.Font(None, 20)
    app = _app()
    items = [f"item-{n}" for n in range(12)]
    i18n.set_language("es")
    lines = app._wrap_items(items, font, 120, 1)
    assert len(lines) == 1 and "más" in lines[0] and "more" not in lines[0]


def test_minimized_window_ticks_without_drawing(monkeypatch):
    app = App.__new__(App)
    app.running = True
    app.hidden = False
    app.quit_at = None
    app.ignore_until = 0.0
    app.mouse_on = False
    app.music = None
    app.update_pool = None

    class Pool:
        def shutdown(self, **_kwargs):
            pass

    app.art_pool = Pool()
    drawn, ticks = [], []

    class Input:
        def handle(self, event, now):
            return []

        def update(self, now):
            return []

    app.input = Input()
    app._draw = lambda now: drawn.append(now)
    app._flip = lambda: None
    app._close_window = lambda: None

    def tick(now, dt):
        ticks.append(now)
        if len(ticks) == 3:
            app.running = False

    app.tick = tick
    batches = [[pygame.event.Event(pygame.WINDOWMINIMIZED)], [], []]
    monkeypatch.setattr(pygame.event, "get", lambda: batches.pop(0) if batches else [])
    class Clock:
        def tick(self, fps=0):
            return 0

    monkeypatch.setattr(pygame.time, "Clock", Clock)
    monkeypatch.setattr(pygame, "quit", lambda: None)
    app.run()
    assert len(ticks) == 3 and drawn == []


def test_long_paths_keep_their_last_folders():
    pygame.font.init()
    font = pygame.font.Font(None, 20)
    path = r"C:\Users\someone\Games\Doom\Launchers\DoomRunner"
    fitted = App._fit_start(path, font, font.size("Launchers\\DoomRunner")[0] + font.size("…")[0] + 4)
    assert fitted.startswith("…") and fitted.endswith(r"Launchers\DoomRunner")
