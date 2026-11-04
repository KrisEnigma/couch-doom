from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

import couch_doom.ui as ui
from couch_doom.theme import HOUSE


@pytest.mark.parametrize("platform", ["darwin", "win32", "linux"])
def test_gpu_is_the_default_on_every_platform(monkeypatch, platform):
    monkeypatch.setattr(ui.sys, "platform", platform)
    monkeypatch.delenv("COUCHDOOM_RENDERER", raising=False)
    assert ui.use_gpu() is True


def test_software_env_still_forces_the_cpu(monkeypatch):
    monkeypatch.setattr(ui.sys, "platform", "win32")
    monkeypatch.setenv("COUCHDOOM_RENDERER", "software")
    assert ui.use_gpu() is False


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


def test_a_fullscreen_clip_does_not_keep_the_old_size_when_the_window_grows():
    """_draw_list saves the clip and puts it back. The saved rect is the whole screen, and keeping it
    pins later frames to that size: Alt+Enter up leaves the rest of the frame black."""
    screen = ui.canvas.Canvas.__new__(ui.canvas.Canvas)
    size = [1440, 810]
    screen.get_rect = lambda: pygame.Rect(0, 0, *size)
    screen._clip = None

    screen.set_clip(screen.get_clip())
    size[:] = [2560, 1440]

    assert screen.get_clip() == pygame.Rect(0, 0, 2560, 1440)


def test_a_partial_clip_still_limits_drawing():
    screen = ui.canvas.Canvas.__new__(ui.canvas.Canvas)
    screen.get_rect = lambda: pygame.Rect(0, 0, 1440, 810)
    screen._clip = None
    screen.set_clip(pygame.Rect(10, 20, 30, 40))
    assert screen.get_clip() == pygame.Rect(10, 20, 30, 40)
    screen.set_clip(None)
    assert screen.get_clip() == pygame.Rect(0, 0, 1440, 810)


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


class _ToggleWindow:
    def __init__(self, size, borderless=True):
        self.size = size
        self.borderless = borderless
        self.position = (0, 0)
        self.calls = []

    def set_windowed(self):
        self.calls.append("windowed")

    def set_fullscreen(self, desktop=False):
        self.calls.append(("fullscreen", desktop))


def _toggle_app(size, windowed, monkeypatch):
    app = window_app()
    app.window = _ToggleWindow(size, borderless=not windowed)
    app.windowed = windowed
    app.state = SimpleNamespace(windowed=windowed)
    app.state.set_windowed = lambda on: setattr(app.state, "windowed", on)
    app.screen = SimpleNamespace(
        get_width=lambda: app.window.size[0],
        get_size=lambda: tuple(app.window.size),
        set_clip=lambda rect: None,
    )
    app.layouts = []
    app._layout = lambda: app.layouts.append(tuple(app.window.size))
    app._frame_period = 1 / 60
    monkeypatch.setattr(ui, "display_refresh_rate", lambda: 170)
    monkeypatch.setattr(ui.pygame.display, "get_desktop_sizes", lambda: [(2560, 1440)])
    return app


