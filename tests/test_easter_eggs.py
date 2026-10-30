import sys
from pathlib import Path
from types import SimpleNamespace

from couch_doom import easter_eggs, ui
from couch_doom.filebrowser import Browser
from couch_doom.gamepad import Action


def test_reacts_to_self_executable_and_install_folder(monkeypatch, tmp_path):
    executable = tmp_path / "CouchDoom.exe"
    executable.touch()
    monkeypatch.setattr(easter_eggs, "self_paths", lambda: {executable.resolve()})
    assert easter_eggs.react_to_pick(executable).message == easter_eggs.DOOMCEPTION_MESSAGE
    assert easter_eggs.react_to_pick(tmp_path).message == easter_eggs.DOOMCEPTION_MESSAGE


def test_reacts_to_app_bundle(monkeypatch, tmp_path):
    bundle = tmp_path / "CouchDoom.app"
    executable = bundle / "Contents" / "MacOS" / "CouchDoom"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setattr(easter_eggs, "self_paths", lambda: {executable.resolve()})
    assert easter_eggs.react_to_pick(bundle).message == easter_eggs.DOOMCEPTION_MESSAGE


def test_unrelated_same_name_does_not_match_browser_entry(monkeypatch, tmp_path):
    home = tmp_path / "home"
    other = tmp_path / "other"
    home.mkdir()
    other.mkdir()
    (other / "CouchDoom.exe").touch()
    self_exe = home / "CouchDoom.exe"
    self_exe.touch()
    monkeypatch.setattr(easter_eggs, "self_paths", lambda: {self_exe.resolve()})

    assert "CouchDoom.exe" in [e.path.name for e in Browser(home, candidates=[home],
                                                            include=easter_eggs.is_self_entry).entries]
    assert "CouchDoom.exe" not in [e.path.name for e in Browser(other, candidates=[other],
                                                                include=easter_eggs.is_self_entry).entries]


def test_does_not_react_to_python_or_unrelated_files(monkeypatch, tmp_path):
    monkeypatch.setattr(easter_eggs, "self_paths", lambda: {(tmp_path / "CouchDoom.exe").resolve()})
    assert easter_eggs.react_to_pick(Path(sys.executable)) is None
    assert easter_eggs.react_to_pick(tmp_path / "notes.txt") is None


def test_self_paths_never_include_the_python_interpreter(monkeypatch, tmp_path):
    target = tmp_path / "couch-doom"
    target.touch()
    monkeypatch.setenv("COUCHDOOM_SELF", str(target))
    paths = easter_eggs.self_paths()
    assert target.resolve() in paths
    assert Path(sys.executable).resolve() not in paths


def test_browser_confirmation_keeps_place_when_self_is_selected(monkeypatch, tmp_path):
    executable = tmp_path / "CouchDoom"
    executable.touch()
    app = ui.App.__new__(ui.App)
    app.file_browser = Browser(tmp_path, candidates=[tmp_path], include=lambda entry: Path(entry.path) == executable)
    app.file_browser.selected = next(i for i, e in enumerate(app.file_browser.entries) if e.path == executable)
    app.browser_scroll = 0
    app.mode = "browse"
    app.sfx = SimpleNamespace(play_secret=lambda: None)
    app.theme = SimpleNamespace(label=(255, 100, 20))
    app.launchers = SimpleNamespace(add=lambda _path: (_ for _ in ()).throw(AssertionError("launcher detection")))
    monkeypatch.setattr(ui.easter_eggs, "react_to_pick", lambda path: easter_eggs.Reaction("Doomception!"))
    messages = []
    monkeypatch.setattr(app, "_notify", lambda message, _color: messages.append(message))

    app._browser_action(Action.CONFIRM)

    assert app.mode == "browse"
    assert app.file_browser.directory == tmp_path
    assert messages == ["Doomception!"]
