"""Read-only view of Doom Launcher (hobomaster22 / nstlaurent): its DoomLauncher.sqlite library.

Every game file with saved settings, plus each of its profiles, becomes a preset; tags become sections.
Launch arguments follow Doom Launcher's own GameFilePlayAdapter so a preset starts the same way it would there.
"""
from __future__ import annotations

import os
import re
import sqlite3
import zipfile
import zlib
from pathlib import Path

from ..config import DEV_LAUNCHERS, FROZEN, PROJECT_ROOT, STATE_DIR
from ..options import Engine, Options, Preset

NAME = "Doom Launcher"
DB_NAME = "DoomLauncher.sqlite"
EXES = ("doomlauncher.exe",)
SETTINGS_NAMES = (DB_NAME,)
UNTAGGED = "Untagged"
LIBRARY = "Library"
UNPACK_DIR = STATE_DIR / "unpacked"
_PACKAGED = (".zip",)
_UNSUPPORTED_PACKAGED = (".7z", ".rar")


def candidates() -> list[Path]:
    found = [PROJECT_ROOT / DB_NAME, PROJECT_ROOT.parent / DB_NAME] if FROZEN else []
    if base := os.environ.get("APPDATA"):
        found.append(Path(base) / "DoomLauncher" / DB_NAME)
    if DEV_LAUNCHERS:
        found.append(DEV_LAUNCHERS / "DoomLauncher" / DB_NAME)
    return found


def matches(path: Path) -> bool:
    return path.suffix.lower() == ".sqlite" and not is_667(path)


def is_667(path: Path) -> bool:
    """Doom Launcher 667 keeps the same database but adds its own WinUI_* tables on first start."""
    try:
        con = _connect(path)
    except sqlite3.Error:
        return False
    try:
        return con.execute("select 1 from sqlite_master where type = 'table' and name like 'WinUI\\_%' escape '\\' limit 1").fetchone() is not None
    except sqlite3.Error:
        return False
    finally:
        con.close()


def _connect(path: Path) -> sqlite3.Connection:
    # mode=ro: Doom Launcher may be open, and CouchDoom must never write to its library.
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=2)
    con.row_factory = sqlite3.Row
    return con


def _split(value: str | None) -> list[str]:
    return [v for v in (value or "").split(";") if v]


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class _Library:
    def __init__(self, con: sqlite3.Connection, base: Path, game_dir: str = "GameFiles", tags_by_name: bool = False):
        self.base = base
        self.config = {r["Name"]: r["Value"] for r in con.execute("select Name, Value from Configuration")}
        self.game_dir = self._abs(os.path.expandvars(self.config.get("GameFileDirectory") or game_dir))
        self.files = {r["GameFileID"]: r for r in con.execute("select * from GameFiles")}
        self.by_name = {r["FileName"].lower(): r for r in self.files.values() if r["FileName"]}
        self.ports = {r["SourcePortID"]: r for r in con.execute("select * from SourcePorts where LaunchType = '0' or LaunchType = 0")
                      if not ("Archived" in r.keys() and _int(r["Archived"]))}
        self.iwads = {r["IWadID"]: r for r in con.execute("select * from IWads")}
        self.iwad_files = {r["GameFileID"] for r in self.iwads.values() if r["GameFileID"] is not None}
        self.profiles = con.execute("select * from GameProfiles order by GameProfileID").fetchall()
        order = "Name collate nocase" if tags_by_name else "TagID"
        self.tags = con.execute(f"select * from Tags order by {order}").fetchall()
        rank = {t["TagID"]: i for i, t in enumerate(self.tags)}
        self.file_tags: dict[int, list[str]] = {}
        for m in sorted(con.execute("select FileID, TagID from TagMapping"), key=lambda m: rank.get(m["TagID"], -1)):
            if m["TagID"] in rank:
                self.file_tags.setdefault(m["FileID"], []).append(self.tags[rank[m["TagID"]]]["Name"])

    def _abs(self, value: str) -> Path:
        p = Path(os.path.expandvars(value))
        return p if p.is_absolute() else self.base / p

    def lookup(self, name: str):
        """Doom Launcher's GetGameFile: exact FileName, or one ending in \\name."""
        hit = self.by_name.get(name.lower())
        if hit is None:
            tail = "\\" + name.lower()
            hit = next((r for k, r in self.by_name.items() if k.endswith(tail)), None)
        return hit

    def port_exts(self, port) -> list[str]:
        return [e.strip().lower() for e in (port["SupportedExtensions"] or "").split(",") if e.strip()]


def _unpack_dest(archive: Path, member: str) -> Path:
    tag = f"{zlib.crc32(str(archive).lower().encode()):08x}"
    return UNPACK_DIR / f"{archive.stem}-{tag}" / Path(member).name


