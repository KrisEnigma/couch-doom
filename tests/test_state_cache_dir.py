"""State round-trip for optional cache_dir in settings.json."""
from __future__ import annotations

from couch_doom.state import State


def test_cache_dir_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    first = State(path)
    assert first.cache_dir is None
    first.cache_dir = "cache"
    first._save()
    again = State(path)
    assert again.cache_dir == "cache"


def test_empty_cache_dir_loads_as_none(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"cache_dir": "  ", "language": "en", "language_source": "menu"}', encoding="utf-8")
    state = State(path)
    assert state.cache_dir is None


def test_cache_dir_persists_null_so_hand_edits_survive(tmp_path):
    path = tmp_path / "settings.json"
    state = State(path)
    state.set_music(False)
    saved = path.read_text(encoding="utf-8")
    assert '"cache_dir": null' in saved
