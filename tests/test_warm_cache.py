import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

from couch_doom import asset_cache, i18n, music_cache, ui
from couch_doom.options import Preset, unpack
from couch_doom.ui import WARM_PROGRESS_DELAY, App, Row


class InlineThread:
    def __init__(self, target, daemon=False):
        self.target = target

    def start(self):
        self.target()


def _warm_app(monkeypatch, *, visible: list[int], total: int):
    app = App.__new__(App)
    app.opts = SimpleNamespace(presets=[SimpleNamespace(name=f"p{i}") for i in range(total)])
    app.rows = [Row("preset", f"p{i}", i) for i in visible]
    app.current = visible[0]
    app.cur_row = 0
    app.art_cache, app.art_jobs = {}, {}
    app.running = True
    app._warm_generation = 0
    app._warm_allowed = threading.Event()
    app._warm_allowed.set()
    app._warm_announce = False
    app._warm_immediate = False
    app.menu_status = ""
    app.menu_status_at = 0.0
    app._preset_rows = lambda: list(range(len(app.rows)))
    app._sel_row = lambda: 0

    seen: list[str] = []
    calls = {}
    monkeypatch.setattr(ui.threading, "Thread", InlineThread)
    monkeypatch.setattr(ui, "unpack", lambda preset: seen.append(preset.name))
    monkeypatch.setattr(ui, "load_order", lambda preset: [])
    monkeypatch.setattr(ui, "presented_files", lambda preset: (None, []))
    monkeypatch.setattr(ui, "_load_extras", lambda preset: None)
    monkeypatch.setattr(asset_cache, "key_for", lambda preset, iwad, files: preset.name)
    monkeypatch.setattr(asset_cache, "get", lambda key: True)
    monkeypatch.setattr(asset_cache, "load_preset_keys", lambda: {})
    monkeypatch.setattr(asset_cache, "save_preset_keys", lambda mapping: None)
    monkeypatch.setattr(asset_cache, "name_cache_file", lambda key, label: None)
    monkeypatch.setattr(asset_cache, "prune", lambda: None)
    monkeypatch.setattr(asset_cache, "invalidate_missing", lambda keys: calls.setdefault("assets", keys))
    monkeypatch.setattr(music_cache, "selection_key", lambda key, iwad, files: key)
    monkeypatch.setattr(music_cache, "invalidate_selections", lambda keys: calls.setdefault("music", keys))
    return app, seen, calls


def test_warming_covers_presets_in_folded_groups(monkeypatch):
    app, seen, calls = _warm_app(monkeypatch, visible=[1, 2], total=4)

    app._warm_cache()

    assert seen[:2] == ["p1", "p2"]  # visible rows first
    assert sorted(seen) == ["p0", "p1", "p2", "p3"]
    assert calls["assets"] == {"p0", "p1", "p2", "p3"}


def test_an_interrupted_pass_never_invalidates_caches(monkeypatch):
    app, seen, calls = _warm_app(monkeypatch, visible=[0], total=3)
    real_unpack = ui.unpack

    def stop_after_first(preset):
        real_unpack(preset)
        app.running = False

    monkeypatch.setattr(ui, "unpack", stop_after_first)

    app._warm_cache()

    assert seen == ["p0"]
    assert calls == {}


def test_a_finished_pass_counts_each_preset_then_clears_the_count(monkeypatch):
    app, _, _ = _warm_app(monkeypatch, visible=[0], total=3)
    seen_counts = []
    real_unpack = ui.unpack

    def note(preset):
        real_unpack(preset)
        seen_counts.append(app._warm_progress)

    monkeypatch.setattr(ui, "unpack", note)

    app._warm_cache()

    assert seen_counts == [(0, 3), (1, 3), (2, 3)]  # the counter moves after the previous preset
    assert app._warm_progress is None


def test_a_retired_pass_leaves_the_new_count_alone(monkeypatch):
    app, _, _ = _warm_app(monkeypatch, visible=[0], total=3)
    real_unpack = ui.unpack

    def hand_off(preset):
        real_unpack(preset)
        app._warm_generation += 1
        app._warm_progress = (4, 9)

    monkeypatch.setattr(ui, "unpack", hand_off)

    app._warm_cache()

    assert app._warm_progress == (4, 9)


def test_the_count_stays_hidden_until_the_walk_has_lasted_a_second():
    i18n.set_language("en")
    app = App.__new__(App)
    app._warm_begun = 10.0
    app._warm_progress = (2, 9)
    app._warm_immediate = False

    assert app._warm_status(10.0 + WARM_PROGRESS_DELAY - 0.01) is None
    assert app._warm_status(10.0 + WARM_PROGRESS_DELAY) == "Caching 2/9"
    app._warm_progress = None
    assert app._warm_status(12.0) is None
    app._warm_progress = (0, 0)
    assert app._warm_status(12.0) is None


