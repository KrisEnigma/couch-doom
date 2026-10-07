"""Turn a DoomRunner preset into an engine command line."""
from __future__ import annotations

import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .options import Options, Preset

GAME_EXTS = {".wad", ".pk3", ".pk7", ".ipk3", ".pke", ".zip", ".deh", ".bex"}

# DoomRunner LaunchMode enum.
LAUNCH_DEFAULT, LAUNCH_MAP, LAUNCH_SAVE = 0, 1, 2


@dataclass
class LaunchCommand:
    argv: list[str]
    cwd: Path | None
    env: dict[str, str]
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def display(self) -> str:
        return subprocess.list2cmdline(self.argv)


def split_args(text: str) -> list[str]:
    """Split like a shell but keep Windows backslashes intact."""
    if not text.strip():
        return []
    lex = shlex.shlex(text, posix=True)
    lex.whitespace_split = True
    lex.escape = ""
    lex.commenters = ""
    return list(lex)


def _expand_mappack(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(
            (p for p in path.iterdir() if p.is_file() and p.suffix.lower() in GAME_EXTS),
            key=lambda p: p.name.lower(),
        )
    return [path]


def load_order(preset: Preset) -> list[Path]:
    """Files after the IWAD, in the order the engine loads them."""
    maps = [f for mp in preset.mappacks if mp.exists() for f in _expand_mappack(mp)]
    return [*preset.mods, *maps] if preset.load_maps_after_mods else [*maps, *preset.mods]


def _file_args(files: list[Path]) -> list[str]:
    plain = [str(f) for f in files if f.suffix.lower() not in (".deh", ".bex")]
    args = ["-file", *plain] if plain else []
    for f in files:
        ext = f.suffix.lower()
        if ext == ".deh":
            args += ["-deh", str(f)]
        elif ext == ".bex":
            args += ["-bex", str(f)]
    return args


def _option_args(preset: Preset) -> list[str]:
    g = preset.groups
    args: list[str] = []

    launch = g.get("launch", {})
    mode = launch.get("launch_mode", LAUNCH_DEFAULT)
    gameplay = g.get("gameplay", {})
    if mode == LAUNCH_MAP and launch.get("map_name"):
        args += ["+map", launch["map_name"], "-skill", str(gameplay.get("skill_num", 3))]
    elif mode == LAUNCH_SAVE and launch.get("save_file"):
        args += ["-loadgame", launch["save_file"]]

    if gameplay.get("fast_monsters"):
        args.append("-fast")
    if gameplay.get("monsters_respawn"):
        args.append("-respawn")
    if gameplay.get("no_monsters"):
        args.append("-nomonsters")
    if gameplay.get("allow_cheats"):
        args += ["+sv_cheats", "1"]
    for key, cvar in (("dmflags1", "+dmflags"), ("dmflags2", "+dmflags2"), ("dmflags3", "+dmflags3")):
        if gameplay.get(key):
            args += [cvar, str(gameplay[key])]

    compat = g.get("compat", {})
    if compat.get("compatflags1"):
        args += ["+compatflags", str(compat["compatflags1"])]
    if compat.get("compatflags2"):
        args += ["+compatflags2", str(compat["compatflags2"])]

    video = g.get("video", {})
    if video.get("resolution_x") and video.get("resolution_y"):
        args += ["-width", str(video["resolution_x"]), "-height", str(video["resolution_y"])]
    if video.get("show_fps"):
        args += ["+vid_fps", "1"]

    audio = g.get("audio", {})
    if audio.get("no_sound"):
        args.append("-nosound")
    else:
        if audio.get("no_music"):
            args.append("-nomusic")
        if audio.get("no_sfx"):
            args.append("-nosfx")
    return args


def _present(preset: Preset, path: Path) -> bool:
    if path.exists():
        return True
    return any(dest == path and archive.exists() for archive, _, dest in preset.unpack)


def build_command(opts: Options, preset: Preset) -> LaunchCommand:
    issues: list[str] = list(preset.issues)
    engine = opts.engine_for(preset)
    env = {**os.environ, **opts.global_env, **preset.env_vars}

    if engine is None:
        return LaunchCommand([], None, env, [f"Engine '{preset.engine_id}' not configured"])
    if not engine.path.exists():
        issues.append(f"Engine missing: {engine.path}")

    argv = [*split_args(opts.cmd_prefix), str(engine.path)]

    if preset.selected_config:
        cfg = Path(preset.selected_config)
        if not cfg.is_absolute():
            cfg_dir = preset.alternative_paths.get("config_dir") or engine.config_dir
            cfg = Path(cfg_dir) / cfg if cfg_dir else cfg
        argv += ["-config", str(cfg)]

    if preset.iwad:
        if not _present(preset, preset.iwad):
            issues.append(f"IWAD missing: {preset.iwad.name}")
        argv += ["-iwad", str(preset.iwad)]

    for mp in preset.mappacks:
        if not mp.exists():
            issues.append(f"Map pack missing: {mp.name}")
    for mod in preset.mods:
        if not _present(preset, mod):
            issues.append(f"Mod missing: {mod.name}")
    argv += _file_args(load_order(preset))

    if save_dir := preset.alternative_paths.get("save_dir"):
        argv += ["-savedir", save_dir]
    if shot_dir := preset.alternative_paths.get("screenshot_dir"):
        argv += ["+screenshot_dir", shot_dir]

    argv += _option_args(preset)
    argv += split_args(opts.global_args)
    argv += split_args(preset.additional_args)

    return LaunchCommand(argv, engine.path.parent, env, issues)


@dataclass
class LaunchResult:
    returncode: int | None
    seconds: float
    error: str | None = None


def run_blocking(cmd: LaunchCommand) -> LaunchResult:
    start = time.monotonic()
    try:
        proc = subprocess.Popen(cmd.argv, cwd=cmd.cwd, env=cmd.env)
    except OSError as exc:
        return LaunchResult(None, 0.0, str(exc))
    code = proc.wait()
    return LaunchResult(code, time.monotonic() - start)
