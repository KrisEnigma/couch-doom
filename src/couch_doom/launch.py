"""Turn a DoomRunner preset into an engine command line."""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .engine_traits import FAMILIES, Traits, compat_flag_args
from .options import Options, Preset

GAME_EXTS = {".wad", ".pk3", ".pk7", ".ipk3", ".pke", ".zip", ".deh", ".hhe", ".bex"}

# DoomRunner LaunchMode enum.
LAUNCH_DEFAULT, LAUNCH_MAP, LAUNCH_SAVE, LAUNCH_RECORD_DEMO = 0, 1, 2, 3

_FILES = object()  # where the load-file group goes


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
        return cmdline(self.argv)


def cmdline(argv: list[str]) -> str:
    """argv quoted the way this OS's shell would need it."""
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


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


def _doomrunner_file_args(preset: Preset, traits: Traits) -> list[str]:
    """DoomRunner's ordering: dehacked files and custom arguments stay where they are in the lists,
    every other file goes into one load-file group placed where the first of them appeared."""
    args: list = []
    maps: list[str] = []
    mods: list[str] = []

    def add(group: list[str], f: Path) -> None:
        ext = f.suffix.lower()
        if ext in (".deh", ".hhe"):
            args.extend(["-deh", str(f)])
        elif ext == ".bex":
            args.extend(["-bex", str(f)])
        else:
            if not maps and not mods:
                args.extend([traits.spec.load_param, _FILES])
            group.append(str(f))

    for mp in preset.mappacks:
        if mp.exists():
            for f in _expand_mappack(mp):
                add(maps, f)
    for entry in preset.mod_entries or preset.mods:
        if isinstance(entry, str):
            args += split_args(entry)
        else:
            add(mods, entry)

    files = [*mods, *maps] if preset.load_maps_after_mods else [*maps, *mods]
    return [a for arg in args for a in (files if arg is _FILES else [arg])]


def _doomrunner_option_args(preset: Preset, traits: Traits) -> list[str]:
    g = preset.groups
    launch, gameplay, compat = g.get("launch", {}), g.get("gameplay", {}), g.get("compat", {})
    video, audio = g.get("video", {}), g.get("audio", {})
    args: list[str] = []

    mode = launch.get("launch_mode", LAUNCH_DEFAULT)
    if mode == LAUNCH_MAP:
        args += traits.map_args(launch.get("map_name") or "")
    elif mode == LAUNCH_SAVE:
        args += traits.load_game_args(launch.get("save_file") or "", preset.alternative_paths.get("save_dir"))

    direct = mode in (LAUNCH_MAP, LAUNCH_RECORD_DEMO)
    if direct:
        args += ["-skill", str(gameplay.get("skill_num", 3))]
    if direct or mode == LAUNCH_DEFAULT:
        for key, flag in (("no_monsters", "-nomonsters"), ("fast_monsters", "-fast"), ("monsters_respawn", "-respawn")):
            if gameplay.get(key):
                args.append(flag)
        if gameplay.get("pistol_start") and traits.pistol_start:
            args.append(traits.pistol_start)
        if gameplay.get("allow_cheats"):
            args += traits.cheats
        if traits.detailed_options:
            for key, cvar in (("dmflags1", "+dmflags"), ("dmflags2", "+dmflags2"), ("dmflags3", "+dmflags3")):
                if gameplay.get(key):
                    args += [cvar, str(gameplay[key])]
        if (compat_mode := compat.get("compat_mode", -1)) >= 0:
            args += traits.compat_mode_args(compat_mode)
        if traits.detailed_options:
            args += compat_flag_args(compat.get("compatflags1", 0), compat.get("compatflags2", 0))

    if (monitor := video.get("monitor_idx", 0)) > 0:
        args += ["+vid_adapter", traits.monitor_index(monitor - 1)]
    if video.get("resolution_x"):
        args += ["-width", str(video["resolution_x"])]
    if video.get("resolution_y"):
        args += ["-height", str(video["resolution_y"])]
    if video.get("show_fps"):
        args += ["+vid_fps", "1"]

    for key, flag in (("no_sound", "-nosound"), ("no_sfx", "-nosfx"), ("no_music", "-nomusic")):
        if audio.get(key):
            args.append(flag)
    return args


def _present(preset: Preset, path: Path) -> bool:
    if path.exists():
        return True
    return any(dest == path and archive.exists() for archive, _, dest in preset.unpack)


_LIB_PATHS = ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "LIBPATH")


def engine_environ(environ, frozen: bool | None = None) -> dict[str, str]:
    """The environment games should start with.

    A PyInstaller build puts its own _internal folder first on the library path so CouchDoom finds its bundled libraries.
    Left in place, every game inherits it and loads those (older) copies of libstdc++ and friends instead of the
    system's, and anything built against a newer one dies at startup ("GLIBCXX_3.4.32 not found"). PyInstaller keeps
    the original value as <NAME>_ORIG, so the game gets exactly what CouchDoom itself was started with.
    """
    env = dict(environ)
    if getattr(sys, "frozen", False) if frozen is None else frozen:
        for name in _LIB_PATHS:
            if f"{name}_ORIG" in env:
                env[name] = env.pop(f"{name}_ORIG")
            else:
                env.pop(name, None)
    return env

def build_command(opts: Options, preset: Preset) -> LaunchCommand:
    issues: list[str] = list(preset.issues)
    engine = opts.engine_for(preset)
    env = {**engine_environ(os.environ), **opts.global_env, **preset.env_vars}

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
    if engine.family in FAMILIES:
        traits = Traits(engine.family, engine.path)
        argv += _doomrunner_file_args(preset, traits)
        # Ports that don't know these flags can refuse to start, so they're only passed where supported.
        if (save_dir := preset.alternative_paths.get("save_dir")) and traits.spec.save_dir_param:
            argv += [traits.spec.save_dir_param, save_dir]
        if (shot_dir := preset.alternative_paths.get("screenshot_dir")) and traits.screenshot_dir_param:
            argv += [traits.screenshot_dir_param, shot_dir]
        argv += _doomrunner_option_args(preset, traits)
    else:
        argv += _file_args(load_order(preset))

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
