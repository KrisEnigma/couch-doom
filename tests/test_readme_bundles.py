import os

from couch_doom import asset_cache, readme, ui
from couch_doom.launch import load_order
from couch_doom.options import Preset
from couch_doom.readme import Readme
from couch_doom.titleart import Art

TEXT = "Title        : Breach\nAuthor       : someone\nDescription  : A megawad for testing bundle readmes.\n"


def _megawad(tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir()
    wad = maps / "breach.wad"
    wad.write_bytes(b"PWAD" + bytes(8))
    (maps / "breach.txt").write_text(TEXT, encoding="utf-8")
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    bundle = bundles / "Breach.dmb"
    bundle.write_text("../maps/breach.wad\n", encoding="utf-8")
    return wad, bundle


def test_bundle_mod_finds_its_members_readme(tmp_path, monkeypatch):
    monkeypatch.setattr(readme, "_load_overrides", lambda: {})
    _, bundle = _megawad(tmp_path)
    found = readme.find_readme(Preset("p", "s", "e", None, [bundle], mod_entries=[bundle]))
    assert found and found.source == "breach.txt" and found.author == "someone"


def test_bundle_map_pack_finds_its_members_readme(tmp_path, monkeypatch):
    monkeypatch.setattr(readme, "_load_overrides", lambda: {})
    _, bundle = _megawad(tmp_path)
    found = readme.find_readme(Preset("p", "s", "e", None, [], mappacks=[bundle]))
    assert found and found.source == "breach.txt"


def test_text_beside_bundle_outranks_members(tmp_path, monkeypatch):
    monkeypatch.setattr(readme, "_load_overrides", lambda: {})
    _, bundle = _megawad(tmp_path)
    bundle.with_suffix(".txt").write_text("Description  : The whole set, described by its bundle.\n", encoding="utf-8")
    found = readme.find_readme(Preset("p", "s", "e", None, [bundle], mod_entries=[bundle]))
    assert found and found.source == "Breach.txt"


def test_bundle_and_loose_members_get_different_cache_keys(tmp_path):
    wad, bundle = _megawad(tmp_path)
    bundled = Preset("p", "s", "e", None, [bundle], mod_entries=[bundle])
    loose = Preset("p", "s", "e", None, [wad], mod_entries=[wad])
    assert [p.resolve() for p in load_order(bundled)] == [p.resolve() for p in load_order(loose)]
    assert asset_cache.key_for(bundled, None, load_order(bundled)) != asset_cache.key_for(loose, None, load_order(loose))


def test_cached_missing_readme_is_looked_for_again(tmp_path, monkeypatch):
    monkeypatch.setattr(readme, "_load_overrides", lambda: {})
    monkeypatch.setattr(asset_cache, "_assets_dir", lambda: tmp_path)
    _, bundle = _megawad(tmp_path)
    preset = Preset("p", "s", "e", None, [bundle], mod_entries=[bundle])
    key = asset_cache.key_for(preset, None, load_order(preset))
    asset_cache.put(key, asset_cache.CachedAssets(None, None, None, None))

    _, found, _, _ = ui._load_extras(preset)

    assert found and found.source == "breach.txt"
    assert asset_cache.get(key).readme.source == "breach.txt"


def test_changed_sidecar_readme_replaces_the_cached_one(tmp_path, monkeypatch):
    monkeypatch.setattr(readme, "_load_overrides", lambda: {})
    monkeypatch.setattr(asset_cache, "_assets_dir", lambda: tmp_path)
    wad, bundle = _megawad(tmp_path)
    preset = Preset("p", "s", "e", None, [bundle], mod_entries=[bundle])
    calls = {"n": 0}
    real = ui.find_readme

    def counting(preset):
        calls["n"] += 1
        return real(preset)

    monkeypatch.setattr(ui, "find_readme", counting)
    ui._load_extras(preset)
    key = asset_cache.key_for(preset, None, load_order(preset))
    cached = asset_cache.get(key)
    art = Art(kind="encoded", data=b"title")
    cached.art = art
    cached.readme = Readme("breach.txt", "Description  : Old blurb.\n", {"description": "Old blurb."})
    asset_cache.put(key, cached)

    txt = wad.with_suffix(".txt")
    txt.write_text("Description  : Doom2 map pack.\nCommentary   : Between the episodes.\n", encoding="utf-8")
    st = txt.stat()
    os.utime(txt, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))

    seen = calls["n"]
    found_art, found, _, _ = ui._load_extras(preset)

    assert found and "Between the episodes." in found.text and "Between the episodes." in found.blurb
    assert found_art and found_art.data == art.data
    assert calls["n"] == seen + 1
    assert ui._load_extras(preset)[1].text == found.text
    assert calls["n"] == seen + 1


def test_legacy_cache_without_a_stamp_rereads_a_different_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(readme, "_load_overrides", lambda: {})
    monkeypatch.setattr(asset_cache, "_assets_dir", lambda: tmp_path)
    _, bundle = _megawad(tmp_path)
    preset = Preset("p", "s", "e", None, [bundle], mod_entries=[bundle])
    key = asset_cache.key_for(preset, None, load_order(preset))
    art = Art(kind="encoded", data=b"title")
    asset_cache.put(key, asset_cache.CachedAssets(
        art, Readme("breach.txt", "Description  : Old blurb.\n", {"description": "Old blurb."}), None, None))

    found_art, found, _, _ = ui._load_extras(preset)

    assert found and "megawad for testing" in found.text
    assert found_art and found_art.data == art.data
    assert asset_cache.get(key).art.data == art.data
