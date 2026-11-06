"""cache_dir env override, settings configure, and healing of a non-directory occupant."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from couch_doom.cache_paths import cache_dir, configure


@pytest.fixture(autouse=True)
def _reset_settings_cache_dir():
    configure(None)
    yield
    configure(None)


def test_cache_dir_env_override_wins(tmp_path, monkeypatch):
    target = tmp_path / "custom-cache"
    settings_target = tmp_path / "from-settings"
    configure(str(settings_target))
    monkeypatch.setenv("COUCHDOOM_CACHE_DIR", str(target))
    assert cache_dir() == target
    assert target.is_dir()


def test_cache_dir_settings_wins_over_platform_default(tmp_path, monkeypatch):
    monkeypatch.delenv("COUCHDOOM_CACHE_DIR", raising=False)
    target = tmp_path / "settings-cache"
    configure(str(target))
    assert cache_dir() == target
    assert target.is_dir()


def test_cache_dir_relative_settings_resolves_against_data_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("COUCHDOOM_CACHE_DIR", raising=False)
    data = tmp_path / "data"
    data.mkdir()
    configure("cache")
    with patch("couch_doom.config.DATA_DIR", data):
        assert cache_dir() == data / "cache"
    assert (data / "cache").is_dir()


def test_cache_dir_replaces_a_file_occupying_the_path(tmp_path, monkeypatch):
    blocked = tmp_path / "cache"
    blocked.write_text("not a directory")
    monkeypatch.setenv("COUCHDOOM_CACHE_DIR", str(blocked))
    assert cache_dir() == blocked
    assert blocked.is_dir()


@pytest.mark.skipif(os.name != "nt", reason="Windows junctions")
def test_cache_dir_heals_a_dangling_junction(tmp_path, monkeypatch):
    target = tmp_path / "gone-target"
    target.mkdir()
    junction = tmp_path / "dangling-cache"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip(f"mklink /J unavailable: {created.stderr or created.stdout}")
    target.rmdir()
    assert not junction.is_dir()
    monkeypatch.setenv("COUCHDOOM_CACHE_DIR", str(junction))
    assert cache_dir() == junction
    assert junction.is_dir()


def test_cache_dir_unlinks_then_mkdirs_when_path_is_not_a_directory(tmp_path, monkeypatch):
    """Mocked FileExistsError path used when a real dangling junction cannot be made."""
    path = tmp_path / "occupied"
    monkeypatch.setenv("COUCHDOOM_CACHE_DIR", str(path))
    real_mkdir = Path.mkdir
    mkdir_calls = []
    unlinked = []

    def flaky_mkdir(self, *args, **kwargs):
        mkdir_calls.append(self)
        if len(mkdir_calls) == 1:
            raise FileExistsError(183, "Cannot create a file when that file already exists")
        return real_mkdir(self, *args, **kwargs)

    with (
        patch.object(Path, "mkdir", flaky_mkdir),
        patch.object(Path, "is_dir", lambda self: False),
        patch.object(Path, "unlink", lambda self: unlinked.append(self)),
    ):
        assert cache_dir() == path
    assert unlinked == [path]
    assert len(mkdir_calls) == 2
