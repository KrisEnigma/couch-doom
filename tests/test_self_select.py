from types import SimpleNamespace

import couch_doom.ui as ui

from couch_doom.self_select import is_self_selection


def test_matches_windows_executable_case_insensitively(tmp_path):
    executable = tmp_path / "CouchDoom.exe"

    assert is_self_selection(tmp_path / "COUCHDOOM.EXE", executable=executable, frozen=True, platform="win32")


def test_matches_extensionless_linux_executable(tmp_path):
    executable = tmp_path / "CouchDoom"

    assert is_self_selection(executable, executable=executable, frozen=True)


def test_matches_macos_app_bundle_not_only_inner_executable(tmp_path):
    bundle = tmp_path / "CouchDoom.app"
    executable = bundle / "Contents" / "MacOS" / "CouchDoom"
    executable.parent.mkdir(parents=True)
    executable.touch()

    assert is_self_selection(bundle, executable=executable, frozen=True, platform="darwin")


def test_source_run_does_not_match_python(tmp_path):
    python = tmp_path / "python"

    assert not is_self_selection(python, executable=python, frozen=False)


def test_self_selection_shows_toast_and_skips_launcher_detection(monkeypatch, tmp_path):
    executable = tmp_path / "CouchDoom"
    calls = []
    app = ui.App.__new__(ui.App)
    app.launchers = SimpleNamespace(add=lambda _path: calls.append("launcher") or None)
    app.theme = SimpleNamespace(label=(255, 100, 20))
    app.sfx = SimpleNamespace(play_secret=lambda: calls.append("secret"))
    monkeypatch.setattr(ui, "is_self_selection", lambda path: path == executable)
    monkeypatch.setattr(app, "_notify", lambda message, _color: calls.append(message))

    app._on_drop(executable)

    assert calls == ["Doomception! I’m already running.", "secret"]


def test_packaged_executable_is_in_default_browser_filter(monkeypatch, tmp_path):
    executable = tmp_path / "CouchDoom"
    app = ui.App.__new__(ui.App)
    app.browser_scroll = 0
    app.mode = "launcher"
    app.sfx = None
    monkeypatch.setattr(ui, "FROZEN", True)
    monkeypatch.setattr(ui.sys, "executable", str(executable))

    app._open_browser(tmp_path)

    assert executable.name in app.file_browser.names
