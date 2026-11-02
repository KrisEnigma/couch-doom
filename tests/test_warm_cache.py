import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

from couch_doom import asset_cache, music_cache, ui
from couch_doom.options import Preset, unpack
from couch_doom.ui import App, Row


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
