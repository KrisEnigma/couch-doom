"""End-to-end smoke test, run in CI on Windows and Linux: fake DoomRunner, qZDL and bare UZDoom setups in each
OS's real settings folders, then discovery, command lines and one rendered UI frame.

    python tests/smoke.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import struct
import sys
import tempfile
import time
import zipfile
from pathlib import Path

root = Path(tempfile.mkdtemp(prefix="couchdoom-smoke-"))
if os.name == "nt":
    os.environ["APPDATA"] = str(root / "Roaming")
    os.environ["LOCALAPPDATA"] = str(root / "Local")
    dr_dir, zdl_dir = root / "Local" / "DoomRunner", root / "Roaming" / "Vectec Software"
else:
    os.environ["HOME"] = str(root)
    os.environ["XDG_DATA_HOME"] = str(root / "data")
    os.environ["XDG_CONFIG_HOME"] = str(root / "config")
    dr_dir, zdl_dir = root / "data" / "DoomRunner", root / "config" / "Vectec Software"
os.environ["COUCHDOOM_NO_UPDATE_CHECK"] = "1"  # tests never touch the network
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

exe = ".exe" if os.name == "nt" else ""
games = root / "games"
games.mkdir()
for name in (f"dsda-doom{exe}", f"uzdoom{exe}", "freedoom2.wad", "mod.pk3", "fix.deh"):
    (games / name).write_bytes(b"")

dr_dir.mkdir(parents=True)
(dr_dir / "options.json").write_text(json.dumps({
    "engines": {"default_engine": "dsda", "engine_list": [
        {"id": "dsda", "name": "DSDA-Doom", "path": str(games / f"dsda-doom{exe}"), "family": "PrBoom"},
        {"id": "uz", "name": "UZDoom", "path": str(games / f"uzdoom{exe}")}]},
    "options_storage": {"compat_opts": 2, "gameplay_opts": 2, "launch_opts": 2, "video_opts": 2, "audio_opts": 2},
    "presets": [
        {"separator": True, "name": "--- Smoke ---"},
        {"name": "DSDA", "selected_engine": "dsda", "selected_IWAD": str(games / "freedoom2.wad"),
         "mods": [{"path": str(games / "fix.deh"), "checked": True}, {"path": str(games / "mod.pk3"), "checked": True}],
         "alternative_paths": {"save_dir": str(games / "saves")},
         "compatibility_options": {"compat_mode": 9},
         "gameplay_options": {"pistol_start": True, "allow_cheats": True}},
        {"name": "UZDoom", "selected_engine": "uz", "selected_IWAD": str(games / "freedoom2.wad"),
         "mods": [{"cmd_argument": True, "value": "+fov 110", "checked": True}],
         "gameplay_options": {"allow_cheats": True}},
    ],
}), encoding="utf-8")

zdl_dir.mkdir(parents=True)
(zdl_dir / "qZDL.ini").write_text(f"""[zdl.ports]
p0n=DSDA-Doom
p0f={games / f"dsda-doom{exe}"}
[zdl.iwads]
i0n=Freedoom
i0f={games / "freedoom2.wad"}
[zdl.save]
port=DSDA-Doom
iwad=Freedoom
file0={games / "mod.pk3"}
""", encoding="utf-8")


def wad(path: Path, lumps: list[str], magic: bytes = b"IWAD", data: dict[str, bytes] | None = None) -> None:
    body, entries = b"", b""
    for name in lumps:
        blob = (data or {}).get(name, b"")
        entries += struct.pack("<ii8s", 12 + len(body), len(blob), name.encode())
        body += blob
    path.write_bytes(magic + struct.pack("<ii", len(lumps), 12 + len(body)) + body + entries)


# A bare UZDoom: its iwadinfo names the IWADs, its ini says where to look.
port, wads = root / "port", root / "wads"
port.mkdir()
wads.mkdir()
(port / f"uzdoom{exe}").write_bytes(b"")
with zipfile.ZipFile(port / "game_support.pk3", "w") as zf:
    zf.writestr("iwadinfo.txt", """
