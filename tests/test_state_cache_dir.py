"""State round-trip for optional cache_dir in settings.ini."""
from __future__ import annotations

from couch_doom.state import State


def test_cache_dir_round_trip(tmp_path):
    path = tmp_path / "settings.ini"
    first = State(path)
    assert first.cache_dir is None
    first.cache_dir = "cache"
    first._save()
    again = State(path)
    assert again.cache_dir == "cache"
    assert "; " in path.read_text(encoding="utf-8")  # comments for hand editing


def test_empty_cache_dir_loads_as_none(tmp_path):
    path = tmp_path / "settings.ini"
    path.write_text(
        "[general]\ncache_dir =   \nlanguage = en\nlanguage_source = menu\n",
        encoding="utf-8",
    )
    state = State(path)
    assert state.cache_dir is None


def test_cache_dir_persists_blank_so_hand_edits_survive(tmp_path):
    path = tmp_path / "settings.ini"
    state = State(path)
    state.set_music(False)
    saved = path.read_text(encoding="utf-8")
    assert "cache_dir =" in saved
