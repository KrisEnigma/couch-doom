"""The card takes its face from the first launcher entry that has one.

Arrival in the DoomRunner file attached to issue 18 is checked first, and the preference
bundles that were covering it (logo and readme) come after. Discussion 26.
"""
import zipfile
from dataclasses import replace

from couch_doom import asset_cache, readme, ui
from couch_doom.launch import load_order, load_rows
from couch_doom.options import Preset
from couch_doom.titleart import find_logo
from couch_doom.readme import find_readme


def _png(w: int, h: int, tag: bytes) -> bytes:
    return b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + w.to_bytes(4, "big") + h.to_bytes(4, "big") + tag


def _wad(lumps: dict[str, bytes]) -> bytes:
    body, entries, pos = b"", b"", 12
    for name, data in lumps.items():
        entries += pos.to_bytes(4, "little") + len(data).to_bytes(4, "little") + name.encode().ljust(8, b"\0")
        body += data
        pos += len(data)
    return b"PWAD" + len(lumps).to_bytes(4, "little") + pos.to_bytes(4, "little") + body + entries


def _arrival(tmp_path, *, map_readme: bool):
    iwad = tmp_path / "DOOM2.WAD"
    iwad.write_bytes(_wad({"PLAYPAL": b"\x80" * 768, "TITLEPIC": _png(320, 200, b"doom2")}))
    maps = tmp_path / "maps"
    maps.mkdir()
    wad = maps / "arrival.wad"
    wad.write_bytes(_wad({"TITLEPIC": _png(640, 400, b"arrival")}))
    if map_readme:
        (maps / "arrival.txt").write_text(
            "Title        : Arrival\nAuthor       : Walker\nDescription  : The map set.\n", encoding="utf-8")
    mods = tmp_path / "mods"
    mods.mkdir()
    cards = mods / "cards.pk3"
    with zipfile.ZipFile(cards, "w") as z:
        z.writestr("graphics/corruption-cards-logo.png", _png(320, 48, b"cards"))
    (mods / "cards.txt").write_text(
        "Title        : Corruption Cards\nAuthor       : Someone\nDescription  : The gameplay mod.\n",
        encoding="utf-8")
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    arrival = bundles / "Arrival.dmb"
    arrival.write_text("../maps/arrival.wad\n", encoding="utf-8")
    prefs = bundles / "MyPreference_HUD.dmb"
    prefs.write_text("../mods/cards.pk3\n", encoding="utf-8")
    preset = Preset("Arrival", "Presets", "uzdoom", iwad, [arrival, prefs], mod_entries=[arrival, prefs])
    return iwad, preset


def test_first_checked_bundle_keeps_the_card(tmp_path, monkeypatch):
    monkeypatch.setattr(readme, "_load_overrides", lambda: {})
    monkeypatch.setattr(asset_cache, "_assets_dir", lambda: tmp_path)
    iwad, preset = _arrival(tmp_path, map_readme=True)

    rows = load_rows(preset)
    assert [row[0].name for row in rows] == ["Arrival.dmb", "MyPreference_HUD.dmb"]
    assert [path.name for path in load_order(preset)] == ["arrival.wad", "cards.pk3"]
    # What the old rule would have shown: the later bundle's logo, over the map's title.
    assert find_logo(iwad, load_order(preset)).data.endswith(b"cards")
    assert find_readme(preset).fields["title"] == "Arrival"

    art, found, _, logo = ui._load_extras(preset)

    assert art and art.data.endswith(b"arrival") and not art.fallback
    assert logo is None
    assert found and found.fields["title"] == "Arrival" and found.author == "Walker"


def test_a_later_bundle_does_not_lend_its_readme_when_the_map_has_none(tmp_path, monkeypatch):
    monkeypatch.setattr(readme, "_load_overrides", lambda: {})
    monkeypatch.setattr(asset_cache, "_assets_dir", lambda: tmp_path)
    iwad, preset = _arrival(tmp_path, map_readme=False)

    assert find_logo(iwad, load_order(preset)).data.endswith(b"cards")
    assert find_readme(preset).fields["title"] == "Corruption Cards"

    art, found, _, logo = ui._load_extras(preset)

    assert art and art.data.endswith(b"arrival")
    assert logo is None
    assert found is None


def test_an_entry_with_no_face_does_not_block_the_next_one(tmp_path, monkeypatch):
    monkeypatch.setattr(readme, "_load_overrides", lambda: {})
    monkeypatch.setattr(asset_cache, "_assets_dir", lambda: tmp_path)
    iwad, preset = _arrival(tmp_path, map_readme=False)
    blank = tmp_path / "maps" / "blank.wad"
    blank.write_bytes(_wad({"PLAYPAL": b"\x10" * 768}))
    lead = tmp_path / "bundles" / "Blank.dmb"
    lead.write_text("../maps/blank.wad\n", encoding="utf-8")
    preset.mods = [lead, *preset.mods]

    art, found, _, logo = ui._load_extras(preset)

    assert art and art.data.endswith(b"arrival")
    assert logo is None
    assert found is None


def test_load_maps_after_mods_lets_the_mod_entry_go_first(tmp_path, monkeypatch):
    monkeypatch.setattr(readme, "_load_overrides", lambda: {})
    monkeypatch.setattr(asset_cache, "_assets_dir", lambda: tmp_path)
    _, preset = _arrival(tmp_path, map_readme=True)
    arrival, prefs = preset.mods
    preset.mods = [prefs]
    preset.mappacks = [arrival]

    art, found, _, logo = ui._load_extras(preset)
    assert art and art.data.endswith(b"arrival") and logo is None
    assert found.fields["title"] == "Arrival"

    moved = replace(preset, load_maps_after_mods=True)
    art, found, _, logo = ui._load_extras(moved)
    assert logo and logo.data.endswith(b"cards")
    assert found.fields["title"] == "Corruption Cards"