IWad { Name = "Hexen: Deathkings of the Dark Citadel" Required = "Hexen: Beyond Heretic" MustContain = "TITLE", "MAP60" }
IWad { Name = "Freedoom: Phase 2" MustContain = "MAP01", "FREEDOOM" }  // comment
Names { "freedoom2.wad" "hexdd.wad" "doom.wad" }
Order { "Freedoom: Phase 2" "Hexen: Deathkings of the Dark Citadel" }
""")
wad(port / "freedoom2.wad", ["MAP01", "FREEDOOM"])
wad(wads / "hexdd.wad", ["TITLE", "MAP60"])  # needs Hexen, which isn't there: the port hides it
(wads / "doom.wad").write_bytes(b"not a wad")
wad(wads / "own.iwad", ["IWADINFO"], data={"IWADINFO": b'IWad { Name = "Own Game" MustContain = "MAP01" }'})
ini_dir = port if os.name == "nt" else root / "config" / "uzdoom"
ini_dir.mkdir(parents=True, exist_ok=True)
(ini_dir / ("uzdoom_portable.ini" if os.name == "nt" else "uzdoom.ini")).write_text(
    f"[IWADSearch.Directories]\nPath=$PROGDIR\nPath={wads}\nPath=$COUCHDOOM_UNSET\n[GlobalSettings]\ni_searchdistributors=false\n")

import pygame  # noqa: E402
from couch_doom.launch import build_command  # noqa: E402
from couch_doom.options import Preset  # noqa: E402
from couch_doom.readme import find_readme  # noqa: E402
from couch_doom.sources import discover, identify, load_choice  # noqa: E402
from couch_doom.state import State  # noqa: E402
from couch_doom.ui import App  # noqa: E402

found = {c.source.key: c for c in discover()}
assert {"doomrunner", "zdl"} <= found.keys(), f"launchers not discovered: {sorted(found)}"

dr = load_choice(found["doomrunner"])
argv = {p.name: build_command(dr, p).argv[1:] for p in dr.presets}
g = str(games)
assert argv["DSDA"] == ["-iwad", f"{g}{os.sep}freedoom2.wad", "-deh", f"{g}{os.sep}fix.deh", "-file", f"{g}{os.sep}mod.pk3",
                        "-save", f"{g}{os.sep}saves", "-pistolstart", "-complevel", "9"], argv["DSDA"]
assert argv["UZDoom"] == ["-iwad", f"{g}{os.sep}freedoom2.wad", "+fov", "110", "+sv_cheats", "1"], argv["UZDoom"]

zdl = load_choice(found["zdl"])
assert build_command(zdl, zdl.presets[0]).argv[1:] == ["-iwad", f"{g}{os.sep}freedoom2.wad", "-file", f"{g}{os.sep}mod.pk3"]

uz_choice = identify(port / f"uzdoom{exe}")
assert uz_choice and uz_choice.source.key == "gzdoom" and uz_choice.name == "UZDoom", uz_choice
uz = load_choice(uz_choice)
assert [(p.name, p.iwad.name) for p in uz.presets] == [("Freedoom: Phase 2", "freedoom2.wad"), ("Own Game", "own.iwad")], uz.presets
assert build_command(uz, uz.presets[0]).argv[1:] == ["-iwad", str(port / "freedoom2.wad")]
found["gzdoom"] = uz_choice

dl_db = root / "DoomLauncher" / "DoomLauncher.sqlite"
dl_db.parent.mkdir()
settings = "SourcePortID, IWadID, SettingsMap, SettingsSkill, SettingsExtraParams, SettingsExtraParamsOnly, SettingsFiles, SettingsSpecificFiles"
with sqlite3.connect(dl_db) as con:
    con.executescript(f"""
        create table Configuration (Name, Value);
        create table GameFiles (GameFileID, FileName, Title, {settings}, SettingsFilesSourcePort, SettingsSaved, LastPlayed);
        create table SourcePorts (SourcePortID, Name, Executable, Directory, SupportedExtensions, ExtraParameters, SettingsFiles, LaunchType);
        create table IWads (IWadID, GameFileID);
        create table GameProfiles (GameProfileID, GameFileID, Name, {settings});
        create table Tags (TagID, Name);
        create table TagMapping (FileID, TagID);
        insert into SourcePorts values (1, 'UZDoom', 'uzdoom.exe', '{port}', '.wad,.pk3', '', '', 0);
        insert into GameFiles (GameFileID, FileName, Title, SettingsSaved, LastPlayed) values
            (1, '{g}{os.sep}mod.pk3', 'Tagged', 1, null),
            (2, '{g}{os.sep}fix.deh', 'Played', 0, '2026-01-01'),
            (3, '{g}{os.sep}music.wad', 'Support file', 0, null);
        insert into Tags values (1, 'Megawads');
        insert into TagMapping values (1, 1);
    """)
con.close()
dl = load_choice(identify(dl_db))
assert [(p.section, p.name) for p in dl.presets] == [("Megawads", "Tagged"), ("Untagged", "Played")], dl.presets

bare = Preset(name="Doom II", section="", engine_id="", iwad=Path(g) / "DOOM2.WAD", mods=[])
assert (r := find_readme(bare)) and r.author == "id Software" and r.year == "1994", r
assert find_readme(Preset(name="Mod", section="", engine_id="", iwad=Path(g) / "DOOM2.WAD", mods=[Path(g) / "mod.pk3"])) is None

from couch_doom.music import TITLEMAP_MUSIC_RE, TITLEMUSIC_RE  # noqa: E402

bw_info = b'map TITLEMAP "Love"\r\n{\r\n\ttitlepatch = "CWILV23" // note\r\n\tmusic = WONDER\r\n\tpar = 150\r\n}'
assert TITLEMAP_MUSIC_RE.search(bw_info)[1] == b"WONDER"
assert TITLEMAP_MUSIC_RE.search(b'map titlemap "x" { music = "D_TITLE" }')[1] == b"D_TITLE"
assert TITLEMUSIC_RE.search(b"gameinfo { titlemusic = intro; }")[1] == b"intro"
assert TITLEMUSIC_RE.search(b'titlemusic = "music/theme.ogg"')[1] == b"music/theme.ogg"

from couch_doom.gamepad import Input  # noqa: E402

pygame.init()
inp = Input()
inp._pad_last = True
inp.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=0, unicode="a", scancode=0), 0.0)
assert not inp._pad_last
inp.handle(pygame.event.Event(pygame.JOYAXISMOTION, instance_id=99, axis=0, value=0.1), 0.0)
assert not inp._pad_last  # drift doesn't count
inp.handle(pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, instance_id=99, button=pygame.CONTROLLER_BUTTON_A), 0.0)
assert inp._pad_last
inp.handle(pygame.event.Event(pygame.MOUSEMOTION, pos=(1, 1), rel=(1, 1), buttons=(0, 0, 0)), 0.0)
assert inp._pad_last  # moving the mouse doesn't count, only clicks
inp.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(1, 1), button=1), 0.0)
assert not inp._pad_last and not inp.pad_mode

from couch_doom import update as upd  # noqa: E402
from couch_doom.gamepad import Action  # noqa: E402

assert upd.is_newer("0.10.0", "0.9.0") and not upd.is_newer("0.6.0", "0.6.0") and not upd.is_newer("junk", "0.6.0")
notes_md = "**Download**\n- a\n\n**New in 0.7.0**\n- Thing with `code` and [a link](http://x).\n- Second\n\n**New in 0.6.0**\n- Old\n"
assert upd.whats_new(notes_md, "0.7.0") == ["Thing with code and a link.", "Second"], upd.whats_new(notes_md, "0.7.0")
assert upd.check("0.1.0") is None  # disabled by the env var set above

state = State(root / "state.json")
app = App(dr, state, windowed=True)
now = time.monotonic()
app._open_update({"version": "9.9.9", "current": "0.6.0", "url": "https://github.com/KrisEnigma/couch-doom/releases", "notes": ["x"]})
app._draw(now)
assert app.mode == "update" and app.update_sel == 1
app._on_action(Action.BACK, now)
assert app.mode == "list" and app.update_choice == "later" and state.update_skip is None
app._open_update({"version": "9.9.9", "current": "0.6.0", "url": "", "notes": []})
app._on_action(Action.DOWN, now)
app._on_action(Action.CONFIRM, now)
assert app.mode == "list" and state.update_skip == "9.9.9" and State(root / "state.json").update_skip == "9.9.9"
for _ in range(3):
    pygame.event.pump()
    app.tick(now, 1 / 60)
    app._draw(now)
from couch_doom import log as clog  # noqa: E402

lp = root / "log" / "couch-doom.log"
engine = [sys.executable, "-c", "import sys; print('boom ' * 9000, flush=True); print('last line', file=sys.stderr); sys.exit(3)"]
run = clog.spawn(engine, None, dict(os.environ), "Fake", "fake cmd")
code, secs = run.wait(lp)
text = lp.read_text(encoding="utf-8")
assert code == 3 and clog.closed_early(code, secs) and not clog.closed_early(0, 60) and clog.closed_early(0, 2)
assert "launch: Fake" in text and "exit: 3" in text and "last line" in text and "fake cmd" in text
assert len(text) < clog.OUTPUT_TAIL + 2048, len(text)  # 45 KB of output was cut to the tail
for _ in range(80):
    clog.write("filler", "x" * 4000, lp)
assert lp.stat().st_size <= clog.MAX_BYTES + 5000 and lp.with_name(lp.name + ".1").exists()
assert lp.stat().st_size + lp.with_name(lp.name + ".1").stat().st_size < 2 * clog.MAX_BYTES + 10000
clog.write("unwritable", "", root / "state.json" / "nope.log")  # parent is a file: must not raise
try:
    clog.spawn([str(root / "no-such-engine.exe")], None, dict(os.environ), "Missing", "x")
    raise AssertionError("expected OSError")
except OSError:
    pass
assert clog.last_line("a\n\n  Error: no display  \n") == "Error: no display" and clog.last_line("") == ""
fuse = "AppImages require FUSE to run."
assert clog.needs_extract_retry(["/o/Nugget.AppImage", "-iwad", "x"], {}, fuse, 1, 0.2)
assert clog.needs_extract_retry(["wrapper", "/o/n.appimage"], {}, fuse, 1, 0.2)
assert not clog.needs_extract_retry(["/o/nugget-doom"], {}, fuse, 1, 0.2)  # not an AppImage
assert not clog.needs_extract_retry(["/o/n.AppImage"], {}, "some other error", 1, 0.2)
assert not clog.needs_extract_retry(["/o/n.AppImage"], {"APPIMAGE_EXTRACT_AND_RUN": "1"}, fuse, 1, 0.2)  # no retry loop
assert not clog.needs_extract_retry(["/o/n.AppImage"], {}, fuse, 0, 0.2)
from couch_doom.launch import engine_environ  # noqa: E402

pyi = {"PATH": "/usr/bin", "LD_LIBRARY_PATH": "/app/_internal:/mine", "LD_LIBRARY_PATH_ORIG": "/mine", "LANG": "C"}
assert engine_environ(pyi, True) == {"PATH": "/usr/bin", "LD_LIBRARY_PATH": "/mine", "LANG": "C"}
assert "LD_LIBRARY_PATH" not in engine_environ({"LD_LIBRARY_PATH": "/app/_internal"}, True)  # there was none originally
assert engine_environ(pyi, False) == pyi  # running from source: untouched
from couch_doom.music import find_title_music  # noqa: E402

pk3 = root / "tc.pk3"
with zipfile.ZipFile(pk3, "w") as z:
    z.writestr("music/LVL1.ogg", b"OggS" + b"\0" * 20)
    z.writestr("music/TITMUS.ogg", b"OggS" + b"\1" * 20)
guess = find_title_music(None, [pk3])
assert guess and guess.name == "TITLE" and guess.kind == "stream" and guess.data[4] == 1, guess
with zipfile.ZipFile(root / "plain.pk3", "w") as z:
    z.writestr("music/LVL1.ogg", b"OggS" + b"\0" * 20)
assert find_title_music(None, [root / "plain.pk3"]) is None  # nothing title-like: stay silent rather than guess a level song
from couch_doom.readme import find_readme  # noqa: E402
from couch_doom.options import Preset  # noqa: E402


def _readme_for(folder: str, files: dict[str, bytes], mod: str):
    d = root / "rm" / folder
    d.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (d / name).write_bytes(data)
    return find_readme(Preset("t", "s", "e", None, [d / mod]))


r = _readme_for("evit", {"Eviternity II.wad": b"x", "eviternityii.txt": b"Title : Evit\nDescription : big"}, "Eviternity II.wad")
assert r and r.source == "eviternityii.txt", r  # spacing ignored
r = _readme_for("aa", {"aaliens_v1_2.wad": b"x", "aaliens.txt": b"Title : AA"}, "aaliens_v1_2.wad")
assert r and r.source == "aaliens.txt", r  # version tail ignored
r = _readme_for("single", {"sa.pk3": b"x", "SA readme.txt": b"hello"}, "sa.pk3")
assert r and r.source == "SA readme.txt", r  # one game file, one readme
r = _readme_for("lang", {"dd.pk3": b"x", "Readme RUS.txt": b"privet", "Readme ENG.txt": b"hello"}, "dd.pk3")
assert r and r.source == "Readme ENG.txt", r
r = _readme_for("dump", {"a.wad": b"x", "b.wad": b"x", "SIGIL_README.txt": b"unrelated"}, "a.wad")
assert r is None, r  # a shared folder of downloads: no guessing
r = _readme_for("changes", {"solo.wad": b"x", "CHANGELOG.txt": b"v2"}, "solo.wad")
assert r is None, r
pk = root / "rm" / "both.pk3"
with zipfile.ZipFile(pk, "w") as z:
    z.writestr("credits.txt", "Thanks")
    z.writestr("readme.txt", "Title : Both\nDescription : the readme")
r = find_readme(Preset("t", "s", "e", None, [pk]))
assert r and r.source.endswith("readme.txt") and r.blurb == "the readme", r  # readme beats credits
def _bstr(text: str, ident: int) -> bytes:
    raw = text.encode("utf-8")
    n, varint = len(raw), b""
    while True:
        varint += bytes([n & 0x7F | (0x80 if n > 0x7F else 0)])
        n >>= 7
        if not n:
            break
    return b"\x06" + ident.to_bytes(4, "little") + varint + raw


def _metadata(wad: str, title: str, english: str, author: str) -> bytes:
    parts = ["/WADs/8/8", wad, title, english, "Version fran\u00e7aise " + "x" * 50, "Versione " + "x" * 50, "Deutsch " + "x" * 50,
             "Espa\u00f1ol " + "x" * 50, author, "iwad", "2019/9/27", "shot1.jpg"]
    return b"\x00\x01junk" + b"".join(_bstr(v, 10 + i) for i, v in enumerate(parts))


english = "A long English description of the episode that is clearly more than forty characters.\n\nSecond paragraph."
r = _readme_for("mb", {"mine.wad": b"x", "metadata": _metadata("mine.wad", "Mine", english, "Someone")}, "mine.wad")
assert r and r.source == "mod browser" and r.author == "Someone" and r.year == "2019", r
assert r.blurb.startswith("A long English") and "Second paragraph" not in r.blurb and "Second paragraph" in r.text, r.blurb
r = _readme_for("mb2", {"tvr.wad": b"x", "metadata": _metadata("tvr2021.wad", "TVR", english, "T")}, "tvr.wad")
assert r and r.source == "mod browser"  # renamed file, but the only game in its folder
r = _readme_for("mb3", {"a.wad": b"x", "b.wad": b"x", "metadata": _metadata("other.wad", "O", english, "T")}, "a.wad")
assert r is None, r  # several downloads share the folder and the name doesn't match: don't borrow it


def _wad_with(lumps: dict[str, bytes]) -> bytes:
    body, entries, pos = b"", b"", 12
    for name, data in lumps.items():
        entries += pos.to_bytes(4, "little") + len(data).to_bytes(4, "little") + name.encode().ljust(8, b"\0")
        body += data
        pos += len(data)
    return b"PWAD" + len(lumps).to_bytes(4, "little") + pos.to_bytes(4, "little") + body + entries


info = b"Title                   : Embedded\nAuthor                  : Me\n" + b"Description : " + b"x" * 80
r = _readme_for("emb", {"emb.wad": _wad_with({"WADINFO": info})}, "emb.wad")
assert r and r.source.endswith("WADINFO") and r.author == "Me", r
newer = (b"Map creator                     : Carton\nMap title                       : The Darkest\n"
         b"Map description                 : Map for a contest.\n\n"
         b"Commentary                      : For years, the echoes of my breath\n                                  were the only sound.\n\n"
         b"Credits                         : Someone\n")
r = _readme_for("newtpl", {"dd.pk3": b"x", "Readme ENG.txt": newer}, "dd.pk3")
assert r and r.author == "Carton" and r.fields["title"] == "The Darkest", r
assert r.blurb == "Map for a contest. For years, the echoes of my breath were the only sound.", r.blurb
import couch_doom.readme as rdm  # noqa: E402

real_file = rdm.OVERRIDES_FILE
rdm.OVERRIDES_FILE = root / "descriptions.json"
rdm._overrides = None
try:
    assert _readme_for("ov0", {"Mod.wad": b"x"}, "Mod.wad") is None  # no override file yet
    rdm.OVERRIDES_FILE.write_text('{"MOD.WAD": {"title": "My Mod", "author": "Me", "year": 2020, "description": "Mine."}}', encoding="utf-8")
    r = _readme_for("ov1", {"Mod.wad": b"x", "Mod.txt": b"Title : Other\nAuthor : Them\nDescription : theirs"}, "Mod.wad")
    assert r and r.source == "descriptions.json" and r.author == "Me" and r.year == "2020" and r.blurb == "Mine.", r  # beats a readme
    assert _readme_for("ov2", {"Other.wad": b"x"}, "Other.wad") is None  # only the named file
    import time
    time.sleep(0.05)
    rdm.OVERRIDES_FILE.write_text("{not json", encoding="utf-8")
    import os
    os.utime(rdm.OVERRIDES_FILE, (time.time() + 5, time.time() + 5))
    assert _readme_for("ov3", {"Mod.wad": b"x"}, "Mod.wad") is None  # a broken file is ignored, not fatal
finally:
    rdm.OVERRIDES_FILE = real_file
    rdm._overrides = None
from couch_doom.known import lookup  # noqa: E402

assert lookup("Elementalism_Phase1_Full_Release_v1.9.pk3").title == "Elementalism: Phase 1"  # a newer download still matches
assert lookup("rr.pk3").title == "Refracted Reality" and lookup("rr2.pk3") is None  # exact keys don't act as prefixes
assert lookup("hacx.wad").title and lookup("unknown.wad") is None
r = _readme_for("kn", {"Bloom.pk3": b"x", "readme.txt": b"Just thanks to everyone"}, "Bloom.pk3")
assert r and r.source != "readme.txt" and r.author == "Bloom Team" and "Crossover" not in r.blurb and r.blurb.startswith("A Doom and Blood")
assert "Just thanks to everyone" in r.text  # the readme's own text stays below the entry
r = _readme_for("kn2", {"Bloom.pk3": b"x", "Bloom.txt": b"Title : B\nAuthor : A\nDescription : the readme's own words are used when it has them"}, "Bloom.pk3")
assert r and r.source == "Bloom.txt", r
import couch_doom.ui as ui_mod  # noqa: E402

real_create, fails = app._create_window, [2]
real_sleep, ui_mod.time.sleep = ui_mod.time.sleep, lambda _s: None
real_log, ui_mod.log.write = ui_mod.log.write, lambda *a, **k: None


def flaky_create() -> None:
    if fails[0]:
        fails[0] -= 1
        raise pygame.error("Couldn't create window: used all of its system allowance of handles")
    real_create()


app._create_window = flaky_create
app._open_window()  # a window that only opens on the third try still opens
assert fails[0] == 0 and app.screen.get_size() == (1440, 810)
del app._create_window
ui_mod.time.sleep, ui_mod.log.write = real_sleep, real_log
pads = app.input.pad_count
app.input.suspend()
assert app.input.pad_count == 0 and not pygame.joystick.get_init()
app.input.resume()
assert app.input.pad_count == pads and pygame.joystick.get_init()  # pads come back after a game
from couch_doom.launch import presented_files  # noqa: E402
from couch_doom.music import midi_volume, VOLUME  # noqa: E402

midi = b"MThd\0\0\0\x06\0\0\0\x01\0\x60MTrk\0\0\0\x04\0\xff\x2f\0"
strife = root / "strife1.wad"
strife.write_bytes(_wad_with({"D_INTRO": midi, "D_LOGO": midi + b"\0"}))
assert find_title_music(strife, []).data == midi + b"\0"  # Strife's title plays D_LOGO, not its intro song

dk = root / "dk"
dk.mkdir()
(dk / "HEXEN.WAD").write_bytes(b"x")
(dk / "hexdd.wad").write_bytes(b"x")
base, shown = presented_files(Preset("DK", "s", "e", dk / "hexdd.wad", []))
assert base == dk / "HEXEN.WAD" and shown == [dk / "hexdd.wad"]  # an add-on IWAD stands on its base game
assert presented_files(Preset("H", "s", "e", dk / "HEXEN.WAD", [])) == (dk / "HEXEN.WAD", [])

spiky, even = midi_volume(2.6, 0.22), midi_volume(1.0, 0.22)
assert spiky == even and spiky * 0.22 == even * 0.22  # one loud hit no longer pulls the whole track down
assert midi_volume(1.0, 0.03) == 0.9  # a quiet track is raised only until its peak would clip
assert midi_volume(0.5, 0.01) == 1.0 and midi_volume(0.0, 0.0) == VOLUME
from couch_doom.music import MusicPlayer, Prepared  # noqa: E402

if pygame.mixer.get_init():
    mp = MusicPlayer(None, (pygame.mixer.Channel(0), pygame.mixer.Channel(1)))
    tune = Prepared("pcm", bytes(44100 * 8 * 3), 0.5, "stock")
    mp.cache["stock"] = tune
    a, b, quiet = (root / "a.wad", ()), (root / "b.wad", ()), (root / "c.wad", ())
    mp.tracks.update({a: "stock", b: "stock", quiet: None})
    mp.request(1, a[0], [])
    mp.update()
    channel = mp.active
    assert mp.playing == "stock" and mp.channels[channel].get_busy()
    mp.request(2, b[0], [])
    mp.update()
    assert mp.active == channel and mp.playing == "stock" and mp.pending is None  # same track plays on, not restarted
    mp.request(3, quiet[0], [])
    assert mp.playing is None  # a preset without title music fades it out
    mp.shutdown()
print("smoke ok:", ", ".join(sorted(found)), "| UI", app.screen.get_size())
from couch_doom.titleart import find_logo, find_title_art  # noqa: E402


def _png(w: int, h: int, tag: bytes = b"") -> bytes:
    return b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + w.to_bytes(4, "big") + h.to_bytes(4, "big") + tag


d2 = root / "doom2.wad"
d2.write_bytes(_wad_with({"PLAYPAL": b"\x80" * 768, "TITLEPIC": _png(320, 200, b"stock"), "D_DM2TTL": midi}))
emb = root / "emb.pk3"
with zipfile.ZipFile(emb, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("main.wad", _wad_with({"TITLEPIC": _png(320, 200, b"mine"), "D_DM2TTL": midi + b"\1"}))
    z.writestr("maps/MAP01.wad", _wad_with({"TITLEPIC": _png(320, 200, b"map")}))
assert find_title_art(d2, [emb]).data.endswith(b"mine")  # a WAD at a pk3's root loads with it, like the engine does
assert find_title_music(d2, [emb]).data == midi + b"\1"
tm = root / "titlemap.pk3"
with zipfile.ZipFile(tm, "w") as z:
    z.writestr("zmapinfo.txt", 'map TITLEMAP "Welcome"\n{\n  sky1 = "SKY1"\n  music = "D_TITLE"\n}\n')
    z.writestr("music/D_TITLE.ogg", b"OggS" + b"\2" * 20)
    z.writestr("textures/runes/logo1.png", _png(512, 512))
    z.writestr("textures/logo2021.png", _png(986, 180, b"word"))
assert find_title_music(d2, [tm]).data[4] == 2  # no titlemusic: the title map's own song
assert find_title_art(d2, [tm]).data.endswith(b"stock")  # a 3D title map and nothing of its own: the IWAD's picture
with zipfile.ZipFile(tm, "a") as z:
    z.writestr("graphics/interbg.png", _png(1920, 1080, b"inter"))
assert find_title_art(d2, [tm]).data.endswith(b"inter")  # the mod's own intermission backdrop stands in
assert find_logo(d2, [tm]).data.endswith(b"word")  # the wide wordmark, not the square emblem
ipk = root / "tc.ipk3"
with zipfile.ZipFile(ipk, "w") as z:
    z.writestr("mapinfo.txt", 'map TITLEMAP "Title" { music = "D_TITLE" }')
    z.writestr("graphics/titlepic.png", _png(320, 200, b"tc"))
assert find_title_art(ipk, []).data.endswith(b"tc")  # a standalone game's own title map doesn't hide its picture
di = root / "infinite.pk3"
with zipfile.ZipFile(di, "w") as z:
    z.writestr("MAPINFO", 'map TITLEMAP ""\n{\n  music = ""\n}\n')
    z.writestr("acs/intro.o", b"ACSE\0\0ResetTitlemap\0music/DIM_1.mp3\0TITLEMAP\0")
    z.writestr("music/DIM_1.mp3", b"ID3" + b"\3" * 20)
    z.writestr("MENUDEF", 'LISTMENU "MainMenu"\n{\n  StaticPatch 94, 0, "DILSC0"\n  TextItem "START", "s", "x"\n}\n')
    z.writestr("sprites/intro/DILSC0.png", _png(123, 82, b"dils"))
track = find_title_music(d2, [di])
assert track and track.name == "DIM_1" and track.data[3] == 3, track  # started by the title map's own script
assert find_logo(d2, [di]).data.endswith(b"dils")  # whatever the main menu draws is the logo
from couch_doom.titleart import find_startup  # noqa: E402

pal16 = bytes(range(0, 48))
planes = [b"\x80" + b"\0" * (640 * 480 // 8 - 1), b"\0" * (640 * 480 // 8), b"\0" * (640 * 480 // 8), b"\x80" + b"\0" * (640 * 480 // 8 - 1)]
st = root / "startup.pk3"
with zipfile.ZipFile(st, "w") as z:
    z.writestr("STARTUP", pal16 + b"".join(planes))
art = find_startup([st])
assert art and art.size == (640, 480) and art.data[0] == 9 and art.data[1] == 0  # bit planes 0 and 3 set the first pixel
assert art.palette[27:30] == bytes((c << 2) | (c >> 4) for c in pal16[27:30])  # 6-bit colours widened
assert find_startup([emb]) is None
assert find_title_art(d2, [emb]).fallback is False and find_title_art(d2, [tm]).fallback  # Doom 2's picture stands in
bl = root / "bloom.pk3"
with zipfile.ZipFile(bl, "w") as z:
    z.writestr("MENUDEF.txt", 'ListMenu "MainMenu"\n{\n  IfGame(Doom)\n  {\n    StaticPatch 73, -20, "LOGO"\n  }\n}\n')
    z.writestr("HIRESTEX.txt", '//Graphic "LOGO", 1, 1 { Patch "WRONG", 0, 0 }\nGraphic "LOGO", 825, 825\n{\n  XScale 5.0\n  Patch "M_BLOOM", 140, 0\n}\n')
    z.writestr("graphics/m_bloom.png", _png(625, 340, b"bloom"))
    z.writestr("graphics/misc/m_doom.png", _png(480, 240, b"panel"))
assert find_logo(d2, [bl]).data.endswith(b"bloom")  # a TEXTURES alias resolves to its picture
bw = root / "bw.pk3"
with zipfile.ZipFile(bw, "w") as z:
    z.writestr("MENUDEF", 'ListMenu "MainMenu"\n{\n  StaticPatch 99, 2, "M_DOOM"\n}\n')
    z.writestr("graphics/misc/m_doom.png", _png(480, 240, b"panel"))
assert find_logo(d2, [bw]) is None  # a stock name buried in a subfolder is some other menu graphic
sq = root / "square.ipk3"
with zipfile.ZipFile(sq, "w") as z:
    z.writestr("PLAYPAL", b"\x80" * 768)
    z.writestr("MENUDEF.txt", 'ListMenu "MainMenu"\n{\n  StaticPatchCentered 160, 4, "M_SQUARE"\n}\n')
    z.writestr("graphics/M_SQUARE.png", _png(200, 60, b"square"))
assert find_logo(sq, []).data.endswith(b"square")  # a standalone game's own menu logo
zt = root / "zmc.pk3"
with zipfile.ZipFile(zt, "w") as z:
    z.writestr("textures.wad", _wad_with({"ZMCTITLE": _png(1280, 720, b"zmc"), "TITLEPI2": _png(640, 400, b"no")}))
    z.writestr("graphics/titlepic.png", _png(320, 200, b"pic"))
assert find_logo(d2, [zt]).data.endswith(b"zmc")  # a title card among its textures, inside a WAD in the pk3
el = root / "elem2.pk3"
with zipfile.ZipFile(el, "w") as z:
    z.writestr("MENUDEF.txt", 'ListMenu "MainMenu"\n{\n  StaticPatch 0, 0, "M_SUBTTL"\n}\n')
    z.writestr("TEXTURES.txt", 'Graphic "M_SUBTTL", 1024, 600 { Patch "SUBTTL", 0, 0 }')
    z.writestr("graphics/subttl.png", _png(1024, 600, b"menu"))
    z.writestr("textures/logo2021.png", _png(986, 180, b"word"))
assert find_logo(d2, [el]).data.endswith(b"word")  # a wide *logo* picture beats a menu texture alias
cv = root / "castle.ipk3"
with zipfile.ZipFile(cv, "w") as z:
    z.writestr("PLAYPAL", b"\x80" * 768)
    z.writestr("graphics/CVTITLE.png", _png(640, 400, b"cv"))
    z.writestr("graphics/titlepic.png", _png(320, 200, b"pic"))
assert find_logo(cv, []).data.endswith(b"cv")  # a standalone game's intro title card
card = pygame.Surface((40, 20))
card.fill((10, 10, 10))
card.fill((200, 40, 40), pygame.Rect(10, 5, 20, 10))
assert ui_mod._dark_backed(card)
keyed = ui_mod._key_out_dark(card)
assert keyed.get_at((0, 0)).a == 0 and keyed.get_at((20, 10)).a == 255  # backing gone, lettering kept
with zipfile.ZipFile(cv, "a") as z:
    z.writestr("graphics/M_DOOM.png", _png(200, 80, b"small"))
assert find_logo(cv, []).data.endswith(b"cv")  # the intro's 640px title card beats the 200px menu copy
ash = root / "ashes.pk3"
with zipfile.ZipFile(ash, "w") as z:
    z.writestr("textures/dblogo.png", _png(500, 150, b"db"))
    z.writestr("textures/gzlogo.png", _png(500, 150, b"gz"))
assert find_logo(d2, [ash]) is None  # editor and engine credit logos aren't the mod's