def test_the_window_mode_is_remembered(tmp_path):
    from couch_doom.state import State

    path = tmp_path / "state.json"
    assert State(path).windowed is False
    State(path).set_windowed(True)
    assert State(path).windowed is True
    State(path).set_windowed(False)
    assert State(path).windowed is False


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_alt_enter_recreates_the_window_so_borderless_lands_at_the_corner(monkeypatch, platform):
    # X11 ignores a position request on a window that already exists, so growing one in place leaves a
    # borderless window centred and off the screen. A new window takes its position at creation.
    monkeypatch.setattr(ui.sys, "platform", platform)
    app = window_app()
    app.window = object()
    app.windowed = False
    app.state = SimpleNamespace(windowed=False)
    app.state.set_windowed = lambda on: setattr(app.state, "windowed", on)
    events = []
    app._close_window = lambda: events.append(("close", app.windowed))
    app._open_window = lambda: events.append(("open", app.windowed))
    monkeypatch.setattr(ui.pygame.display, "init", lambda: events.append("display-init"))
    monkeypatch.setattr(ui.pygame.display, "set_caption", lambda title: None)

    app._toggle_window()

    assert events == [("close", True), "display-init", ("open", True)]
    assert app.windowed is True
    assert app.state.windowed is True
    assert app._frame_period == 0.0


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_borderless_window_is_created_at_the_desktop_corner(monkeypatch, platform):
    monkeypatch.setattr(ui.sys, "platform", platform)
    monkeypatch.setattr(ui.pygame.display, "get_desktop_sizes", lambda: [(2560, 1440)])
    monkeypatch.setattr(ui, "display_refresh_rate", lambda: 170)
    monkeypatch.setattr(ui, "_set_window_icon", lambda window=None: None)
    monkeypatch.setattr(ui, "_force_foreground", lambda handle=None: None)
    monkeypatch.setattr(ui.log, "write", lambda *a: None)
    monkeypatch.setattr(ui.pygame.key, "start_text_input", lambda: None)
    created = []

    class FakeWindow:
        handle = 0

        def __init__(self, title, size, **kwargs):
            created.append((size, kwargs))
            self.size = size

    monkeypatch.setattr(ui.pygame, "Window", FakeWindow)
    app = window_app()
    app.windowed = False
    app._window_target = lambda window: SimpleNamespace(get_width=lambda: 2560)
    app._mouse_off = lambda: None
    app._layout = lambda: None

    app._create_window()

    size, kwargs = created[0]
    assert size == (2560, 1440)
    assert kwargs["borderless"] is True
    assert kwargs["position"] == (0, 0)


def test_alt_enter_on_mac_uses_desktop_fullscreen_not_a_mode_change(monkeypatch):
    monkeypatch.setattr(ui.sys, "platform", "darwin")
    shadows = []
    monkeypatch.setattr(ui, "_disable_macos_fullscreen_shadow", lambda: shadows.append("shadow"))
    app = _toggle_app((2560, 1440), windowed=False, monkeypatch=monkeypatch)

    app._toggle_window()

    assert app.windowed is True
    assert app.window.calls == ["windowed"]
    assert app.window.size == ui.WINDOWED_SIZE
    assert shadows == []

    app._toggle_window()

    assert app.windowed is False
    assert app.window.calls == ["windowed", ("fullscreen", True)]
    assert app.window.size == (2560, 1440)
    assert shadows == ["shadow"]


def test_alt_enter_is_consumed_and_a_held_key_toggles_once():
    app = window_app()
    app.mode, app.filter = "list", ""
    app._alt_enter_held = False
    calls = []
    app._toggle_window = lambda: calls.append("toggle")
    alt = SimpleNamespace(key=ui.pygame.K_RETURN, mod=ui.pygame.KMOD_ALT)
    plain = SimpleNamespace(key=ui.pygame.K_RETURN, mod=0)

    assert app._on_key(plain) is False
    assert app._on_key(alt) is True
    assert app._on_key(alt) is True
    assert calls == ["toggle"]

    app._alt_enter_held = False
    pad = SimpleNamespace(key=ui.pygame.K_KP_ENTER, mod=ui.pygame.KMOD_LALT)
    assert app._on_key(pad) is True
    assert calls == ["toggle", "toggle"]


def test_alt_enter_toggles_while_search_is_open_instead_of_closing_it():
    app = window_app()
    app.mode, app.filter = "search", "doom"
    app._alt_enter_held = False
    seen = []
    app._close_overlay = lambda: seen.append("close")
    app._toggle_window = lambda: seen.append("toggle")

    assert app._on_key(SimpleNamespace(key=ui.pygame.K_RETURN, mod=ui.pygame.KMOD_ALT)) is True
    assert seen == ["toggle"]


def test_motion_tracks_elapsed_time_rather_than_the_frame():
    at_60 = ui._approach(0.0, 10.0, 16, 1 / 60)
    at_120 = ui._approach(0.0, 10.0, 16, 1 / 120)
    assert at_120 == pytest.approx(at_60 / 2)  # half the frame, half the travel
    assert at_120 < at_60
