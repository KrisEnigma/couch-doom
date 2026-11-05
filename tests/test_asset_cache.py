import json
import os
from pathlib import Path

from couch_doom import asset_cache
from couch_doom.asset_cache import _endoom_from_dict, _endoom_to_dict
from couch_doom.endoom import Endoom, SIZE
from couch_doom.options import Preset


def test_endoom_cache_round_trip_preserves_raw_bytes():
    screen = Endoom("hell-revealed-2.wad", bytes(range(256)) * (SIZE // 256) + bytes(range(SIZE % 256)))

    encoded = json.loads(json.dumps(_endoom_to_dict(screen)))
    restored = _endoom_from_dict(encoded)

    assert restored == screen


def test_preset_key_index_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(asset_cache, "cache_dir", lambda: tmp_path)

    asset_cache.save_preset_keys({"abc": "def"})

    assert asset_cache.load_preset_keys() == {"abc": "def"}
    assert not list(tmp_path.glob("preset_keys.*.tmp"))


def test_a_missing_drive_is_offline_and_a_deleted_file_is_not(tmp_path, monkeypatch):
    wad = tmp_path / "cool.wad"
    wad.write_bytes(b"PWAD" + bytes(8))
    preset = Preset("Cool", "Maps", "gz", None, [wad])
    before = asset_cache.key_for(preset, None, [wad])
    wad.unlink()

    assert not asset_cache.preset_offline(preset)
    assert asset_cache.key_for(preset, None, [wad]) != before

    monkeypatch.setattr(asset_cache, "_path_exists", lambda path: False)
    if os.name == "nt":
        assert asset_cache.volume_unavailable(Path("E:/wads/cool.wad"))
    assert asset_cache.volume_unavailable(Path("/Volumes/Games/cool.wad"))
    assert asset_cache.volume_unavailable(Path("/mnt/games/cool.wad"))
    assert asset_cache.volume_unavailable(Path("/media/games/cool.wad"))
    assert asset_cache.volume_unavailable(Path("/run/media/kris/games/cool.wad"))
    assert not asset_cache.volume_unavailable(Path("/home/kris/cool.wad"))
    assert not asset_cache.volume_unavailable(Path("/mnt/cool.wad"))
    assert not asset_cache.volume_unavailable(Path("cool.wad"))


def test_a_present_volume_stays_online(monkeypatch):
    monkeypatch.setattr(asset_cache, "_path_exists", lambda path: True)

    assert not asset_cache.volume_unavailable(Path("/Volumes/Games/cool.wad"))
    if os.name == "nt":
        assert not asset_cache.volume_unavailable(Path("E:/wads/cool.wad"))


def test_unc_paths_are_not_probed(monkeypatch):
    if os.name != "nt":
        return

    def boom(path):
        raise AssertionError(path)

    monkeypatch.setattr(asset_cache, "_path_exists", boom)

    assert not asset_cache.volume_unavailable(Path(r"\\server\share\cool.wad"))


def test_duplicate_names_with_different_paths_are_different_presets():
    one = Preset("Doom 64", "Maps", "gz", None, [Path("E:/a/doom64.wad")])
    two = Preset("Doom 64", "Maps", "gz", None, [Path("E:/b/doom64.wad")])

    assert asset_cache.preset_identity(one) != asset_cache.preset_identity(two)
