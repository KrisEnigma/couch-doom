from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

from couch_doom import asset_cache, music


class ManualPool:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args):
        future = Future()
        self.jobs.append((future, fn, args))
        return future


def test_requesting_preset_music_defers_file_identity_work_to_worker(monkeypatch):
    player = music.MusicPlayer.__new__(music.MusicPlayer)
    player.soundfont = None
    player.tsf_available = False
    player.peek = None
    player.renderers = {}
    player.channels = ()
    player.active = 0
    player.sounds = [None, None]
    player.pool = ManualPool()
    player.want = None
    player.job = None
    player.pending = None
    player.cache = {}
    player.tracks = {}
    player.playing = None
    player.streaming = False
    player.stream_path = None
    player.prune_job = None
    preset = SimpleNamespace(
        name="Preset",
        iwad=Path("game.wad"),
        mappacks=[],
        mods=[],
        load_maps_after_mods=False,
        mod_entries=[],
        unpack=[],
    )

    def key_for(*_args):
        raise AssertionError("file identity hashing must not run on the UI thread")

    monkeypatch.setattr(asset_cache, "key_for", key_for)

    player.request("preset", soundfont=None, preset=preset)

    assert len(player.pool.jobs) == 1
    assert player.job is not None
