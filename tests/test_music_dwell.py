from types import SimpleNamespace

from couch_doom import music
from couch_doom.ui import App


def test_music_preparation_does_not_start_during_half_second_navigation():
    app = App.__new__(App)
    app.music = SimpleNamespace(want=None, update=lambda: None, request=lambda *a, **k: requests.append((a, k)))
    requests = []
    app.current = 0
    app._music_sel = 0
    app._music_since = 10.0
    app.state = SimpleNamespace(music=True)
    app.rows = [object()]
    app.opts = SimpleNamespace(presets=[object()], engine_for=lambda _preset: None)
    app.soundfont_choice = None
    app.soundfont = None
    app._engine_soundfont_for = lambda _engine: None
    app._category_selected = lambda: False

    app._update_music(10.5)

    assert requests == []
    assert music.DWELL_SECONDS > 0.5
