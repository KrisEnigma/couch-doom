from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

import couch_doom.ui as ui
from couch_doom.theme import HOUSE


def test_releases_window_surface_before_destroying_window_and_display(monkeypatch):
    events = []
    app = ui.App.__new__(ui.App)
    app.screen = object()
    window = SimpleNamespace(destroy=lambda: events.append(("destroy", app.screen, app.window)))
    app.window = window
    monkeypatch.setattr(ui.pygame.display, "quit", lambda: events.append(("display-quit", app.screen, app.window)))

    app._close_window()

    assert events == [
        ("destroy", None, window),
        ("display-quit", None, None),
    ]
    assert app.screen is None
    assert app.window is None


def test_set_window_icon_is_applied_to_the_window(monkeypatch):
    calls = []
    monkeypatch.setattr(ui.pygame.image, "load", lambda path: "icon-surface")
    monkeypatch.setattr(ui.pygame.display, "set_icon", lambda surf: calls.append(("display", surf)))
    window = SimpleNamespace(set_icon=lambda surf: calls.append(("window", surf)))

    ui._set_window_icon(window)

    assert calls == [("display", "icon-surface"), ("window", "icon-surface")]


def test_refresh_rate_follows_the_display(monkeypatch):
    monkeypatch.setattr(ui.pygame.display, "get_current_refresh_rate", lambda: 144)
    assert ui.display_refresh_rate() == 144


def test_refresh_rate_falls_back_when_the_display_will_not_say(monkeypatch):
    monkeypatch.setattr(ui, "_macos_refresh_rate", lambda: 0)
    monkeypatch.setattr(ui.pygame.display, "get_current_refresh_rate", lambda: 0)
    assert ui.display_refresh_rate() == ui.FALLBACK_FPS

    def missing():
        raise ui.pygame.error("No open window")

    monkeypatch.setattr(ui.pygame.display, "get_current_refresh_rate", missing)
    assert ui.display_refresh_rate() == ui.FALLBACK_FPS


def test_pygame_window_on_mac_uses_the_display_rate(monkeypatch):
    # The Mac build's pygame.Window makes get_current_refresh_rate raise; the display's own rate must still count.
    def missing():
        raise ui.pygame.error("No open window")

    monkeypatch.setattr(ui.pygame.display, "get_current_refresh_rate", missing)
    monkeypatch.setattr(ui.sys, "platform", "darwin")
    monkeypatch.setattr(ui, "_macos_refresh_rate", lambda: 120)
    assert ui.display_refresh_rate() == 120


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_pygame_window_takes_the_fastest_desktop_rate(monkeypatch, platform):
    # A pygame.Window makes get_current_refresh_rate raise. The desktop rates are the only other source, and
    # guessing the highest is the safe side: see _desktop_refresh_rate.
    def missing():
        raise ui.pygame.error("No open window")

    monkeypatch.setattr(ui.pygame.display, "get_current_refresh_rate", missing)
    monkeypatch.setattr(ui.pygame.display, "get_desktop_refresh_rates", lambda: [60, 170, 0])
    monkeypatch.setattr(ui.sys, "platform", platform)
    assert ui.display_refresh_rate() == 170


def test_desktop_rates_that_are_all_zero_fall_back(monkeypatch):
    def missing():
        raise ui.pygame.error("No open window")

    monkeypatch.setattr(ui.pygame.display, "get_current_refresh_rate", missing)
    monkeypatch.setattr(ui.pygame.display, "get_desktop_refresh_rates", lambda: [0, 0])
    monkeypatch.setattr(ui.sys, "platform", "win32")
    assert ui.display_refresh_rate() == ui.FALLBACK_FPS


def test_windows_renders_through_direct3d11_when_it_exists(monkeypatch):
    drivers = [SimpleNamespace(name="direct3d"), SimpleNamespace(name="direct3d11"), SimpleNamespace(name="opengl")]
    monkeypatch.setattr(ui.canvas.video, "get_drivers", lambda: iter(drivers))
    monkeypatch.setattr(ui.canvas.sys, "platform", "win32")
    assert ui.canvas.driver_index() == 1


def test_renderer_keeps_sdl_choice_when_the_preferred_driver_is_missing(monkeypatch):
    monkeypatch.setattr(ui.canvas.video, "get_drivers", lambda: iter([SimpleNamespace(name="opengl")]))
    monkeypatch.setattr(ui.canvas.sys, "platform", "win32")
    assert ui.canvas.driver_index() == -1
    monkeypatch.setattr(ui.canvas.sys, "platform", "linux")
    assert ui.canvas.driver_index() == -1


