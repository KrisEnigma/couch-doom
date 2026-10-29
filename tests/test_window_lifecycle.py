from types import SimpleNamespace

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