def test_a_refresh_shows_the_count_immediately_and_says_refreshed_when_the_walk_ends(monkeypatch):
    i18n.set_language("en")
    app, _, _ = _warm_app(monkeypatch, visible=[0], total=3)
    app._warm_announce = True

    app._warm_cache()

    assert app._warm_immediate is False
    assert app._warm_progress is None
    assert app.menu_status == "Refreshed"
    app._warm_progress = (1, 3)
    app._warm_immediate = True
    assert app._warm_status(app._warm_begun) == "Caching 1/3"


def test_a_finished_pass_remembers_each_preset_key(monkeypatch):
    app, _, _ = _warm_app(monkeypatch, visible=[0], total=2)
    saved = {}
    monkeypatch.setattr(asset_cache, "save_preset_keys", lambda mapping: saved.update(mapping))

    app._warm_cache()

    assert saved == {asset_cache.preset_identity(preset): preset.name for preset in app.opts.presets}


def test_an_interrupted_pass_does_not_replace_remembered_keys(monkeypatch):
    app, seen, _ = _warm_app(monkeypatch, visible=[0], total=3)
    saved = []
    monkeypatch.setattr(asset_cache, "save_preset_keys", lambda mapping: saved.append(mapping))

    def stop(preset):
        seen.append(preset.name)
        app.running = False

    monkeypatch.setattr(ui, "unpack", stop)

    app._warm_cache()

    assert saved == []


def test_a_cache_hit_refreshes_the_readme_stamp(monkeypatch):
    app, _, _ = _warm_app(monkeypatch, visible=[0, 1, 2], total=3)
    cached = asset_cache.CachedAssets(None, None, None, None, "stamp")
    synced = []
    loaded = []
    monkeypatch.setattr(asset_cache, "get", lambda key: cached)
    monkeypatch.setattr(ui, "_sync_cached_readme", lambda *args: synced.append(args[0].name))
    monkeypatch.setattr(ui, "_load_extras", lambda preset: loaded.append(preset.name))

    app._warm_cache()

    assert synced == ["p0", "p1", "p2"]
    assert loaded == []


def test_a_cache_hit_names_the_file_after_the_preset(monkeypatch):
    app, _, _ = _warm_app(monkeypatch, visible=[0], total=1)
    app.opts.presets[0] = SimpleNamespace(name="Doom 64", section="Maps")
    named = []
    monkeypatch.setattr(asset_cache, "name_cache_file", lambda key, label: named.append((key, label)))
    monkeypatch.setattr(asset_cache, "get", lambda key: asset_cache.CachedAssets(None, None, None, None, "stamp"))

    app._warm_cache()

    assert named == [("Doom 64", "Doom 64 (Maps)")]


def test_an_offline_preset_keeps_its_previous_cache_file(monkeypatch):
    app, seen, calls = _warm_app(monkeypatch, visible=[0], total=1)
    saved = {}
    monkeypatch.setattr(asset_cache, "preset_offline", lambda preset: True)
    monkeypatch.setattr(asset_cache, "load_preset_keys", lambda: {"same": "old-key"})
    monkeypatch.setattr(asset_cache, "preset_identity", lambda preset: "same")
    monkeypatch.setattr(asset_cache, "save_preset_keys", lambda mapping: saved.update(mapping))

    app._warm_cache()

    assert calls["assets"] == {"old-key"}
    assert "music" not in calls
    assert saved == {"same": "old-key"}
    assert seen == []


def test_an_offline_preset_with_no_memory_does_not_wipe_the_cache(monkeypatch):
    app, seen, calls = _warm_app(monkeypatch, visible=[0], total=1)
    monkeypatch.setattr(asset_cache, "preset_offline", lambda preset: True)

    app._warm_cache()

    assert "assets" not in calls
    assert "music" not in calls
    assert seen == []


def test_a_newer_pass_retires_the_old_one(monkeypatch):
    app, seen, calls = _warm_app(monkeypatch, visible=[0], total=3)
    real_unpack = ui.unpack

    def reload_mid_pass(preset):
        real_unpack(preset)
        app._warm_generation += 1

    monkeypatch.setattr(ui, "unpack", reload_mid_pass)

    app._warm_cache()

    assert seen == ["p0"]
    assert calls == {}


def _archive_preset(tmp_path: Path, payload: bytes) -> tuple[Preset, Path]:
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("maps/big.wad", payload)
    dest = tmp_path / "out" / "big.wad"
    preset = Preset.__new__(Preset)
    preset.unpack = [(archive, "maps/big.wad", dest)]
    return preset, dest


def test_concurrent_unpacks_of_one_preset_both_succeed(tmp_path):
    payload = bytes(range(256)) * 20_000
    preset, dest = _archive_preset(tmp_path, payload)
    errors: list[str | None] = []
    threads = [threading.Thread(target=lambda: errors.append(unpack(preset))) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == [None] * 4
    assert dest.read_bytes() == payload
    assert not dest.with_suffix(".wad.part").exists()
