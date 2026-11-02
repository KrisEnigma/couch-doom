from collections import OrderedDict
from concurrent.futures import Future

import pygame

from couch_doom import ui
from couch_doom.theme import HOUSE
from couch_doom.ui import App, Row


class ManualPool:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args):
        future = Future()
        self.jobs.append((future, fn, args))
        return future

    def complete_next(self):
        future, fn, args = self.jobs.pop(0)
        future.set_result(fn(*args))


def _completed_job(index: int) -> Future:
    job = Future()
    job.set_result((f"art-{index}", f"readme-{index}", f"endoom-{index}", f"logo-{index}"))
    return job


def test_art_preparation_runs_in_worker_and_only_for_the_selected_preset():
    app = App.__new__(App)
    app.current = 0
    app.art_jobs = OrderedDict((index, _completed_job(index)) for index in (0, 1, 2))
    app.art_render_jobs = {}
    app.logo_render_jobs = {}
    app.art_pool = ManualPool()
    app.art_cache = OrderedDict()
    app._theme_bgs = OrderedDict()
    app._theme_layers = OrderedDict()
    app.themes = {}
    app.logos = {}
    app.readmes = {}
    app.endooms = {}
    app.art_layers = []
    app.rows = [Row("preset", "Anything", 0)]
    app._category_selected = lambda: False
    app._neighbors = lambda: [1, 2]
    app._request_art = lambda _index: None
    layers = {"bg": ("background", (0, 0))}
    app._logo_surface = lambda logo: f"logo-{logo}"
    app._render_art = lambda art: (HOUSE, f"surface-{art}", f"background-{art}", layers)

    app._update_art(1.0)

    assert not app.art_cache
    assert list(app.art_render_jobs) == [0]
    assert app.art_jobs == {}
    assert len(app.art_pool.jobs) == 2

    app.art_pool.complete_next()
    app._update_art(1.1)

    assert app.logos[0] == "logo-logo-0"
    assert 0 in app.art_render_jobs

    app.art_pool.complete_next()
    app._update_art(1.2)

    assert list(app.art_cache) == [0]
    assert app.art_cache[0] == "surface-art-0"
    assert list(app.art_render_jobs) == []
    assert app._theme_layers[HOUSE.key] == layers


def test_logo_preparation_runs_separately_from_full_art_rendering():
    app = App.__new__(App)
    app.current = 0
    app.art_jobs = {0: _completed_job(0)}
    app.art_render_jobs = {}
    app.logo_render_jobs = {}
    app.art_pool = ManualPool()
    app.art_cache = OrderedDict()
    app._theme_bgs = OrderedDict()
    app._theme_layers = OrderedDict()
    app.themes = {}
    app.logos = {}
    app.readmes = {}
    app.endooms = {}
    app.art_layers = []
    app.rows = [Row("preset", "Anything", 0)]
    app._category_selected = lambda: False
    app._neighbors = lambda: []
    app._request_art = lambda _index: None
    app._render_art = lambda art: (HOUSE, f"surface-{art}", "background", {})
    app._logo_surface = lambda logo: f"surface-{logo}"

    app._update_art(1.0)

    assert list(app.art_render_jobs) == [0]
    assert list(app.logo_render_jobs) == [0]
    assert len(app.art_pool.jobs) == 2


def _cache_app(current: int):
    app = App.__new__(App)
    app.current = current
    app.art_cache = OrderedDict()
    app.logos, app.readmes, app.endooms, app.themes = {}, {}, {}, {}
    return app


def test_art_cache_evicts_extras_with_their_art(monkeypatch):
    monkeypatch.setattr(ui, "ART_CACHE_SIZE", 2)
    app = _cache_app(current=2)
    for idx in range(3):
        app.art_cache[idx] = None
        for extras in (app.logos, app.readmes, app.endooms, app.themes):
            extras[idx] = f"extra-{idx}"
    app.logos[9] = "logo of a preset whose render was cancelled"

    app._trim_art_cache()

    assert list(app.art_cache) == [1, 2]
    for extras in (app.logos, app.readmes, app.endooms, app.themes):
        assert sorted(extras) == [1, 2]


def test_art_cache_respects_its_byte_budget(monkeypatch):
    panel = pygame.Surface((100, 100))
    monkeypatch.setattr(ui, "ART_CACHE_BYTES", 2 * 100 * 100 * panel.get_bytesize())
    app = _cache_app(current=3)
    for idx in range(4):
        app.art_cache[idx] = panel.copy()

    app._trim_art_cache()

    assert list(app.art_cache) == [2, 3]


def test_art_cache_keeps_the_selected_art_even_over_budget(monkeypatch):
    monkeypatch.setattr(ui, "ART_CACHE_BYTES", 1)
    app = _cache_app(current=0)
    app.art_cache[0] = pygame.Surface((100, 100))

    app._trim_art_cache()

    assert list(app.art_cache) == [0]


def test_resize_drops_renders_sized_for_the_old_window():
    app = App.__new__(App)
    pending = Future()
    app.art_render_jobs = {0: pending}
    app.logo_render_jobs = {0: Future()}

    app._drop_sized_renders()

    assert app.art_render_jobs == {} and app.logo_render_jobs == {}
    assert pending.cancelled()


def test_title_text_fallback_waits_until_logo_detection_finishes():
    app = App.__new__(App)
    app.art_jobs = {0: object()}
    app.art_render_jobs = {}
    app.logo_render_jobs = {}
    app.logos = {}

    assert not app._should_show_title_text(0)

    app.art_jobs.clear()
    app.logo_render_jobs[0] = object()
    assert not app._should_show_title_text(0)

    app.logo_render_jobs.clear()
    app.logos[0] = None
    assert app._should_show_title_text(0)
