from pathlib import Path

import pytest

import couch_doom.filebrowser as filebrowser
from couch_doom.filebrowser import Browser, _drive_roots, list_entries, parent, roots


def test_directories_come_before_matching_files_and_are_case_insensitive(tmp_path):
    (tmp_path / "z-folder").mkdir()
    (tmp_path / "A-folder").mkdir()
    (tmp_path / "doomrunner.EXE").touch()
    (tmp_path / "OPTIONS.JSON").touch()
    (tmp_path / "notes.txt").touch()

    got = [(entry.path.name, entry.is_dir) for entry in list_entries(tmp_path, names={"doomrunner.exe", "options.json"})]

    assert got == [("A-folder", True), ("z-folder", True), ("doomrunner.EXE", False), ("OPTIONS.JSON", False)]


def test_all_files_mode_includes_unmatched_files_without_recursing(tmp_path):
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder" / "nested.exe").touch()
    (tmp_path / "readme.txt").touch()

    assert [e.path.name for e in list_entries(tmp_path, names={"launcher.exe"})] == ["folder"]
    assert [e.path.name for e in list_entries(tmp_path, show_all=True, names={"launcher.exe"})] == ["folder", "readme.txt"]


def test_symlinked_directory_is_navigable(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "launcher.exe").touch()
    link = tmp_path / "linkdir"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")

    browser = Browser(tmp_path, candidates=[tmp_path], names={"launcher.exe"})
    entry = next(e for e in browser.entries if e.path == link)
    browser.selected = browser.entries.index(entry)
    assert entry.is_dir
    assert browser.open_selected() is None
    assert browser.directory == link


def test_dot_entries_are_hidden_until_all_files_is_enabled(tmp_path):
    (tmp_path / ".hidden").mkdir()
    assert ".hidden" not in [e.path.name for e in list_entries(tmp_path)]
    assert ".hidden" in [e.path.name for e in list_entries(tmp_path, show_all=True)]


def test_macos_app_bundle_is_selectable_as_a_file(tmp_path):
    bundle = tmp_path / "GZDoom.app"
    executable = bundle / "Contents" / "MacOS" / "gzdoom"
    executable.parent.mkdir(parents=True)
    executable.touch()
    browser = Browser(tmp_path, candidates=[tmp_path], suffixes=(".app",), app_bundles=True)

    assert len(browser.entries) == 1
    assert browser.entries[0].path == bundle
    assert browser.entries[0].is_dir is False
    assert browser.entries[0].display_name == "GZDoom.app"
    assert browser.open_selected() == bundle

    from couch_doom.sources import identify
    choice = identify(bundle)
    assert choice is not None and choice.path == executable


def test_missing_directory_is_an_empty_listing(tmp_path):
    assert list_entries(tmp_path / "gone") == []


def test_inaccessible_directory_is_an_empty_listing(monkeypatch, tmp_path):
    def denied(_directory):
        raise PermissionError("access denied")

    monkeypatch.setattr(filebrowser.os, "scandir", denied)
    assert list_entries(tmp_path) == []


def test_parent_stays_at_posix_root_and_can_leave_a_child(tmp_path):
    child = tmp_path / "child"
    child.mkdir()

    assert parent(child) == tmp_path
    assert parent(Path("/")) is None


def test_roots_put_home_first_and_deduplicate(tmp_path):
    assert roots(tmp_path, candidates=[tmp_path, Path("/")]) == [tmp_path, Path("/")]


def test_windows_drive_mask_lists_only_mounted_letters():
    assert _drive_roots((1 << 0) | (1 << 2)) == [Path("A:/"), Path("C:/")]


def test_browser_enters_directories_selects_files_and_returns_to_parent(tmp_path):
    child = tmp_path / "child"
    child.mkdir()
    (child / "doomrunner.exe").touch()
    browser = Browser(tmp_path, candidates=[tmp_path], names={"doomrunner.exe"})

    assert browser.open_selected() is None
    assert browser.directory == child
    assert browser.open_selected() == child / "doomrunner.exe"
    assert browser.back()
    assert browser.directory == tmp_path
    assert browser.selected == 0


def test_browser_toggle_all_resets_selection_and_change_root_clamps(tmp_path):
    home, other = tmp_path / "home", tmp_path / "other"
    home.mkdir()
    other.mkdir()
    (home / "notes.txt").touch()
    browser = Browser(home, candidates=[other], names={"launcher.exe"})

    browser.toggle_all()
    assert [entry.path.name for entry in browser.entries] == ["notes.txt"]
    browser.change_root(1)
    assert browser.directory == other
    browser.change_root(1)
    assert browser.directory == other