def _game_files(lib: _Library, row, exts: list[str], specific: list[str], unpack: list) -> tuple[list[Path], list[str]]:
    """What one game file contributes to the command line (GetFilesFromGameFileSettings)."""
    name = row["FileName"]
    path = lib._abs(name) if Path(name).is_absolute() else lib.game_dir / name
    unmanaged = Path(name).is_absolute()
    suffix = path.suffix.lower()
    if unmanaged and path.is_dir():
        return [path], []
    if unmanaged and suffix not in _PACKAGED:
        if suffix in _UNSUPPORTED_PACKAGED:
            return [], [f"Can't read {suffix} archives: {path.name}"]
        if specific and str(path) not in specific:
            return [], []
        return [path], []
    if not path.is_file():
        return [path], []  # build_command reports it missing
    try:
        with zipfile.ZipFile(path) as zf:
            members = [m for m in zf.namelist() if not m.endswith("/")]
    except (OSError, zipfile.BadZipFile):
        return [], [f"Not a valid zip: {path.name}"]
    if specific:
        members = [m for m in members if m in specific]
    else:
        members = [m for m in members if "." in Path(m).name and Path(m).suffix.lower() in exts]
    out = []
    for m in members:
        dest = _unpack_dest(path, m)
        unpack.append((path, m, dest))
        out.append(dest)
    return out, []


def _warp_args(port, warp: str) -> list[str]:
    exe = (port["Executable"] or "").lower()
    if "zdoom.exe" in exe or Path(exe).stem in ("zandronum", "helion"):
        return ["+map", warp]
    if re.fullmatch(r"E\dM\d|MAP\d\d", warp):
        return ["-warp", *[str(int(n)) for n in re.findall(r"\d+", warp)]]
    return ["+map", warp]


def _preset(lib: _Library, game, settings, name: str, section: str) -> Preset:
    """settings is the game file itself or one of its GameProfiles rows: both carry the Settings* columns."""
    port_id = _int(settings["SourcePortID"]) or _int(lib.config.get("DefaultSourcePort"))
    port = lib.ports.get(port_id)
    unpack: list = []
    issues: list[str] = []
    preset = Preset(name=name, section=section, engine_id=str(port_id or ""), iwad=None, mods=[], unpack=unpack, issues=issues)
    if port is None:
        return preset

    exts = lib.port_exts(port)
    extra = settings["SettingsExtraParams"] or ""
    if settings["SettingsExtraParamsOnly"]:
        preset.additional_args = extra
        return preset

    is_iwad = game["GameFileID"] in lib.iwad_files
    iwad_row = game if is_iwad else None
    if iwad_row is None:
        iwad = lib.iwads.get(_int(settings["IWadID"]) or _int(lib.config.get("DefaultIWad")))
        iwad_row = lib.files.get(iwad["GameFileID"]) if iwad else None
    if iwad_row is not None:
        files, errs = _game_files(lib, iwad_row, exts, _split(iwad_row["SettingsSpecificFiles"]), unpack)
        preset.iwad = files[0] if files else None
        issues += errs or ([] if files else [f"No IWAD inside {Path(iwad_row['FileName']).name}"])

    # FileLoadHandler: saved files (the game first if it was never placed), then the IWAD's and the port's own extras.
    load = [r for n in _split(settings["SettingsFiles"]) if (r := lib.lookup(n)) is not None]
    if all(r["GameFileID"] != game["GameFileID"] for r in load):
        load.insert(0, game)
    if iwad_row is not None:
        skip = {n.lower() for n in _split(iwad_row["SettingsFilesSourcePort"])}
        load += [r for n in _split(iwad_row["SettingsFiles"]) if n.lower() not in skip and (r := lib.lookup(n)) is not None]
    load += [r for n in _split(port["SettingsFiles"]) if (r := lib.lookup(n)) is not None]
    seen: set[int] = set()
    specific = _split(settings["SettingsSpecificFiles"])
    for r in load:
        if r["GameFileID"] in seen or (iwad_row is not None and r["GameFileID"] == iwad_row["GameFileID"]):
            continue
        seen.add(r["GameFileID"])
        files, errs = _game_files(lib, r, exts, specific, unpack)
        preset.mods += files
        issues += errs

    args: list[str] = []
    if warp := (settings["SettingsMap"] or "").strip():
        args += _warp_args(port, warp)
        args += ["-skill", (settings["SettingsSkill"] or lib.config.get("DefaultSkill") or "3").strip()]
    preset.additional_args = " ".join(a for a in (" ".join(args), extra, port["ExtraParameters"] or "") if a)
    return preset


def _title(row) -> str:
    return (row["Title"] or "").strip() or Path(row["FileName"] or "?").stem


def load(path: Path) -> Options:
    con = _connect(path)
    try:
        lib = _Library(con, path.parent)
    finally:
        con.close()

    engines = {
        str(pid): Engine(id=str(pid), name=p["Name"] or Path(p["Executable"]).stem, path=lib._abs(p["Directory"] or "") / (p["Executable"] or ""),
                         config_dir=None, family=NAME)
        for pid, p in lib.ports.items()
    }
    fallback = UNTAGGED if lib.tags else LIBRARY
    profiles: dict[int, list] = {}
    for prof in lib.profiles:
        profiles.setdefault(prof["GameFileID"], []).append(prof)

    presets: list[Preset] = []
    for gid, game in lib.files.items():
        tags = lib.file_tags.get(gid, [])
        # IWADs live in Doom Launcher's IWADs tab; they only join the list once tagged like a game.
        if gid in lib.iwad_files and not tags:
            continue
        section = tags[0] if tags else fallback
        title = _title(game)
        presets.append(_preset(lib, game, game, title, section))
        for prof in profiles.get(gid, []):
            presets.append(_preset(lib, game, prof, f"{title} ({prof['Name']})", section))

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
