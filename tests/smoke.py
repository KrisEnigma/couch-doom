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
print("smoke ok:", ", ".join(sorted(found)), "| UI", app.screen.get_size())
