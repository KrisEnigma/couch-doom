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


def test_stamp_reread_ignores_a_descriptions_line_that_does_not_apply():
    old = "/a/b.txt:1:2"
    added = "/a/b.txt:1:2\ndescriptions.json:3:4"

    assert not readme.stamp_needs_reread(None, "descriptions.json:absent", override_applies=False, from_descriptions=False)
    assert readme.stamp_needs_reread(None, "descriptions.json:1:2", override_applies=True, from_descriptions=False)
    assert readme.stamp_needs_reread(None, added, override_applies=False, from_descriptions=False)
    assert not readme.stamp_needs_reread(old, added, override_applies=False, from_descriptions=False)
    assert readme.stamp_needs_reread(old, added, override_applies=True, from_descriptions=False)
    assert readme.stamp_needs_reread(old, "/a/b.txt:9:2\ndescriptions.json:3:4", override_applies=False, from_descriptions=False)
    assert readme.stamp_needs_reread("descriptions.json:1:1", "descriptions.json:2:2", override_applies=False, from_descriptions=True)


def _descriptions(tmp_path, monkeypatch, text="{}"):
    monkeypatch.setattr(asset_cache, "_assets_dir", lambda: tmp_path / "cache")
    (tmp_path / "cache").mkdir()
    desc = tmp_path / "descriptions.json"
    desc.write_text(text, encoding="utf-8")
    monkeypatch.setattr(readme, "OVERRIDES_FILE", desc)
    monkeypatch.setattr(readme, "_overrides", None)
    return desc


def test_an_old_stamp_does_not_reread_when_descriptions_names_nothing(tmp_path, monkeypatch):
    desc = _descriptions(tmp_path, monkeypatch)
    _, bundle = _megawad(tmp_path)
    preset = Preset("p", "s", "e", None, [bundle], mod_entries=[bundle])
    ui._load_extras(preset)
    key = asset_cache.key_for(preset, None, load_order(preset))
    cached = asset_cache.get(key)
    cached.readme_stamp = readme.stamp_sidecar(cached.readme_stamp)
    cached.readme = Readme("breach.txt", "Description  : Old blurb.\n", {"description": "Old blurb."})
    asset_cache.put(key, cached)
    calls = {"n": 0}
    real = ui.find_readme

    def counting(preset):
        calls["n"] += 1
        return real(preset)

    monkeypatch.setattr(ui, "find_readme", counting)
    desc.write_text('{"other.wad": {"description": "Nope."}}\n', encoding="utf-8")
    st = desc.stat()
    os.utime(desc, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    readme._overrides = None

    found = ui._load_extras(preset)[1]

    assert calls["n"] == 0
    assert found and found.text.startswith("Description  : Old blurb.")
    assert "descriptions.json:" in asset_cache.get(key).readme_stamp


def test_descriptions_override_replaces_a_cached_readme(tmp_path, monkeypatch):
    desc = _descriptions(tmp_path, monkeypatch)
    _, bundle = _megawad(tmp_path)
    preset = Preset("p", "s", "e", None, [bundle], mod_entries=[bundle])
    ui._load_extras(preset)
    key = asset_cache.key_for(preset, None, load_order(preset))
    cached = asset_cache.get(key)
    cached.readme_stamp = readme.stamp_sidecar(cached.readme_stamp)
    asset_cache.put(key, cached)
    desc.write_text('{"breach.wad": {"description": "From the player."}}\n', encoding="utf-8")
    st = desc.stat()
    os.utime(desc, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    readme._overrides = None

    found = ui._load_extras(preset)[1]

    assert found and found.source == "descriptions.json" and "From the player." in found.text


def test_removing_a_descriptions_override_restores_the_sidecar(tmp_path, monkeypatch):
    desc = _descriptions(tmp_path, monkeypatch, '{"breach.wad": {"description": "From the player."}}\n')
    _, bundle = _megawad(tmp_path)
    preset = Preset("p", "s", "e", None, [bundle], mod_entries=[bundle])
    ui._load_extras(preset)
    key = asset_cache.key_for(preset, None, load_order(preset))
    assert asset_cache.get(key).readme.source == "descriptions.json"
    desc.write_text("{}\n", encoding="utf-8")
    st = desc.stat()
    os.utime(desc, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    readme._overrides = None

    found = ui._load_extras(preset)[1]

    assert found and found.source == "breach.txt" and "megawad for testing" in found.text


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
