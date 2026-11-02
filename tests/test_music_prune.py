from couch_doom import music_cache
from couch_doom.music import MusicPlayer


class ManualPool:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args):
        self.jobs.append((fn, args))
        return object()


def test_music_update_schedules_cache_pruning_without_running_it_inline(monkeypatch):
    player = MusicPlayer.__new__(MusicPlayer)
    player.job = None
    player.peek = None
    player.pending = None
    player.stream_path = None
    player._prune_needed = True
    player.prune_job = None
    player.pool = ManualPool()
    calls = []
    monkeypatch.setattr(music_cache, "prune", lambda *args: calls.append(args))

    player.update()

    assert calls == []
    assert len(player.pool.jobs) == 1
    fn, args = player.pool.jobs[0]
    assert fn is music_cache.prune
    assert args == (set(),)
    assert player._prune_needed is False
