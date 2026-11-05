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


def test_a_named_cache_file_replaces_the_hash_and_still_loads(tmp_path, monkeypatch):
    monkeypatch.setattr(asset_cache, "cache_dir", lambda: tmp_path)
    asset_cache.put("abc", asset_cache.CachedAssets(None, None, None, None))

    asset_cache.name_cache_file("abc", 'Breach: "the/wad"')

    files = sorted(p.name for p in (tmp_path / "assets").glob("*.json"))
    assert files == ["Breach the wad--abc.json"]
    assert asset_cache.get("abc") is not None

    asset_cache.name_cache_file("abc", "Other name")
    files = sorted(p.name for p in (tmp_path / "assets").glob("*.json"))
    assert files == ["Other name--abc.json"]
    assert asset_cache.get("abc") is not None

    (tmp_path / "assets" / files[0]).unlink()
    assert asset_cache.get("abc") is None


def test_duplicate_preset_names_keep_both_cache_files(tmp_path, monkeypatch):
    monkeypatch.setattr(asset_cache, "cache_dir", lambda: tmp_path)
    asset_cache.put("aaa", asset_cache.CachedAssets(None, None, None, None), label="Doom 64 (Maps)")
    asset_cache.put("bbb", asset_cache.CachedAssets(None, None, None, None), label="Doom 64 (Maps)")

    names = sorted(p.name for p in (tmp_path / "assets").glob("*.json"))

    assert names == ["Doom 64 (Maps)--aaa.json", "Doom 64 (Maps)--bbb.json"]
    assert asset_cache.get("aaa") is not None and asset_cache.get("bbb") is not None


def test_invalidate_keeps_a_named_file_for_a_preset_that_is_still_there(tmp_path, monkeypatch):
    monkeypatch.setattr(asset_cache, "cache_dir", lambda: tmp_path)
    asset_cache.put("aaa", asset_cache.CachedAssets(None, None, None, None), label="Doom 64 (Maps)")
    asset_cache.put("bbb", asset_cache.CachedAssets(None, None, None, None), label="Gone (Maps)")

    asset_cache.invalidate_missing({"aaa"})

    assert [p.name for p in (tmp_path / "assets").glob("*.json")] == ["Doom 64 (Maps)--aaa.json"]


def test_a_long_or_blank_name_stays_a_legal_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(asset_cache, "cache_dir", lambda: tmp_path)
    asset_cache.put("abc", asset_cache.CachedAssets(None, None, None, None), label="x" * 200)
    asset_cache.put("def", asset_cache.CachedAssets(None, None, None, None), label="...")

    named = next(p.name for p in (tmp_path / "assets").glob("*--abc.json"))
    assert named.endswith("--abc.json") and len(named) < 200
    assert (tmp_path / "assets" / "def.json").is_file()


def test_duplicate_names_with_different_paths_are_different_presets():
    one = Preset("Doom 64", "Maps", "gz", None, [Path("E:/a/doom64.wad")])
    two = Preset("Doom 64", "Maps", "gz", None, [Path("E:/b/doom64.wad")])

    assert asset_cache.preset_identity(one) != asset_cache.preset_identity(two)
