"""Legacy last_played.json → settings.ini conversion on startup."""
from __future__ import annotations

import couch_doom.config as config
from couch_doom.state import State


def test_migrate_converts_legacy_json_when_ini_absent(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    legacy = state_dir / "last_played.json"
    settings = state_dir / "settings.ini"
    legacy.write_text('{"music": false, "language": "en", "language_source": "menu"}', encoding="utf-8")
    monkeypatch.setattr(config, "STATE_DIR", state_dir)
    monkeypatch.setattr(config, "STATE_FILE", settings)
    monkeypatch.setattr(config, "LEGACY_STATE_FILES", (legacy, state_dir / "settings.json"))

    config.migrate_legacy_state_file()

    assert settings.is_file()
    assert not legacy.exists()
    state = State(settings)
    assert state.music is False
    assert "cache_dir" in settings.read_text(encoding="utf-8")


def test_migrate_converts_unreleased_settings_json(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    legacy = state_dir / "settings.json"
    settings = state_dir / "settings.ini"
    legacy.write_text('{"cache_dir": "cache", "language": "en", "language_source": "menu"}', encoding="utf-8")
    monkeypatch.setattr(config, "STATE_DIR", state_dir)
    monkeypatch.setattr(config, "STATE_FILE", settings)
    monkeypatch.setattr(config, "LEGACY_STATE_FILES", (state_dir / "last_played.json", legacy))

    config.migrate_legacy_state_file()

    assert State(settings).cache_dir == "cache"
    assert not legacy.exists()


def test_migrate_leaves_existing_ini_alone(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    legacy = state_dir / "last_played.json"
    settings = state_dir / "settings.ini"
    legacy.write_text('{"music": false}', encoding="utf-8")
    settings.write_text("; keep\n[general]\nmusic = true\nlanguage = en\nlanguage_source = menu\n", encoding="utf-8")
    monkeypatch.setattr(config, "STATE_DIR", state_dir)
    monkeypatch.setattr(config, "STATE_FILE", settings)
    monkeypatch.setattr(config, "LEGACY_STATE_FILES", (legacy, state_dir / "settings.json"))

    config.migrate_legacy_state_file()

    assert State(settings).music is True
    assert legacy.exists()


def test_migrate_ok_when_both_missing(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(config, "STATE_DIR", state_dir)
    monkeypatch.setattr(config, "STATE_FILE", state_dir / "settings.ini")
    monkeypatch.setattr(config, "LEGACY_STATE_FILES", (
        state_dir / "last_played.json", state_dir / "settings.json"))

    config.migrate_legacy_state_file()  # must not raise

    assert not (state_dir / "settings.ini").exists()
