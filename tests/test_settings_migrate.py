"""Legacy last_played.json → settings.json rename on startup."""
from __future__ import annotations

from pathlib import Path

import couch_doom.config as config


def test_migrate_renames_legacy_when_settings_absent(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    legacy = state_dir / "last_played.json"
    settings = state_dir / "settings.json"
    legacy.write_text('{"music": false}', encoding="utf-8")
    monkeypatch.setattr(config, "STATE_DIR", state_dir)
    monkeypatch.setattr(config, "STATE_FILE", settings)
    monkeypatch.setattr(config, "LEGACY_STATE_FILE", legacy)

    config.migrate_legacy_state_file()

    assert settings.is_file()
    assert not legacy.exists()
    assert settings.read_text(encoding="utf-8") == '{"music": false}'


def test_migrate_leaves_existing_settings_alone(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    legacy = state_dir / "last_played.json"
    settings = state_dir / "settings.json"
    legacy.write_text("old", encoding="utf-8")
    settings.write_text("new", encoding="utf-8")
    monkeypatch.setattr(config, "STATE_DIR", state_dir)
    monkeypatch.setattr(config, "STATE_FILE", settings)
    monkeypatch.setattr(config, "LEGACY_STATE_FILE", legacy)

    config.migrate_legacy_state_file()

    assert settings.read_text(encoding="utf-8") == "new"
    assert legacy.read_text(encoding="utf-8") == "old"


def test_migrate_ok_when_both_missing(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(config, "STATE_DIR", state_dir)
    monkeypatch.setattr(config, "STATE_FILE", state_dir / "settings.json")
    monkeypatch.setattr(config, "LEGACY_STATE_FILE", state_dir / "last_played.json")

    config.migrate_legacy_state_file()  # must not raise

    assert not (state_dir / "settings.json").exists()
