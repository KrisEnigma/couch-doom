from pathlib import Path
from types import SimpleNamespace

from couch_doom import ui


def test_engine_soundfont_lookup_is_reused_for_the_same_engine(monkeypatch):
    app = ui.App.__new__(ui.App)
    app._engine_soundfonts = {}
    engine = SimpleNamespace(
        id="uzdoom",
        name="UZDoom",
        path=Path("D:/Standalone/UZDoom/uzdoom.exe"),
        config_dir=Path("D:/Standalone/UZDoom/config"),
    )
    expected = Path("D:/Standalone/UZDoom/soundfonts/uzdoom.sf2")
    calls = []
    monkeypatch.setattr(ui, "find_engine_soundfont", lambda item: calls.append(item) or expected)

    assert app._engine_soundfont_for(engine) == expected
    assert app._engine_soundfont_for(engine) == expected
    assert calls == [engine]
