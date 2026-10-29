from pathlib import Path
from types import SimpleNamespace
import struct
import pytest

import couch_doom.sfx as sfx
from couch_doom.sfx import Sfx, _source_iwad


def write_wad(path: Path, lumps: dict[str, bytes]) -> None:
    body = bytearray()
    entries = bytearray()
    for name, data in lumps.items():
        entries += struct.pack("<ii8s", 12 + len(body), len(data), name.encode())
        body += data
    path.write_bytes(b"IWAD" + struct.pack("<ii", len(lumps), 12 + len(body)) + body + entries)


def options(*paths):
    return SimpleNamespace(presets=[SimpleNamespace(iwad=path) for path in paths])


@pytest.mark.parametrize("filename", ["hexen.wad", "strife1.wad", "unknown.wad"])
def test_non_doom_wad_names_are_not_treated_as_doom_menu_audio(tmp_path, filename):
    candidate = tmp_path / filename
    write_wad(candidate, {"DSPSTOP": b"shared"})

    assert _source_iwad(options(candidate)) is None


def test_prefers_most_used_recognized_doom_family_iwad(tmp_path):
    hexen = tmp_path / "hexen.wad"
    doom = tmp_path / "doom2.wad"
    write_wad(hexen, {"DSPSTOP": b"hexen"})
    write_wad(doom, {"DSPSTOP": b"doom"})

    assert _source_iwad(options(hexen, doom, doom)) == doom


def test_freedoom_iwad_is_a_doom_family_audio_source(tmp_path):
    freedoom = tmp_path / "freedoom2.wad"
    write_wad(freedoom, {"DSPSTOP": b"freedoom"})

    assert _source_iwad(options(freedoom)) == freedoom


def test_bundled_freedoom_menu_sounds_load_without_iwad(monkeypatch):
    requested = []

    class FakeSound:
        def set_volume(self, _volume):
            pass

        def play(self):
            pass

    monkeypatch.setattr(sfx.pygame.mixer, "Sound", lambda file: requested.append(file) or FakeSound())
    result = Sfx(options(), SimpleNamespace(play=lambda _sound: None))

    assert set(result.sounds) == {"move", "confirm", "open", "close", "error", "secret"}
    assert len(requested) == 6
    assert all(isinstance(path, Path) and path.is_file() for path in requested)


@pytest.mark.parametrize(("has_getpow", "expected_tag"), [(True, 2), (False, None)])
def test_easter_egg_sound_uses_powerup_pickup_then_bundled(monkeypatch, tmp_path, has_getpow, expected_tag):
    iwad = tmp_path / "doom2.wad"
    iwad.touch()

    class FakeWad:
        def __init__(self, lumps):
            self.lumps = lumps
            self.closed = False

        def lump(self, name):
            return self.lumps.get(name)

        def close(self):
            self.closed = True

    class FakeSound:
        def __init__(self, data):
            self.data = data

        def set_volume(self, _volume):
            pass

        def play(self):
            pass

    def dmx(tag):
        return struct.pack("<HHI", 3, 11025, 20) + bytes([tag]) * 20

    loaded = []
    monkeypatch.setattr(sfx, "_source_iwad", lambda _opts: iwad)
    lumps = {"DSPSTOP": dmx(1)}
    if has_getpow:
        lumps["DSGETPOW"] = dmx(2)
        lumps["DSSECRET"] = dmx(4)
        lumps["DSITMBK"] = dmx(3)
    else:
        lumps["DSITMBK"] = dmx(3)
    monkeypatch.setattr(sfx, "open_archive", lambda _path: FakeWad(lumps))
    monkeypatch.setattr(sfx.pygame.mixer, "Sound", lambda file: loaded.append(file) or FakeSound(
        file.getvalue() if hasattr(file, "getvalue") else file.read_bytes()))

    result = Sfx(options(iwad), SimpleNamespace(play=lambda _sound: None))

    if expected_tag is None:
        assert result.sounds["secret"].data == (sfx.FREEDOOM_SOUNDS / "dsgetpow.wav").read_bytes()
    else:
        assert result.sounds["secret"].data.endswith(bytes([expected_tag]) * 20)
    assert len(loaded) == 6
