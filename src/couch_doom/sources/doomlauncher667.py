"""Read-only view of Doom Launcher 667 (Realm667's WinUI rewrite): the same DoomLauncher.sqlite, read its way.

Differences from the classic launcher that change what a game loads: no profiles, collections (tags) sorted
by name, IWADs named by IWads.FileName (unpacked from their zip if needed), and every game's own
Files / FilesSourcePort / FilesIWAD lists plus the port's files added after the game.
"""
from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path

from ..config import FROZEN, PROJECT_ROOT
from ..options import Engine, Options, Preset
from .doomlauncher import DB_NAME, LIBRARY, UNTAGGED, _connect, _int, _Library, _title, _unpack_dest, is_667

NAME = "Doom Launcher 667"
EXES = ("doomlauncher667.exe",)
SETTINGS_NAMES = (DB_NAME,)
_DEH = (".deh", ".bex")


def candidates() -> list[Path]:
    found = [PROJECT_ROOT / DB_NAME, PROJECT_ROOT.parent / DB_NAME] if FROZEN else []
    if env := os.environ.get("DOOMLAUNCHER_DATABASE"):
        found.append(Path(os.path.expandvars(env.strip().strip('"'))))
    if base := os.environ.get("LOCALAPPDATA"):
        found.append(Path(base) / "DoomLauncher667" / DB_NAME)
    return found


def matches(path: Path) -> bool:
    return path.suffix.lower() == ".sqlite" and is_667(path)


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in re.split(r"[;,]", value or "") if v.strip()]


def _path(lib: _Library, name: str) -> Path:
    p = Path(os.path.expandvars(name.strip()))
    return p if p.is_absolute() else lib.game_dir / p


