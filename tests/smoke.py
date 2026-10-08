"""End-to-end smoke test, run in CI on Windows and Linux: fake DoomRunner and qZDL setups in each OS's real
settings folders, then discovery, command lines and one rendered UI frame.

    python tests/smoke.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
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

import pygame  # noqa: E402
from couch_doom.launch import build_command  # noqa: E402
from couch_doom.sources import discover, load_choice  # noqa: E402
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

app = App(dr, State(root / "state.json"), windowed=True)
now = time.monotonic()
for _ in range(3):
    pygame.event.pump()
    app.tick(now, 1 / 60)
    app._draw(now)
print("smoke ok:", ", ".join(sorted(found)), "| UI", app.screen.get_size())
