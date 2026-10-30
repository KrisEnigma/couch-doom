import sys
from pathlib import Path
from types import SimpleNamespace

from couch_doom import easter_eggs, ui
from couch_doom.filebrowser import Browser
from couch_doom.gamepad import Action


def test_reacts_to_self_executable_but_not_install_folder_by_default(monkeypatch, tmp_path):
    executable = tmp_path / "CouchDoom.exe"
    executable.touch()
    monkeypatch.setattr(easter_eggs, "self_paths", lambda: {executable.resolve()})

    assert easter_eggs.react_to_pick(executable).message == easter_eggs.DOOMCEPTION_MESSAGE
    assert easter_eggs.react_to_pick(tmp_path) is None


def test_install_folder_is_a_fallback_reaction(monkeypatch, tmp_path):
    monkeypatch.setattr(easter_eggs, "self_folders", lambda: {tmp_path.resolve()})

    assert easter_eggs.react_to_folder(tmp_path).message == easter_eggs.DOOMCEPTION_MESSAGE
    assert easter_eggs.react_to_folder(tmp_path / "missing") is None


def test_reacts_to_app_bundle(monkeypatch, tmp_path):
    bundle = tmp_path / "CouchDoom.app"
    executable = bundle / "Contents" / "MacOS" / "CouchDoom"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setattr(easter_eggs, "self_paths", lambda: {executable.resolve()})

    assert easter_eggs.react_to_pick(bundle).message == easter_eggs.DOOMCEPTION_MESSAGE


def test_same_named_executables_are_all_visible_in_the_browser(monkeypatch, tmp_path):
    home = tmp_path / "home"
    other = tmp_path / "other"
    home.mkdir()
    other.mkdir()
    (other / "CouchDoom.exe").touch()
    self_exe = home / "CouchDoom.exe"
    self_exe.touch()
    monkeypatch.setattr(easter_eggs, "self_paths", lambda: {self_exe.resolve()})

    assert "CouchDoom.exe" in [e.path.name for e in Browser(home, candidates=[home],
                                                            names={"CouchDoom.exe"}).entries]
    assert "CouchDoom.exe" in [e.path.name for e in Browser(other, candidates=[other],
                                                            names={"CouchDoom.exe"}).entries]


def test_same_named_executable_triggers_easter_egg_by_name(monkeypatch, tmp_path):
    running = tmp_path / "installed" / "CouchDoom.exe"
    copied = tmp_path / "other" / "CouchDoom.exe"
    copied.parent.mkdir()
    copied.touch()
    monkeypatch.setattr(easter_eggs, "FROZEN", True)
    monkeypatch.setattr(easter_eggs, "self_paths", lambda: {running.resolve()})

    assert easter_eggs.react_to_pick(copied).message == easter_eggs.DOOMCEPTION_MESSAGE


def test_couchdoom_executable_name_is_recognized_without_frozen_flag(monkeypatch, tmp_path):
    copied = tmp_path / "other" / "CouchDoom.exe"
    copied.parent.mkdir()
    copied.touch()
    monkeypatch.setattr(easter_eggs, "FROZEN", False)

    assert easter_eggs.react_to_pick(copied).message == easter_eggs.DOOMCEPTION_MESSAGE