def _zip_members(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        return [m for m in zf.namelist() if not m.endswith("/")]


def _game_files(lib: _Library, name: str, exts: set[str], specific: list[str], unpack: list, issues: list) -> list[Path]:
    """PrepareGameArchiveAsync: folders and port-loadable files as they are, zip contents filtered."""
    path = _path(lib, name)
    if path.is_dir() or path.suffix.lower() in exts or not path.exists():
        return [path]  # build_command reports it if missing
    if path.suffix.lower() != ".zip":
        issues.append(f"{path.name} only plays from Doom Launcher 667")
        return []
    try:
        members = _zip_members(path)
    except (OSError, zipfile.BadZipFile):
        issues.append(f"Not a valid zip: {path.name}")
        return []
    if specific:
        wanted = {s.lower() for s in specific} | {Path(s).name.lower() for s in specific}
        members = [m for m in members if m.lower() in wanted or Path(m).name.lower() in wanted]
    else:
        members = [m for m in members if Path(m).suffix.lower() in exts]
    if not members:
        issues.append(f"Nothing in {path.name} this port can load")
    out = []
    for m in members:
        dest = _unpack_dest(path, m)
        unpack.append((path, m, dest))
        out.append(dest)
    return out


def _iwad_name(iwad) -> str:
    return Path((iwad["FileName"] or "").strip()).name


def _iwad(lib: _Library, iwad, unpack: list, issues: list) -> Path | None:
    """PrepareIwadAsync: the file named IWads.FileName, either the stored file itself or inside its zip."""
    row = lib.files.get(iwad["GameFileID"])
    if row is None:
        return None
    # IWads.FileName is a bare name for managed IWADs but a full path for ones the classic launcher left in place.
    path, inner = _path(lib, row["FileName"]), _iwad_name(iwad)
    if path.name.lower() == inner.lower() or not path.is_file():
        return path
    if path.suffix.lower() != ".zip":
        issues.append(f"{path.name} only plays from Doom Launcher 667")
        return None
    try:
        member = next((m for m in _zip_members(path) if Path(m).name.lower() == inner.lower()), None)
    except (OSError, zipfile.BadZipFile):
        issues.append(f"Not a valid zip: {path.name}")
        return None
    if member is None:
        issues.append(f"{inner} isn't inside {path.name}")
        return None
    dest = _unpack_dest(path, member)
    unpack.append((path, member, dest))
    return dest


def _map_args(warp: str) -> list[str]:
    warp = warp.strip().upper()
    if re.fullmatch(r"E\dM\d", warp):
        return ["-warp", warp[1], warp[3]]
    if re.fullmatch(r"MAP\d\d", warp):
        return ["-warp", str(int(warp[3:]))]
    return ["+map", warp]


def _preset(lib: _Library, game, section: str) -> Preset:
    port_id = _int(game["SourcePortID"]) or _int(lib.config.get("DefaultSourcePort"))
    port = lib.ports.get(port_id)
    unpack: list = []
    issues: list[str] = []
    preset = Preset(name=_title(game), section=section, engine_id=str(port_id or ""), iwad=None, mods=[], unpack=unpack, issues=issues)
    if port is None:
        return preset
    extra = game["SettingsExtraParams"] or ""
    if game["SettingsExtraParamsOnly"]:
        preset.additional_args = extra
        return preset

    iwad = lib.iwads.get(_int(game["IWadID"]) or _int(lib.config.get("DefaultIWad")))
    files: list[Path] = []
    if iwad is not None:
        base = iwad
        # Hexen: Deathkings is an add-on: HEXEN.WAD stays the IWAD and HEXDD.WAD loads as the first file.
        if _iwad_name(iwad).upper() == "HEXDD.WAD":
            base = next((i for i in lib.iwads.values() if _iwad_name(i).upper() == "HEXEN.WAD"), None)
            if base is None:
                issues.append("Hexen: Deathkings needs HEXEN.WAD set up as an IWAD")
            elif dk := _iwad(lib, iwad, unpack, issues):
                files.append(dk)
        if base is not None:
            preset.iwad = _iwad(lib, base, unpack, issues)

    exts = {e if e.startswith(".") else "." + e for e in lib.port_exts(port)}
    if iwad is None or game["GameFileID"] != iwad["GameFileID"]:
        files += _game_files(lib, game["FileName"], exts, _split(game["SettingsSpecificFiles"]), unpack, issues)
    names = [*_split(game["SettingsFiles"]), *_split(game["SettingsFilesSourcePort"]), *_split(game["SettingsFilesIWAD"]),
             *_split(port["SettingsFiles"])]
    for name in dict.fromkeys(n.lower() for n in names):
        row = lib.by_name.get(name)
        if row is not None and row["GameFileID"] != game["GameFileID"]:
            files += _game_files(lib, row["FileName"], exts, [], unpack, issues)
    preset.mods = list(dict.fromkeys(files))

    args: list[str] = []
    if warp := (game["SettingsMap"] or "").strip():
        args += _map_args(warp)
    if skill := (game["SettingsSkill"] or "").strip():
        args += ["-skill", skill]
    preset.additional_args = " ".join(a for a in (" ".join(args), extra, port["ExtraParameters"] or "") if a)
    return preset


def load(path: Path) -> Options:
    con = _connect(path)
    try:
        lib = _Library(con, path.parent, game_dir="Data", tags_by_name=True)
    finally:
        con.close()

    engines = {
        str(pid): Engine(id=str(pid), name=p["Name"] or Path(p["Executable"]).stem, path=lib._abs(p["Directory"] or "") / (p["Executable"] or ""),
                         config_dir=None, family=NAME)
        for pid, p in lib.ports.items()
    }
    fallback = UNTAGGED if lib.tags else LIBRARY
    presets: list[Preset] = []
    for gid, game in lib.files.items():
        tags = lib.file_tags.get(gid, [])
        if gid in lib.iwad_files and not tags:
            continue
        presets.append(_preset(lib, game, tags[0] if tags else fallback))

    order = {t["Name"]: i for i, t in enumerate(lib.tags)}
    presets.sort(key=lambda p: (order.get(p.section, len(order)), p.name.lower()))
    return Options(
        path=path,
        engines=engines,
        default_engine=str(_int(lib.config.get("DefaultSourcePort")) or next(iter(engines), "")),
        presets=presets,
        global_args="",
        global_env={},
        cmd_prefix="",
        sections=list(dict.fromkeys(p.section for p in presets)),
        launcher=NAME,
    )
