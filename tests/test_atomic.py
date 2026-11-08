"""replace_when_free retries brief PermissionError locks."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from couch_doom import atomic


def test_replace_when_free_swaps_the_file(tmp_path):
    source = tmp_path / "next.json"
    destination = tmp_path / "live.json"
    destination.write_text("old", encoding="utf-8")
    source.write_text("new", encoding="utf-8")

    atomic.replace_when_free(source, destination)

    assert destination.read_text(encoding="utf-8") == "new"
    assert not source.exists()


def test_replace_when_free_retries_permission_errors(tmp_path, monkeypatch):
    source = tmp_path / "next.json"
    destination = tmp_path / "live.json"
    destination.write_text("old", encoding="utf-8")
    source.write_text("new", encoding="utf-8")
    calls = []
    real = atomic.os.replace

    def flaky(src, dst):
        calls.append(src)
        if len(calls) < 3:
            raise PermissionError(5, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(atomic.time, "sleep", lambda _s: None)
    with patch.object(atomic.os, "replace", flaky):
        atomic.replace_when_free(source, destination, timeout=1.0)

    assert len(calls) == 3
    assert destination.read_text(encoding="utf-8") == "new"


def test_replace_when_free_raises_after_timeout(tmp_path, monkeypatch):
    source = tmp_path / "next.json"
    destination = tmp_path / "live.json"
    source.write_text("new", encoding="utf-8")
    destination.write_text("old", encoding="utf-8")

    def always_busy(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(atomic.time, "sleep", lambda _s: None)
    with patch.object(atomic.os, "replace", always_busy), pytest.raises(PermissionError):
        atomic.replace_when_free(source, destination, timeout=0.01)

    assert destination.read_text(encoding="utf-8") == "old"
    assert source.exists()


def test_music_selection_cache_retries_a_locked_replace(tmp_path, monkeypatch):
    from couch_doom import music_cache

    monkeypatch.setattr(music_cache, "cache_dir", lambda: tmp_path)
    calls = []
    real = atomic.os.replace

    def flaky(src, dst):
        calls.append(Path(src).name)
        if len(calls) < 2:
            raise PermissionError(5, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(atomic.time, "sleep", lambda _s: None)
    with patch.object(atomic.os, "replace", flaky):
        music_cache.put_selection("preset-a", {"track": None})
    found, result = music_cache.get_selection("preset-a")

    assert found and result == {"track": None}
    assert len(calls) == 2
