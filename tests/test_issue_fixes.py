import json
from pathlib import Path

from couch_doom.launch import build_command, presented_files
import couch_doom.launch as launch
from couch_doom.options import Engine, Options, Preset
from couch_doom.sources import doomrunner
from couch_doom.music import _configured_soundfont


def test_empty_configured_soundfont_is_ignored(tmp_path):
    engine_path = tmp_path / "doomretro.exe"
    engine_path.touch()
    (tmp_path / "doomretro.cfg").write_text('fsynth_sf_path ""\n', encoding="utf-8")
    engine = Engine("doomretro", "Doom Retro", engine_path, None, "ChocolateDoom")

    assert _configured_soundfont(engine) is None


def test_doomrunner_bundle_expands_relative_entries_before_launch(tmp_path):
    engine_path = tmp_path / "doomretro.exe"
    engine_path.touch()
    bundle_dir = tmp_path / "Bundles"
    bundle_dir.mkdir()
    mod = bundle_dir / "VoxelDoom.pk3"
    mod.touch()
    bundle = bundle_dir / "VoxelDoom.dmb"
    bundle.write_text("# files\nVoxelDoom.pk3\n", encoding="utf-8")
    engine = Engine("doomretro", "Doom Retro", engine_path, None, "ChocolateDoom")
    preset = Preset("VoxelDoom", "Presets", "doomretro", None, [bundle], mod_entries=[bundle])
    options = Options(tmp_path / "options.json", {engine.id: engine}, engine.id, [preset], "", {}, "", [], "DoomRunner")

    argv = build_command(options, preset).argv

    assert "-merge" in argv
    assert str(mod) in argv
    assert str(bundle) not in argv


def test_presented_files_expand_doomrunner_bundle(tmp_path):
    mod = tmp_path / "title.pk3"
    mod.touch()
    bundle = tmp_path / "mods.dmb"
    bundle.write_text("title.pk3\n", encoding="utf-8")
    preset = Preset("bundle", "s", "e", None, [bundle], mod_entries=[bundle])
    assert presented_files(preset) == (None, [mod])


def test_unreadable_doomrunner_bundle_is_logged_and_skipped(monkeypatch, tmp_path):
    bundle = tmp_path / "broken.dmb"
    bundle.mkdir()
    logged = []
    monkeypatch.setattr(launch.log, "write", lambda *args: logged.append(args))
    preset = Preset("broken", "s", "e", None, [bundle], mod_entries=[bundle])

    assert launch.load_order(preset) == []
    assert logged and "Couldn't read mod bundle" in logged[0][0]


def test_presented_files_expand_doomrunner_bundle_inside_mappack(tmp_path):
    mod = tmp_path / "map.pk3"
    mod.touch()
    bundle = tmp_path / "maps.dmb"
    bundle.write_text("map.pk3\n", encoding="utf-8")
    preset = Preset("bundle", "s", "e", None, [], mappacks=[bundle])
    assert presented_files(preset) == (None, [mod])


def test_doomrunner_relative_alternative_paths_resolve_from_options_folder(tmp_path):
    settings_dir = tmp_path / "DoomRunner"
    settings_dir.mkdir()
    engine = settings_dir / "doomretro.exe"
    engine.touch()
    settings = settings_dir / "options.json"
    settings.write_text(json.dumps({
        "engines": {"engine_list": [{"id": "doomretro", "name": "Doom Retro", "path": "doomretro.exe"}],
                    "default_engine": "doomretro"},
        "presets": [{"name": "Default", "selected_engine": "doomretro",
                     "alternative_paths": {"save_dir": "../Data/Saves", "screenshot_dir": "../Data/Shots"}}],
    }), encoding="utf-8")

    preset = doomrunner.load(settings).presets[0]

    assert Path(preset.alternative_paths["save_dir"]).resolve() == (tmp_path / "Data" / "Saves").resolve()
    assert Path(preset.alternative_paths["screenshot_dir"]).resolve() == (tmp_path / "Data" / "Shots").resolve()
