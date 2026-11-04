from types import SimpleNamespace

import pytest

import couch_doom.ui as ui


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


def test_canvas_caps_frames_above_the_display_so_vsync_paces():
    screen = ui.canvas.Canvas.__new__(ui.canvas.Canvas)
    assert window_app(screen)._frame_cap() == 75
    assert window_app("software surface")._frame_cap() == 60


def test_motion_tracks_elapsed_time_rather_than_the_frame():
    at_60 = ui._approach(0.0, 10.0, 16, 1 / 60)
    at_120 = ui._approach(0.0, 10.0, 16, 1 / 120)
    assert at_120 == pytest.approx(at_60 / 2)  # half the frame, half the travel
    assert at_120 < at_60
