"""DoomRunner's engine families: which command-line flags each kind of source port expects.

Mirrors DoomRunner 1.9.2 (Sources/EngineTraits.cpp) so a preset gets the same arguments DoomRunner would give it.
Only DoomRunner engines carry one of these families; the other launchers build plain -file command lines.
"""
from __future__ import annotations

import ctypes
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path


@dataclass(frozen=True)
class Family:
    load_param: str
    save_dir_param: str | None
    map_style: str  # "map": +map NAME, "warp": -warp N [M]
    compat_style: str | None  # "zdoom": +compatmode, "prboom": -complevel


FAMILIES = {
    "ZDoom": Family("-file", "-savedir", "map", "zdoom"),
    "ChocolateDoom": Family("-merge", "-savedir", "warp", None),
    "PrBoom": Family("-file", "-save", "warp", "prboom"),
    "MBF": Family("-file", "-save", "warp", "prboom"),
    "EDGE": Family("-file", None, "warp", None),
    "KEX": Family("-file", None, "warp", None),
}

# DoomRunner's auto-detection by executable name (lower case, no .exe), for engines saved without a family.
KNOWN = {
    **dict.fromkeys(("chocolate-doom", "chocolate-heretic", "chocolate-hexen", "crispy-doom", "crispy-heretic",
                     "crispy-hexen", "doomretro", "strife-ve"), "ChocolateDoom"),
    **dict.fromkeys(("prboom", "prboom-plus", "glboom", "dsda-doom"), "PrBoom"),
    **dict.fromkeys(("smmu", "eternity", "nugget-doom", "cherry-doom", "woof"), "MBF"),
    **dict.fromkeys(("zdoom", "lzdoom", "gzdoom", "qzdoom", "uzdoom", "vkdoom", "skulltag", "zandronum"), "ZDoom"),
    **dict.fromkeys(("edge", "3dge", "edge-classic"), "EDGE"),
    "doom_gog": "KEX",
}
FALLBACK = "ChocolateDoom"  # DoomRunner's choice: its flags are the ones most likely to work anywhere

_MONITOR_BASE = {"zdoom": 1}
_LATEST = (255, 255, 255)


def detect(family: str | None, exe: Path) -> str:
    if family in FAMILIES:
        return family
    name = exe.stem.lower()
    if name in KNOWN:
        return KNOWN[name]
    return "EDGE" if name.startswith("edge") else FALLBACK  # EDGE puts its version in the exe name: edge135.exe


@cache
def exe_version(exe: Path) -> tuple[int, int, int]:
    """The exe's file version, or 'latest' when it can't be read (DoomRunner assumes the same)."""
    try:
        ver = ctypes.windll.version
        size = ver.GetFileVersionInfoSizeW(str(exe), None)
        if not size:
            return _LATEST
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(str(exe), 0, size, buf):
            return _LATEST
        ptr, length = ctypes.c_void_p(), ctypes.c_uint()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)) or not length.value:
            return _LATEST
        info = (ctypes.c_uint32 * 13).from_address(ptr.value)  # VS_FIXEDFILEINFO
        ms, ls = info[2], info[3]
        return (ms >> 16, ms & 0xFFFF, ls >> 16)
    except (AttributeError, OSError, ValueError):
        return _LATEST


class Traits:
    def __init__(self, family: str, exe: Path):
        self.family = family
        self.spec = FAMILIES[family]
        self.exe = exe
        self.name = exe.stem.lower()

    def gzdoom_at_least(self, version: tuple[int, int, int]) -> bool:
        return self.family == "ZDoom" and (
            (self.name == "gzdoom" and exe_version(self.exe) >= version) or self.name in ("uzdoom", "vkdoom"))

    @property
    def pistol_start(self) -> str | None:
        return "-pistolstart" if self.family in ("ChocolateDoom", "PrBoom") or self.name == "woof" else None

    @property
    def cheats(self) -> list[str]:
        return ["+sv_cheats", "1"] if self.family == "ZDoom" else []

    @property
    def detailed_options(self) -> bool:
        """dmflags and per-flag compat options: only ZDoom ports have them."""
        return self.family == "ZDoom"

    @property
    def screenshot_dir_param(self) -> str | None:
        return "-shotdir" if self.family in ("ZDoom", "PrBoom") or self.name == "doomretro" else None

    def map_args(self, name: str) -> list[str]:
        if not name:
            return []
        if self.spec.map_style == "map":
            return ["+map", name]
        if m := re.search(r"E(\d+)M(\d+)", name):
            return ["-warp", m[1], m[2]]
        if m := re.search(r"MAP(\d+)", name):
            return ["-warp", m[1]]
        return []  # DoomRunner falls back to the map's position in its list, which isn't saved

    def compat_mode_args(self, mode: int) -> list[str]:
        if self.gzdoom_at_least((4, 8, 0)):
            return ["-compatmode", str(mode)]
        if self.spec.compat_style == "zdoom":
            return ["+compatmode", str(mode)]
        if self.spec.compat_style == "prboom":
            return ["-complevel", str(mode)]
        return []

    def load_game_args(self, save_file: str, save_dir: str | None) -> list[str]:
        if not save_file:
            return []
        if self.family == "ZDoom":
            if self.gzdoom_at_least((4, 9, 0)) or not save_dir:
                return ["-loadgame", save_file]
            return ["-loadgame", str(Path(save_dir) / save_file)]
        if m := re.match(r"^[a-zA-Z_\-]+(\d+)\.", save_file):
            return ["-loadgame", m[1]]
        if self.name == "woof" and save_file == "autosave.dsg":
            return ["-loadgame", "255"]
        return ["-loadgame", "invalid_file_name"]

    def monitor_index(self, own: int) -> str:
        return str(_MONITOR_BASE.get(self.name, 0) + own)


# ZDoom compatibility flags in DoomRunner's order: compatflags1 bits 0-31, then compatflags2 bits 0-4.
COMPAT_CVARS_1 = (
    "compat_shorttex", "compat_stairs", "compat_limitpain", "compat_silentpickup", "compat_nopassover",
    "compat_soundslots", "compat_wallrun", "compat_notossdrops", "compat_useblocking", "compat_nodoorlight",
    "compat_ravenscroll", "compat_soundtarget", "compat_dehhealth", "compat_trace", "compat_dropoff",
    "compat_boomscroll", "compat_invisibility", "compat_silentinstantfloors", "compat_sectorsounds",
    "compat_missileclip", "compat_crossdropoff", "compat_anybossdeath", "compat_minotaur", "compat_mushroom",
    "compat_mbfmonstermove", "compat_corpsegibs", "compat_noblockfriends", "compat_spritesort", "compat_hitscan",
    "compat_light", "compat_polyobj", "compat_maskedmidtex",
)
COMPAT_CVARS_2 = ("compat_badangles", "compat_floormove", "compat_soundcutoff", "compat_pointonline", "compat_multiexit")


def compat_flag_args(flags1: int, flags2: int) -> list[str]:
    args: list[str] = []
    for flags, names in ((flags1, COMPAT_CVARS_1), (flags2, COMPAT_CVARS_2)):
        for bit, cvar in enumerate(names):
            if flags & (1 << bit):
                args += ["+" + cvar, "1"]
    return args
