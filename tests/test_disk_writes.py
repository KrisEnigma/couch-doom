import threading
from pathlib import Path

from couch_doom import asset_cache, log, state as state_mod
from couch_doom.asset_cache import CachedAssets
from couch_doom.state import State


def test_a_settings_file_that_cannot_be_replaced_does_not_crash_the_toggle(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text('{"language": "en", "language_source": "menu"}', encoding="utf-8")
    state = State(path)
    logged = []
    monkeypatch.setattr(state_mod.log, "write", lambda title, body="": logged.append(title))

    def locked(self, target):
        raise PermissionError("held by another process")

    monkeypatch.setattr(Path, "replace", locked)
    assert state.toggle_favorite("Doom") is True
    assert state.favorites == ["Doom"]
    assert logged == ["settings not saved"]


def test_concurrent_log_writes_rotate_once(tmp_path, monkeypatch):
    path = tmp_path / "couch-doom.log"
    monkeypatch.setattr(log, "MAX_BYTES", 1024)
    monkeypatch.setattr(log.sys, "stderr", None)
    path.write_text("x" * 2048, encoding="utf-8")
    barrier = threading.Barrier(8)

    def writer(n):
        barrier.wait()
        log.write(f"entry {n}", path=path)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert path.with_name(path.name + ".1").read_text(encoding="utf-8") == "x" * 2048
    assert path.read_text(encoding="utf-8").count("=== ") == 8


def test_asset_cache_entries_are_swapped_in_whole(tmp_path, monkeypatch):
    monkeypatch.setattr(asset_cache, "cache_dir", lambda: tmp_path)
    asset_cache.put("key", CachedAssets(None, None, None, None))
    cached = asset_cache.get("key")
    assert cached is not None and cached.art is None
    assert [p.name for p in (tmp_path / "assets").iterdir()] == ["key.json"]