def test_fps_overlay_is_opt_in(monkeypatch):
    monkeypatch.delenv("COUCHDOOM_SHOW_FPS", raising=False)
    assert ui.show_fps() is False
    monkeypatch.setenv("COUCHDOOM_SHOW_FPS", "1")
    assert ui.show_fps() is True


def test_renderer_failure_falls_back_to_the_window_surface(monkeypatch):
    # Renderer errors are pygame._sdl2.sdl2.error: a RuntimeError, not a pygame.error.
    def broken(_window):
        raise RuntimeError("Couldn't find matching render driver")

    monkeypatch.setattr(ui, "use_gpu", lambda: True)
    monkeypatch.setattr(ui.canvas, "Canvas", broken)
    monkeypatch.setattr(ui.log, "write", lambda *a: None)
    window = SimpleNamespace(get_surface=lambda: "software surface")
    assert ui.App._window_target(window) == "software surface"


def window_app(screen=None):
    app = ui.App.__new__(ui.App)
    app.screen, app.running, app.hidden, app.refresh_hz = screen, True, False, 60
    app._presented_at = 0.0
    app._frame_period = 0.0
    return app


def test_closing_the_main_window_quits_even_though_quit_never_comes():
    app = window_app()
    assert app._on_window_event(SimpleNamespace(type=ui.pygame.WINDOWCLOSE, window=object()))
    assert app.running is False


def test_the_hidden_format_window_never_counts_as_the_app():
    helper = object()
    screen = ui.canvas.Canvas.__new__(ui.canvas.Canvas)
    screen.format_window = helper
    app = window_app(screen)
    assert app._on_window_event(SimpleNamespace(type=ui.pygame.WINDOWHIDDEN, window=helper))
    assert app._on_window_event(SimpleNamespace(type=ui.pygame.WINDOWCLOSE, window=helper))
    assert app.hidden is False and app.running is True


def test_moving_displays_forgets_the_learned_period(monkeypatch):
    app = window_app()
    app._frame_period = 1 / 60
    monkeypatch.setattr(ui, "display_refresh_rate", lambda: 144)
    assert app._on_window_event(SimpleNamespace(type=ui.pygame.WINDOWDISPLAYCHANGED, window=object()))
    assert app.refresh_hz == 144
    assert app._frame_period == 0.0


def test_canvas_caps_frames_above_the_display_so_vsync_paces():
    screen = ui.canvas.Canvas.__new__(ui.canvas.Canvas)
    assert window_app(screen)._frame_cap() == 75
    assert window_app("software surface")._frame_cap() == 60


def test_canvas_sleeps_out_the_frame_before_the_gil_holding_present(monkeypatch):
    calls = []
    screen = ui.canvas.Canvas.__new__(ui.canvas.Canvas)
    perf, sleep, _advance = _clock(10.004)
    screen.present = lambda: calls.append("present")
    app = window_app(screen)
    app._presented_at = 10.0

    def recorded_sleep(seconds: float) -> None:
        calls.append(round(seconds, 4))
        sleep(seconds)

    monkeypatch.setattr(ui.time, "perf_counter", perf)
    monkeypatch.setattr(ui.time, "sleep", recorded_sleep)
    app._flip()
    assert calls == [round(1 / 60 - ui.VSYNC_MARGIN - 0.004, 4), "present"]


def test_a_late_frame_presents_without_sleeping(monkeypatch):
    calls = []
    screen = ui.canvas.Canvas.__new__(ui.canvas.Canvas)
    screen.present = lambda: calls.append("present")
    app = window_app(screen)
    monkeypatch.setattr(ui.time, "perf_counter", lambda: 10.02)
    monkeypatch.setattr(ui.time, "sleep", lambda s: calls.append(s))
    app._presented_at = 10.0
    app._flip()
    assert calls == ["present"]


def _clock(start: float):
    now = {"t": start}

    def perf() -> float:
        return now["t"]

    def sleep(seconds: float) -> None:
        now["t"] += seconds

    def advance(seconds: float) -> None:
        now["t"] += seconds

    return perf, sleep, advance


