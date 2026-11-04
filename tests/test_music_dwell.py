from concurrent.futures import Future
from types import SimpleNamespace

from couch_doom import music
from couch_doom.ui import App


def music_app():
    app = App.__new__(App)
    requests = []
    app.music = SimpleNamespace(want=None, job=None, pending=None, update=lambda: None,
                                request=lambda *a, **k: requests.append((a, k)),
                                warm=lambda *a, **k: requests.append(("warm", a, k)))
    app.current = 0
    app.cur_row = 0
    app._music_sel = 0
    app._music_since = 10.0
    app.state = SimpleNamespace(music=True)
    app.rows = [SimpleNamespace(kind="preset", preset=0)]
    app.opts = SimpleNamespace(presets=[object()], engine_for=lambda _preset: None)
    app.soundfont_choice = None
    app.soundfont = None
    app._engine_soundfont_for = lambda _engine: None
    app._category_selected = lambda: False
    app.requests = requests
    return app


def test_music_preparation_waits_out_a_held_direction_then_starts_during_the_art_fade():
    app = music_app()

    app._update_music(10.07)  # one gamepad repeat later: still moving, nothing starts

    assert app.requests == []
    assert 0.07 < music.DWELL_SECONDS < 0.3  # past a held repeat, inside the 0.3 s art fade
    assert music.FADE_IN_MS <= 200

    app._update_music(10.0 + music.DWELL_SECONDS + 1e-3)
    assert app.requests  # settled: the track starts while the art is still fading in


def test_a_playing_preset_renders_the_next_ones_track_ahead():
    app = music_app()
    app.music.want = 0
    app.rows = [SimpleNamespace(kind="preset", preset=i) for i in range(3)]
    app.opts.presets = [object(), object(), object()]

    app._update_music(10.0)

    assert app.requests[0][0] == "warm" and app.requests[0][1][0] == 1  # the row below, first


class FakeChannel:
    def __init__(self):
        self.fades = []

    def get_busy(self):
        return True

    def fadeout(self, ms):
        self.fades.append(ms)


class HeldPool:
    """Lookups that finish only when the test says so."""

    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        future = Future()
        self.calls.append((args, future))
        return future


def playing_player(sig="title"):
    player = music.MusicPlayer.__new__(music.MusicPlayer)
    player.soundfont = None
    player.tsf_available = False
    player.channels = (FakeChannel(), FakeChannel())
    player.active = 0
    player.want, player.job, player.pending = "old", None, None
    player.peek_pool, player.peek = HeldPool(), None
    player.tracks = {("old", None): sig}
    player.playing = sig
    player.streaming = False
    return player


def test_a_background_render_becomes_playback_when_that_preset_is_chosen():
    player = playing_player()
    player.job = ("next", ("next", None), Future(), None)

    player.request("next", preset=object())

    assert player.want == "next" and player.job[0] == "next"  # kept, not cancelled and started over
    assert player.channels[0].fades == []  # still playing until the render finishes


def test_warming_does_not_touch_playback_and_skips_a_preset_already_known():
    player = playing_player()
    player.pool = HeldPool()
    player.pending = None
    player.cache = {}
    player.renderers = {}
    player.stream_path = None

    player.warm("next", preset=object())
    assert player.want == "old" and player.playing == "title" and player.channels[0].fades == []
    assert player.pool.calls and player.job[0] == "next"

    player.job = None
    player.tracks[("known", None)] = "other"
    player.warm("known", preset=object())
    assert len(player.pool.calls) == 1  # identified already: the disk or PCM cache covers it


def test_leaving_for_a_preset_known_to_use_another_track_fades_right_away():
    player = playing_player()
    player.tracks[("next", None)] = "other"

    player.leave("next", preset=object())

    assert player.channels[0].fades == [music.LEAVE_FADE_MS]
    assert player.want is None and player.playing is None
    assert player.peek_pool.calls == []


def test_leaving_for_an_unknown_preset_keeps_playing_until_its_track_turns_out_shared():
    player = playing_player()

    player.leave("next", preset=object())
    player._update_peek()
    assert player.channels[0].fades == []  # still looking it up

    player.peek_pool.calls[0][1].set_result("title")
    player._update_peek()

    assert player.channels[0].fades == []
    assert player.playing == "title" and player.tracks[("next", None)] == "title"


def test_leaving_for_an_unknown_preset_fades_once_its_track_turns_out_different():
    player = playing_player()

    player.leave("next", preset=object())
    player.peek_pool.calls[0][1].set_result("other")
    player._update_peek()

    assert player.channels[0].fades == [music.LEAVE_FADE_MS]
    assert player.want is None and player.tracks[("next", None)] == "other"


def test_a_slow_track_lookup_fades_rather_than_trailing(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(music.time, "monotonic", lambda: clock[0])
    player = playing_player()

    player.leave("next", preset=object())
    clock[0] += music.LEAVE_WAIT_SECONDS / 2
    player._update_peek()
    assert player.channels[0].fades == []

    clock[0] += music.LEAVE_WAIT_SECONDS
    player._update_peek()
    assert player.channels[0].fades == [music.LEAVE_FADE_MS]

    player.peek_pool.calls[0][1].set_result("title")
    assert player.tracks[("next", None)] == "title"  # remembered for the next visit


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
                                leave=lambda key, soundfont=None, preset=None: left.append(key))
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
