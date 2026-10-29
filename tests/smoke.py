"""End-to-end smoke test, run in CI on Windows, Linux and macOS: fake DoomRunner, qZDL and bare UZDoom setups in
each OS's real settings folders, then discovery, command lines and one rendered UI frame.

    python tests/smoke.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import struct
import sys
import tempfile
import threading
import time
import zipfile
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

root = Path(tempfile.mkdtemp(prefix="couchdoom-smoke-"))
if os.name == "nt":
    os.environ["APPDATA"] = str(root / "Roaming")
    os.environ["LOCALAPPDATA"] = str(root / "Local")
    dr_dir, zdl_dir = root / "Local" / "DoomRunner", root / "Roaming" / "Vectec Software"
else:
    os.environ["HOME"] = str(root)
    os.environ["XDG_DATA_HOME"] = str(root / "data")
    os.environ["XDG_CONFIG_HOME"] = str(root / "config")
    dr_dir = (root / "Library" / "Application Support" / "DoomRunner" if sys.platform == "darwin"
              else root / "data" / "DoomRunner")
    zdl_dir = root / "config" / "Vectec Software"  # Qt's INI files use ~/.config on macOS too
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
ini_dir = (port if os.name == "nt"
           else root / "Library" / "Preferences" if sys.platform == "darwin"
           else root / "config" / "uzdoom")
ini_dir.mkdir(parents=True, exist_ok=True)
(ini_dir / ("uzdoom_portable.ini" if os.name == "nt" else "uzdoom.ini")).write_text(
    f"[IWADSearch.Directories]\nPath=$PROGDIR\nPath={wads}\nPath=$COUCHDOOM_UNSET\n[GlobalSettings]\ni_searchdistributors=false\n")

import pygame  # noqa: E402
from couch_doom.launch import build_command  # noqa: E402
from couch_doom.options import OptionsError, Preset  # noqa: E402
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
check_started = threading.Event()
def fake_update_check(*args):
    check_started.set()
    return None
with patch.object(upd, "disabled", return_value=False), patch.object(upd, "check", side_effect=fake_update_check):
    app = App(dr, state, windowed=True)
assert app.update_job is not None and app.update_pool is not None and check_started.wait(1)
app._draw_loading("Handover", 0.5)  # the splash keeps drawing on the dummy display
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
app.problem = OptionsError("No IWADs found", "Set up a game first.", [])
pending = Future()
pending.set_result({"version": "9.9.9", "current": "0.6.0", "url": "https://github.com/KrisEnigma/couch-doom/releases", "notes": []})
app.update_job = pending
app.update_started = now - 4
app._poll_update(now)
assert app.mode == "update"  # an update notice is still available on the first-run/setup screen
app._on_action(Action.BACK, now)
assert app.mode == "list" and app.blocked
app.problem = None
for _ in range(3):
    pygame.event.pump()
    app.tick(now, 1 / 60)
    app._draw(now)
if app.update_pool:
    app.update_pool.shutdown(wait=True)
from couch_doom import log as clog  # noqa: E402

lp = root / "log" / "couch-doom.log"
engine = [sys.executable, "-c", "import sys; print('boom ' * 9000, flush=True); print('last line', file=sys.stderr); sys.exit(3)"]
run = clog.spawn(engine, None, dict(os.environ), "Fake", "fake cmd")
code, secs = run.wait(lp)
text = lp.read_text(encoding="utf-8")
assert code == 3 and clog.closed_early(code, secs) and not clog.closed_early(0, 60) and not clog.closed_early(0, 2)
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
from couch_doom import handover  # noqa: E402


def _window(**changes):
    values = dict(handle=100, pid=11, visible=True, class_name="SDL_app", width=1280, height=720, owner=0, tool=False)
    values.update(changes)
    return handover.Window(**values)


# Handover trusts only a real, visible window belonging to the engine or a process it started.
pids = {10, 11, 12}
assert handover._usable(_window(), pids, None)
assert not handover._usable(_window(), pids, 100)  # CouchDoom's own window
assert not handover._usable(_window(pid=99), pids, None)  # another program
assert not handover._usable(_window(visible=False), pids, None)
assert not handover._usable(_window(class_name="ConsoleWindowClass"), pids, None)
assert not handover._usable(_window(tool=True), pids, None)
assert not handover._usable(_window(owner=7), pids, None)  # an owned dialog, not the game
assert not handover._usable(_window(width=80, height=60), pids, None)
assert handover._descendants(10, [(11, 10), (12, 11), (20, 1), (10, 1)]) == {10, 11, 12}
assert handover._descendants(10, []) == {10}
# /proc/<pid>/stat puts the command in parentheses, and that command may contain spaces and parentheses itself.
assert handover._stat_ppid(b"42 (my ) game (x)) S 7 42 42 0 -1") == 7
maps = b"7f00-7f01 r-xp 00000000 08:01 1 /usr/lib/libwayland-client.so.0\n"
assert handover._loads_library(maps, b"libwayland-client")
assert not handover._loads_library(maps, b"libX11.so")
assert isinstance(handover.available(), bool)
if not handover.LINUX:
    assert not handover.engine_uses_wayland(os.getpid())


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


clock = _Clock()
ready_calls, frames = [], []


def ready():
    ready_calls.append(1)
    return len(ready_calls) >= 3


assert handover.hold(lambda: None, ready, lambda: frames.append(1), 10, clock, clock.sleep) == "window"
assert frames and len(ready_calls) == 3  # checked every POLL_SECONDS, not every frame
clock = _Clock()
frames = []
assert handover.hold(lambda: None, lambda: True, lambda: frames.append(1), 10, clock, clock.sleep,
                     grace_frames=2) == "window"
assert len(frames) == 2  # two more frames cover the engine's first paint
polls = []


def poll_once_then_exit():
    polls.append(1)
    return 1 if len(polls) >= 3 else None


assert handover.hold(poll_once_then_exit, lambda: True, lambda: None, grace_frames=2) == "exited"
assert handover.hold(lambda: 7, lambda: True, lambda: None, clock=clock, sleep=clock.sleep) == "exited"
clock = _Clock()
frames = []
assert handover.hold(lambda: None, lambda: False, lambda: frames.append(1), 0.05, clock, clock.sleep) == "timeout"
assert frames
if os.name != "nt":
    assert not handover.engine_window_visible(os.getpid(), None)  # the dummy display has no window to find
from couch_doom.launch import engine_environ  # noqa: E402

pyi = {"PATH": "/usr/bin", "LD_LIBRARY_PATH": "/app/_internal:/mine", "LD_LIBRARY_PATH_ORIG": "/mine", "LANG": "C"}
assert engine_environ(pyi, True) == {"PATH": "/usr/bin", "LD_LIBRARY_PATH": "/mine", "LANG": "C"}
assert "LD_LIBRARY_PATH" not in engine_environ({"LD_LIBRARY_PATH": "/app/_internal"}, True)  # there was none originally
assert engine_environ(pyi, False) == pyi  # running from source: untouched
from couch_doom.music import find_title_music, _classify  # noqa: E402
from couch_doom.archive import Archives, ArchiveSource, Wad  # noqa: E402

pk3 = root / "tc.pk3"
with zipfile.ZipFile(pk3, "w") as z:
    z.writestr("music/LVL1.ogg", b"OggS" + b"\0" * 20)
    z.writestr("music/TITMUS.ogg", b"OggS" + b"\1" * 20)
guess = find_title_music(None, [pk3])
assert guess and guess.name == "TITLE" and guess.kind == "stream" and guess.source and guess.midi_data is None
assert guess.format == "ogg" and guess.source.read_prefix(8)[4] == 1
with zipfile.ZipFile(root / "plain.pk3", "w") as z:
    z.writestr("music/LVL1.ogg", b"OggS" + b"\0" * 20)
assert find_title_music(None, [root / "plain.pk3"]) is None  # nothing title-like: stay silent rather than guess a level song
assert _classify(b"MThd\0\0\0\x06") == ("midi", "mid")
assert _classify(b"MUS\x1a" + b"\0" * 8) == ("midi", "mus")
assert _classify(b"OggS") == ("stream", "ogg")
assert _classify(b"fLaC") == ("stream", "flac")
assert _classify(b"ID3") == ("stream", "mp3")
assert _classify(b"\xff\xfb") == ("stream", "mp3")
assert _classify(b"RIFF" + b"\0" * 4 + b"WAVE") == ("stream", "wav")
assert _classify(b"Extended Module:") == ("stream", "xm")
assert _classify(b"IMPM") == ("stream", "it")
assert _classify(b"\0" * 44 + b"SCRM") == ("stream", "s3m")
assert _classify(b"\0" * 1080 + b"M.K.") == ("stream", "mod")

# ArchiveSource descriptors can outlive the archive context and stream WAD ranges and ZIP members in chunks.
source_wad = root / "source.wad"
wad(source_wad, ["D_DM2TTL"], data={"D_DM2TTL": b"OggS" + b"w" * 32})
source_emb = root / "source-embedded.pk3"
embedded_body = b"OggS" + b"e" * 32
embedded_offset = 12
embedded_bytes = (b"PWAD" + struct.pack("<ii", 1, embedded_offset + len(embedded_body)) + embedded_body
                  + struct.pack("<ii8s", embedded_offset, len(embedded_body), b"D_DM2TTL"))
with zipfile.ZipFile(source_emb, "w") as z:
    z.writestr("inside.wad", embedded_bytes)
source_zip = root / "source-music.pk3"
with zipfile.ZipFile(source_zip, "w") as z:
    z.writestr("music/title.ogg", b"OggS" + b"z" * 32)
source_empty = root / "source-empty.pk3"
with zipfile.ZipFile(source_empty, "w") as z:
    z.writestr("music/title.ogg", b"")
with Archives(source_wad, []) as archives:
    wad_source = archives.items[0].lump_source("D_DM2TTL")
with Archives(None, [source_zip]) as archives:
    zip_source = archives.items[0].lump_source("music/title.ogg")
with Archives(None, [source_zip, source_empty]) as archives:
    assert archives.find_source(["title"], ("music/", "")).size == 36
with Archives(None, [source_emb]) as archives:
    embedded_source = archives.items[0].lump_source("D_DM2TTL")
for source, expected in ((wad_source, b"OggS" + b"w" * 32), (zip_source, b"OggS" + b"z" * 32),
                         (embedded_source, b"OggS" + b"e" * 32)):
    assert source and source.size == len(expected)
    assert source.read_prefix(12) == expected[:12]
    import io
    copied = io.BytesIO()
    assert source.copy_to(copied, chunk_size=7) == len(expected) and copied.getvalue() == expected
assert wad_source.to_dict()["kind"] == "wad" and ArchiveSource.from_dict(zip_source.to_dict()).identity == zip_source.identity
cancel = __import__("threading").Event()
class _CancelAfterOneWrite:
    def __init__(self):
        self.data = bytearray()
    def write(self, chunk):
        self.data.extend(chunk)
        cancel.set()
        return len(chunk)
cancelled = _CancelAfterOneWrite()
try:
    wad_source.copy_to(cancelled, cancel, chunk_size=7)
    raise AssertionError("cancelled archive source copy completed")
except InterruptedError:
    assert len(cancelled.data) == 7

from couch_doom.cache_paths import cache_dir as shared_cache_dir  # noqa: E402
from couch_doom.asset_cache import cache_dir as assets_cache_dir  # noqa: E402
from couch_doom import music_cache  # noqa: E402

assert shared_cache_dir() == assets_cache_dir()
from couch_doom import music as music_mod  # noqa: E402
music_key = music_cache.selection_key("music-selection-smoke")
prepared_stream = music_mod._prepare(None, [source_zip], None, __import__("threading").Event(), {}, music_key)
assert prepared_stream and prepared_stream.kind == "stream" and isinstance(prepared_stream.data, Path)
original_archives = music_mod.Archives
try:
    music_mod.Archives = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("manifest missed"))
    cached_prepared_stream = music_mod._prepare(None, [source_zip], None, __import__("threading").Event(), {}, music_key)
finally:
    music_mod.Archives = original_archives
assert cached_prepared_stream and cached_prepared_stream.data == prepared_stream.data
cached_stream = music_cache.cache_stream(zip_source, "ogg", __import__("threading").Event())
assert cached_stream.is_file() and cached_stream.read_bytes() == b"OggS" + b"z" * 32
assert music_cache.cache_stream(zip_source, "ogg", __import__("threading").Event()) == cached_stream
selection_key = "smoke-selection"
music_cache.put_selection(selection_key, {"track": None})
assert music_cache.get_selection(selection_key) == (True, {"track": None})
music_cache.invalidate_selections(set())
assert music_cache.get_selection(selection_key) == (False, None)
source_stamp = source_zip.stat()
key_before_change = music_cache.selection_key("preset-key", None, [source_zip])
path_before_change = music_cache.cache_stream(zip_source, "ogg", __import__("threading").Event())
os.utime(source_zip, ns=(source_stamp.st_atime_ns, source_stamp.st_mtime_ns + 1_000_000))
key_after_change = music_cache.selection_key("preset-key", None, [source_zip])
path_after_change = music_cache.cache_stream(zip_source, "ogg", __import__("threading").Event())
os.utime(source_zip, ns=(source_stamp.st_atime_ns, source_stamp.st_mtime_ns))
assert key_before_change != key_after_change and music_cache.get_selection(key_after_change) == (False, None)
assert path_before_change != path_after_change
negative_key = music_cache.selection_key("negative-selection", None, [root / "plain.pk3"])
assert music_mod._prepare(None, [root / "plain.pk3"], None, __import__("threading").Event(), {}, negative_key) is None
original_archives_for_negative = music_mod.Archives
try:
    music_mod.Archives = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("negative manifest missed"))
    assert music_mod._prepare(None, [root / "plain.pk3"], None, __import__("threading").Event(), {}, negative_key) is None
finally:
    music_mod.Archives = original_archives_for_negative
cancelled_cache_event = __import__("threading").Event()
cancelled_cache_event.set()
try:
    music_cache.cache_stream(wad_source, "ogg", cancelled_cache_event)
    raise AssertionError("cancelled cache population completed")
except InterruptedError:
    assert not list((shared_cache_dir() / "music").glob("*.part"))
old_cap = music_cache.MAX_STREAM_BYTES
music_cache.MAX_STREAM_BYTES = 10
other_protected_stream = music_cache.cache_stream(wad_source, "ogg", __import__("threading").Event(),
                                                  protected={cached_stream})
assert cached_stream.exists() and other_protected_stream.exists()
music_cache.prune({cached_stream, other_protected_stream})
assert cached_stream.exists() and other_protected_stream.exists()  # protected paths may exceed target
music_cache.prune()
assert not cached_stream.exists() and not other_protected_stream.exists()  # after release they are eligible
music_cache.MAX_STREAM_BYTES = old_cap
fallback_cache_stream = music_cache.cache_stream(zip_source, "ogg", __import__("threading").Event())
original_cache_stream = music_cache.cache_stream
try:
    music_cache.cache_stream = lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("cache unavailable"))
    fallback_prepared = music_mod._prepare(None, [source_zip], None, __import__("threading").Event(), {})
finally:
    music_cache.cache_stream = original_cache_stream
assert fallback_prepared and isinstance(fallback_prepared.data, bytes) and fallback_prepared.format == "ogg"
oversized_source = ArchiveSource(zip_source.kind, zip_source.archive, 8 * 1024 * 1024 + 1,
                                 zip_source.offset, zip_source.member, zip_source.crc)
original_find_music = music_mod.find_title_music
try:
    music_mod.find_title_music = lambda *_args, **_kwargs: music_mod.Track("stream", "ogg", "large", source=oversized_source)
    music_cache.cache_stream = lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("cache unavailable"))
    assert music_mod._prepare(None, [source_zip], None, __import__("threading").Event(), {}) is None
finally:
    music_mod.find_title_music = original_find_music
    music_cache.cache_stream = original_cache_stream
original_copy_to = ArchiveSource.copy_to
try:
    ArchiveSource.copy_to = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cache hit recopied source"))
    no_copy_hit = music_cache.cache_stream(zip_source, "ogg", __import__("threading").Event())
finally:
    ArchiveSource.copy_to = original_copy_to
assert no_copy_hit == fallback_cache_stream
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
ui_size = app.screen.get_size()  # read before the launch-order test destroys the window
del app._create_window
ui_mod.time.sleep, ui_mod.log.write = real_sleep, real_log
pads = app.input.pad_count
app.input.suspend()
assert app.input.pad_count == 0 and not pygame.joystick.get_init()
app.input.resume()
assert app.input.pad_count == pads and pygame.joystick.get_init()  # pads come back after a game

# Launch order: pads off before the splash, window back before audio/pads on, and never resumed while the game runs.
order = []


class _FakeLaunched:
    output = ""

    class proc:
        pid = 1234

        @staticmethod
        def poll():
            return None

    @staticmethod
    def wait():
        order.append("wait")
        return 0, 5.0


originals = {
    name: getattr(ui_mod, name) for name in ("spawn", "needs_extract_retry", "closed_early")
}
display_originals = {name: getattr(pygame.display, name) for name in ("init", "quit", "set_caption")}
installed: dict[str, tuple] = {}


def patched(owner, name, source, result=None):
    old = getattr(owner, name)
    installed[f"{owner}.{name}"] = (owner, name, old)

    def replacement(*args, **kwargs):
        order.append(source)
        return result

    setattr(owner, name, replacement)


try:
    patched(ui_mod, "spawn", "spawn", _FakeLaunched())
    patched(ui_mod, "needs_extract_retry", "retry", False)
    patched(ui_mod, "closed_early", "closed-early", False)
    patched(pygame.display, "init", "display-init")
    patched(pygame.display, "quit", "display-quit")
    patched(pygame.display, "set_caption", "caption")
    patched(app, "_play_wipe", "wipe")
    patched(app, "_hold_loading", "hold")
    patched(app, "_audio_down", "audio-down")
    patched(app, "_audio_up", "audio-up")
    patched(app, "_open_window", "window")
    patched(app.input, "suspend", "suspend")
    patched(app.input, "resume", "resume")
    patched(app.input, "reset", "reset")
    app.current = 0
    app._launch_selected()
finally:
    for owner, name, old in installed.values():
        setattr(owner, name, old)
    for name, old in display_originals.items():
        setattr(pygame.display, name, old)

assert order.index("suspend") < order.index("hold") < order.index("wait"), order
assert order.index("wait") < order.index("window") < order.index("audio-up") < order.index("resume"), order
assert order.index("suspend") < order.index("wait") < order.index("resume"), order  # pads stay off while the game runs
assert order.count("resume") == 1, order
from couch_doom.launch import presented_files  # noqa: E402
from couch_doom.music import midi_volume, VOLUME  # noqa: E402

midi = b"MThd\0\0\0\x06\0\0\0\x01\0\x60MTrk\0\0\0\x04\0\xff\x2f\0"
strife = root / "strife1.wad"
strife.write_bytes(_wad_with({"D_INTRO": midi, "D_LOGO": midi + b"\0"}))
assert find_title_music(strife, []).midi_data == midi + b"\0"  # Strife's title plays D_LOGO, not its intro song
original_wad_lump = Wad.lump
try:
    Wad.lump = lambda self, name, *args: (_ for _ in ()).throw(AssertionError("default music lump materialized")) \
        if Path(name).stem.upper() == "D_LOGO" else original_wad_lump(self, name, *args)
    assert find_title_music(strife, [], materialize_midi=False).source is not None
finally:
    Wad.lump = original_wad_lump
class _RecordingMidiRenderer:
    soundfont = root / "test.sf2"
    def __init__(self):
        self.received = None
    def render(self, data, _cancel):
        self.received = data
        return bytes(8), 0.5, 0.2
recording_renderer = _RecordingMidiRenderer()
prepared_midi = music_mod._prepare(strife, [], recording_renderer, __import__("threading").Event(), {})
assert prepared_midi and prepared_midi.kind == "pcm" and recording_renderer.received == midi + b"\0"

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
from concurrent.futures import Future
from couch_doom.music import MusicPlayer, Prepared  # noqa: E402
from collections import OrderedDict
old_music_cap = music_mod.CACHE_BYTES
music_mod.CACHE_BYTES = 8
pcm_cache_probe = object.__new__(MusicPlayer)
pcm_cache_probe.cache = OrderedDict()
pcm_cache_probe._cache_prepared(Prepared("pcm", b"a" * 6, 0.5, "old"))
pcm_cache_probe._cache_prepared(Prepared("pcm", b"b" * 6, 0.5, "new"))
assert list(pcm_cache_probe.cache) == ["new"]
pcm_cache_probe._cache_prepared(Prepared("pcm", b"c" * 16, 0.5, "oversized"))
assert "oversized" not in pcm_cache_probe.cache and sum(len(p.data) for p in pcm_cache_probe.cache.values()) <= 8
pcm_cache_probe._cache_prepared(Prepared("stream", root / "music.ogg", 0.5, "stream", "ogg"))
assert "stream" not in pcm_cache_probe.cache
music_mod.CACHE_BYTES = old_music_cap

if pygame.mixer.get_init():
    mp = MusicPlayer(None, (pygame.mixer.Channel(0), pygame.mixer.Channel(1)))
    tune = Prepared("pcm", bytes(44100 * 8 * 3), 0.5, "stock")
    mp.cache["stock"] = tune
    a, b, quiet = (root / "a.wad", (), None), (root / "b.wad", (), None), (root / "c.wad", (), None)
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
    unavailable_player = MusicPlayer(None, (pygame.mixer.Channel(0), pygame.mixer.Channel(1)))
    failed_future = Future()
    failed_future.set_result(None)  # the worker reports the logged, unavailable-cache result
    unavailable_player.want = "large-stream"
    unavailable_ident = (root / "large.pk3", (), None)
    unavailable_player.job = ("large-stream", unavailable_ident, failed_future, __import__("threading").Event())
    unavailable_player.update()
    assert unavailable_player.tracks[unavailable_ident] is None
    unavailable_player.shutdown()
    mixer_music = pygame.mixer.music
    originals = {name: getattr(mixer_music, name) for name in ("load", "get_busy", "set_volume", "play", "fadeout", "unload")}
    loaded_streams = []
    try:
        mixer_music.load = lambda path, *args: loaded_streams.append(path)
        mixer_music.get_busy = lambda: False
        mixer_music.set_volume = lambda _volume: None
        mixer_music.play = lambda **_kwargs: None
        mixer_music.fadeout = lambda _duration: None
        mixer_music.unload = lambda: None
        path_player = MusicPlayer(None, (pygame.mixer.Channel(0), pygame.mixer.Channel(1)))
        path_player.want = "stream-path"
        path_player.pending = ("stream-path", Prepared("stream", fallback_cache_stream, 0.5, "path", "ogg"))
        path_player._start()
        assert loaded_streams == [str(fallback_cache_stream)]
        path_player.shutdown()
    finally:
        for name, original in originals.items():
            setattr(mixer_music, name, original)
print("smoke ok:", ", ".join(sorted(found)), "| UI", ui_size)
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
assert find_title_music(d2, [emb]).midi_data == midi + b"\1"
tm = root / "titlemap.pk3"
with zipfile.ZipFile(tm, "w") as z:
    z.writestr("zmapinfo.txt", 'map TITLEMAP "Welcome"\n{\n  sky1 = "SKY1"\n  music = "D_TITLE"\n}\n')
    z.writestr("music/D_TITLE.ogg", b"OggS" + b"\2" * 20)
    z.writestr("textures/runes/logo1.png", _png(512, 512))
    z.writestr("textures/logo2021.png", _png(986, 180, b"word"))
assert find_title_music(d2, [tm]).source.read_prefix(8)[4] == 2  # no titlemusic: the title map's own song
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
assert track and track.name == "DIM_1" and track.source.read_prefix(8)[3] == 3, track  # started by the title map's own script
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
bwk = root / "ZMC-BWV7.0.pk3"
with zipfile.ZipFile(bwk, "w") as z:
    z.writestr("MapInfo.txt", 'map TITLEMAP "Love"\n{\n  music = WONDER\n}\n')
    z.writestr("graphics/interpic.png", _png(426, 200, b"inter"))
    z.writestr("graphics/WLFEND.png", _png(1300, 812, b"gate"))
art = find_title_art(d2, [bwk])
assert art.data.endswith(b"gate") and not art.fallback  # a known mod's picked title art, a real one
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
