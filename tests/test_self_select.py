from pathlib import Path
from types import SimpleNamespace

import couch_doom.ui as ui

from couch_doom.self_select import same_path


def test_windows_path_matching_is_case_insensitive(tmp_path):
    assert same_path(tmp_path / "COUCHDOOM.EXE", tmp_path / "CouchDoom.exe", platform="win32")


def test_posix_path_matching_is_case_sensitive(tmp_path):
    assert not same_path(tmp_path / "COUCHDOOM", tmp_path / "couchdoom", platform="linux")


def test_macos_path_matching_is_case_insensitive(tmp_path):
    assert same_path(tmp_path / "COUCHDOOM", tmp_path / "couchdoom", platform="darwin")


def test_self_selection_shows_toast_and_skips_launcher_detection(monkeypatch, tmp_path):
    executable = tmp_path / "CouchDoom"
    calls = []
    app = ui.App.__new__(ui.App)
    app.launchers = SimpleNamespace(add=lambda _path: calls.append("launcher") or None)
    app.theme = SimpleNamespace(label=(255, 100, 20))
    app.sfx = SimpleNamespace(play=lambda name: calls.append(name))
    monkeypatch.setattr(ui.easter_eggs, "react_to_pick",
                        lambda path: ui.easter_eggs.Reaction(ui.easter_eggs.DOOMCEPTION_MESSAGE)
                        if path == executable else None)
    monkeypatch.setattr(app, "_notify", lambda message, _color: calls.append(message))

    app._on_drop(executable)

    assert calls == ["Doomception! I’m already running.", "secret"]


def test_packaged_executable_is_listed_in_default_browser_filter(monkeypatch, tmp_path):
    executable = tmp_path / "CouchDoom"
    executable.touch()
    app = ui.App.__new__(ui.App)
    app.browser_scroll = 0
    app.mode = "launcher"
    app.sfx = None
    monkeypatch.setattr(ui.easter_eggs, "self_paths", lambda: {executable.resolve()})

    app._open_browser(tmp_path)

    assert executable.name in [entry.path.name for entry in app.file_browser.entries]


def test_open_browser_starts_at_self_location(monkeypatch, tmp_path):
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr(ui.config, "self_location", lambda: install)
    monkeypatch.setattr(ui.easter_eggs, "self_paths", lambda: set())
    app = ui.App.__new__(ui.App)
    app.sfx = None

    app._open_browser()

    assert app.file_browser.directory == install
    assert app.file_browser.roots[0] == install
    assert Path.home() in app.file_browser.roots


def test_open_browser_starts_at_source_project_when_not_packaged(monkeypatch, tmp_path):
    project = tmp_path / "couch-doom"
    project.mkdir()
    monkeypatch.setattr(ui.config, "self_location", lambda: None)
    monkeypatch.setattr(ui.config, "SOURCE_TREE", True)
    monkeypatch.setattr(ui.config, "PROJECT_ROOT", project)
    monkeypatch.setattr(ui.easter_eggs, "self_paths", lambda: set())
    app = ui.App.__new__(ui.App)
    app.sfx = None

    app._open_browser()

    assert app.file_browser.directory == project


def test_open_browser_falls_back_to_home_without_self_location(monkeypatch):
    monkeypatch.setattr(ui.config, "self_location", lambda: None)
    monkeypatch.setattr(ui.config, "SOURCE_TREE", False)
    monkeypatch.setattr(ui.easter_eggs, "self_paths", lambda: set())
    app = ui.App.__new__(ui.App)
    app.sfx = None

    app._open_browser()

    assert app.file_browser.directory == Path.home()


def test_open_browser_lists_its_own_executable_without_a_name_filter(monkeypatch, tmp_path):
    executable = tmp_path / "CouchDoom.exe"
    executable.touch()
    monkeypatch.setattr(ui.config, "self_location", lambda: tmp_path)
    monkeypatch.setattr(ui.easter_eggs, "self_paths", lambda: {executable.resolve()})
    app = ui.App.__new__(ui.App)
    app.sfx = None

    app._open_browser()

    assert executable in [entry.path for entry in app.file_browser.entries]


def test_open_browser_uses_executable_name_for_all_matching_files(monkeypatch, tmp_path):
    install_exe = tmp_path / "CouchDoom.exe"
    install_exe.touch()
    copy_dir = tmp_path / "other"
    copy_dir.mkdir()
    copied_exe = copy_dir / install_exe.name
    copied_exe.touch()
    monkeypatch.setattr(ui.config, "FROZEN", True)
    monkeypatch.setattr(ui.config, "self_location", lambda: tmp_path)
    monkeypatch.setattr(ui.config, "SOURCE_TREE", False)
    monkeypatch.setattr(ui.easter_eggs, "self_paths", lambda: {install_exe.resolve()})
    app = ui.App.__new__(ui.App)
    app.sfx = None

    app._open_browser()
    other_browser = ui.FileBrowser(home=copy_dir, candidates=[copy_dir], names=app.file_browser.names)

    assert install_exe.name in app.file_browser.names
    assert copied_exe in [entry.path for entry in other_browser.entries]


def test_open_browser_always_lists_couchdoom_executable_name(monkeypatch, tmp_path):
    monkeypatch.setattr(ui.config, "FROZEN", False)
    monkeypatch.setattr(ui.config, "SOURCE_TREE", False)
    monkeypatch.setattr(ui.config, "self_location", lambda: tmp_path)
    monkeypatch.setattr(ui.easter_eggs, "self_paths", lambda: set())
    app = ui.App.__new__(ui.App)
    app.sfx = None

    app._open_browser()

    assert "couchdoom.exe" in {name.casefold() for name in app.file_browser.names}
