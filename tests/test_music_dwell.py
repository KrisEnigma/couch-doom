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


class FakeChannel:
    def __init__(self):
        self.fades = []

    def get_busy(self):
        return True

    def fadeout(self, ms):
        self.fades.append(ms)


def playing_player(sig="title"):
    player = music.MusicPlayer.__new__(music.MusicPlayer)
    player.soundfont = None
    player.channels = (FakeChannel(), FakeChannel())
    player.active = 0
    player.want, player.job, player.pending = "old", None, None
    player.tracks = {("old", None): sig}
    player.playing = sig
    player.streaming = False
    return player


def test_leaving_a_preset_fades_its_track_right_away():
    player = playing_player()

    player.leave("next")

    assert player.channels[0].fades == [music.LEAVE_FADE_MS]
    assert player.want is None and player.playing is None


def test_leaving_for_a_preset_known_to_share_the_track_keeps_it_playing():
    player = playing_player()
    player.tracks[("next", None)] = "title"

    player.leave("next")

    assert player.channels[0].fades == []
    assert player.want == "old" and player.playing == "title"


def test_moving_the_selection_fades_music_before_the_dwell_ends():
    app = App.__new__(App)
    left = []
    app.music = SimpleNamespace(want=0, update=lambda: None, request=lambda *a, **k: None,
                                leave=lambda key, soundfont=None: left.append(key))
    app.current, app._music_sel, app._music_since = 1, 0, 10.0
    app.state = SimpleNamespace(music=True)
    app.rows = [object()]
    app.opts = SimpleNamespace(presets=[object(), object()], engine_for=lambda _preset: None)
    app.soundfont_choice = None
    app.soundfont = None
    app._engine_soundfont_for = lambda _engine: None
    app._category_selected = lambda: False

    app._update_music(10.1)
    app._update_music(10.2)

    assert left == [1]  # once, on the move; not every frame of the dwell