def test_a_present_that_blocks_past_the_margin_learns_the_slower_panel(monkeypatch):
    """The guessed rate is the fastest desktop. A window on a slower panel must lengthen the wait,
    or present() keeps holding the GIL for the rest of that panel's frame."""
    screen = ui.canvas.Canvas.__new__(ui.canvas.Canvas)
    perf, sleep, advance = _clock(50.0)
    screen.present = lambda: advance(0.012)
    app = window_app(screen)
    app.refresh_hz = 170
    app._presented_at = 50.0
    app._frame_period = 0.0
    monkeypatch.setattr(ui.time, "perf_counter", perf)
    monkeypatch.setattr(ui.time, "sleep", sleep)
    app._flip()
    assert app._frame_period > 1 / 170


def test_a_hitch_does_not_stretch_the_learned_period(monkeypatch):
    screen = ui.canvas.Canvas.__new__(ui.canvas.Canvas)
    perf, sleep, advance = _clock(50.0 + 1 / 60)
    screen.present = lambda: advance(0.012)
    app = window_app(screen)
    app._presented_at = 50.0
    app._frame_period = 1 / 60
    monkeypatch.setattr(ui.time, "perf_counter", perf)
    monkeypatch.setattr(ui.time, "sleep", sleep)
    app._flip()
    assert app._frame_period == pytest.approx(1 / 60)


def test_a_present_that_does_not_block_shortens_the_wait(monkeypatch):
    """A compositor that returns at once would otherwise be slept at the guessed rate."""
    screen = ui.canvas.Canvas.__new__(ui.canvas.Canvas)
    perf, sleep, _advance = _clock(80.0)
    screen.present = lambda: None
    app = window_app(screen)
    app._presented_at = 80.0
    app._frame_period = 1 / 60
    monkeypatch.setattr(ui.time, "perf_counter", perf)
    monkeypatch.setattr(ui.time, "sleep", sleep)
    app._flip()
    assert app._frame_period == pytest.approx(1 / 60 - ui.VSYNC_MARGIN)


def test_background_column_scales_to_the_full_surface():
    pygame.init()
    app = ui.App.__new__(ui.App)
    app.w, app.h, app.s = 9, 6, 1.0
    bg = app._make_background(HOUSE)
    column = app._bg_columns[bg]
    scaled = pygame.transform.scale(column, bg.get_size())
    assert pygame.image.tobytes(scaled, "RGB") == pygame.image.tobytes(bg, "RGB")


def test_canvas_stretches_the_background_column_instead_of_uploading_it():
    pygame.init()
    app = ui.App.__new__(ui.App)
    app.w, app.h = 8, 4
    full = pygame.Surface((8, 4))
    column = pygame.Surface((1, 4))
    app._bg_columns = {full: column}
    calls = []
    screen = ui.canvas.Canvas.__new__(ui.canvas.Canvas)
    screen.blit_scaled = lambda source, area, dest, alpha=1: calls.append((source, pygame.Rect(dest), alpha))
    screen.blit = lambda *_a, **_k: calls.append("full")
    app.screen = screen
    app._blit_background(full, (0, 0), 0.4)
    assert calls == [(column, pygame.Rect(0, 0, 8, 4), 0.4)]


def test_software_still_blits_the_full_background():
    pygame.init()
    app = ui.App.__new__(ui.App)
    app.w, app.h = 8, 4
    full = pygame.Surface((8, 4))
    app._bg_columns = {full: pygame.Surface((1, 4))}
    calls = []
    app.screen = SimpleNamespace(blit=lambda *a, **k: calls.append(a[0]))
    app._blit_background(full, (0, 0), 1.0)
    assert calls == [full]


def test_vendored_sdl_is_the_hashed_library_not_the_image_addon(tmp_path):
    libs = tmp_path / "pygame_ce.libs"
    libs.mkdir()
    sdl = libs / "libSDL2-2-abc.0.so.0.3200.10"
    image = libs / "libSDL2_image-2-abc.0.so.0.800.12"
    sdl.write_bytes(b"")
    image.write_bytes(b"")
    assert ui.canvas.vendored_sdl(tmp_path) == sdl
    assert ui.canvas.vendored_sdl(Path(tmp_path) / "missing") is None


def test_motion_tracks_elapsed_time_rather_than_the_frame():
    at_60 = ui._approach(0.0, 10.0, 16, 1 / 60)
    at_120 = ui._approach(0.0, 10.0, 16, 1 / 120)
    assert at_120 == pytest.approx(at_60 / 2)  # half the frame, half the travel
    assert at_120 < at_60