def test_packaged_executable_is_found_from_the_install_root(monkeypatch, tmp_path):
    executable = tmp_path / "CouchDoom.exe"
    executable.touch()
    monkeypatch.setattr(easter_eggs, "FROZEN", True)
    monkeypatch.setattr(easter_eggs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(easter_eggs.sys, "executable", str(tmp_path / "_internal" / "python.exe"))
    monkeypatch.setattr(easter_eggs.sys, "frozen", False, raising=False)

    browser = Browser(tmp_path, candidates=[tmp_path], include=easter_eggs.self_matcher())

    assert executable in [entry.path for entry in browser.entries]


def test_browser_matcher_resolves_self_paths_once(monkeypatch, tmp_path):
    self_exe = tmp_path / "CouchDoom.exe"
    self_exe.touch()
    for i in range(200):
        (tmp_path / f"file{i}.txt").touch()
    calls = 0

    def self_paths():
        nonlocal calls
        calls += 1
        return {self_exe.resolve()}

    monkeypatch.setattr(easter_eggs, "self_paths", self_paths)
    browser = Browser(tmp_path, candidates=[tmp_path], include=easter_eggs.self_matcher())
    assert calls == 1
    assert "CouchDoom.exe" in [entry.path.name for entry in browser.entries]

    browser.refresh()
    assert calls == 1


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


def test_self_paths_ignores_loose_couch_prefixed_argv(monkeypatch, tmp_path):
    script = tmp_path / "couch-something.py"
    script.touch()
    monkeypatch.delenv("COUCHDOOM_SELF", raising=False)
    monkeypatch.setattr(easter_eggs.sys, "argv", [str(script)])
    monkeypatch.setattr(easter_eggs.shutil, "which", lambda _name: None)

    assert script.resolve() not in easter_eggs.self_paths()


def test_self_paths_accepts_known_argv_names(monkeypatch, tmp_path):
    script = tmp_path / "couch_doom_entry.py"
    script.touch()
    monkeypatch.delenv("COUCHDOOM_SELF", raising=False)
    monkeypatch.setattr(easter_eggs.sys, "argv", [str(script)])
    monkeypatch.setattr(easter_eggs.shutil, "which", lambda _name: None)

    assert script.resolve() in easter_eggs.self_paths()


def _drop_app(calls, *, launchers=True, add_result=None):
    app = ui.App.__new__(ui.App)
    app.launchers = SimpleNamespace(add=lambda path: add_result) if launchers else None
    app.theme = SimpleNamespace(label=(255, 100, 20))
    app.sfx = SimpleNamespace(play=lambda name: calls.append(("sound", name)))
    app._choose = lambda choice, added=False: calls.append(("choose", choice, added))
    app._notify = lambda message, _color: calls.append(("notify", message))
    app._sound = lambda name: calls.append(("error-sound", name))
    return app


def test_portable_folder_with_launcher_is_not_swallowed_by_doomception(monkeypatch, tmp_path):
    portable = tmp_path / "portable"
    portable.mkdir()
    executable = portable / "CouchDoom.exe"
    executable.touch()
    (portable / "DoomRunner.exe").touch()
    (portable / "options.json").touch()
    monkeypatch.setattr(easter_eggs, "self_paths", lambda: {executable.resolve()})
    monkeypatch.setattr(easter_eggs, "self_folders", lambda: {portable.resolve()})
    calls = []
    app = _drop_app(calls, add_result="choice")

    app._on_drop(portable)

    assert calls == [("choose", "choice", True)]


def test_install_folder_falls_back_to_doomception_when_no_launcher_is_found(monkeypatch, tmp_path):
    portable = tmp_path / "portable"
    portable.mkdir()
    executable = portable / "CouchDoom.exe"
    executable.touch()
    monkeypatch.setattr(easter_eggs, "self_paths", lambda: {executable.resolve()})
    monkeypatch.setattr(easter_eggs, "self_folders", lambda: {portable.resolve()})
    calls = []
    app = _drop_app(calls, add_result=None)

    app._on_drop(portable)

    assert ("notify", easter_eggs.DOOMCEPTION_MESSAGE) in calls
    assert ("sound", "secret") in calls
    assert not any(call[0] == "error-sound" for call in calls)


def test_exact_self_executable_drop_fires_egg_before_launcher_detection(monkeypatch, tmp_path):
    executable = tmp_path / "CouchDoom.exe"
    executable.touch()
    monkeypatch.setattr(easter_eggs, "self_paths", lambda: {executable.resolve()})
    calls = []
    app = _drop_app(calls, launchers=False)
    app.launchers = SimpleNamespace(add=lambda _path: (_ for _ in ()).throw(AssertionError("launcher detection")))

    app._on_drop(executable)

    assert ("notify", easter_eggs.DOOMCEPTION_MESSAGE) in calls


def test_install_folder_egg_still_shows_without_any_launchers(monkeypatch, tmp_path):
    portable = tmp_path / "portable"
    portable.mkdir()
    executable = portable / "CouchDoom.exe"
    executable.touch()
    monkeypatch.setattr(easter_eggs, "self_paths", lambda: {executable.resolve()})
    monkeypatch.setattr(easter_eggs, "self_folders", lambda: {portable.resolve()})
    calls = []
    app = _drop_app(calls, launchers=False)

    app._on_drop(portable)

    assert ("notify", easter_eggs.DOOMCEPTION_MESSAGE) in calls


def test_browser_confirmation_keeps_place_when_self_is_selected(monkeypatch, tmp_path):
    executable = tmp_path / "CouchDoom"
    executable.touch()
    app = ui.App.__new__(ui.App)
    app.file_browser = Browser(tmp_path, candidates=[tmp_path], include=lambda entry: Path(entry.path) == executable)
    app.file_browser.selected = next(i for i, e in enumerate(app.file_browser.entries) if e.path == executable)
    app.browser_scroll = 0
    app.mode = "browse"
    app.sfx = SimpleNamespace(play=lambda _name: None)
    app.theme = SimpleNamespace(label=(255, 100, 20))
    app.launchers = SimpleNamespace(add=lambda _path: (_ for _ in ()).throw(AssertionError("launcher detection")))
    monkeypatch.setattr(ui.easter_eggs, "react_to_pick", lambda path: easter_eggs.Reaction("Doomception!"))
    messages = []
    monkeypatch.setattr(app, "_notify", lambda message, _color: messages.append(message))

    app._browser_action(Action.CONFIRM)

    assert app.mode == "browse"
    assert app.file_browser.directory == tmp_path
    assert messages == ["Doomception!"]
