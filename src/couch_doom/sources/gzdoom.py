"""GZDoom, UZDoom and VKDoom on their own, for players without a launcher: one entry per IWAD the port would offer.

Mirrors the port's startup IWAD picker (UZDoom src/d_iwad.cpp): the search folders come from the port's ini, each
candidate file is identified by the lumps listed in the port's iwadinfo.txt, and the list keeps one file per game
in iwadinfo's display order. The port's own files are only read, never written.
"""
from __future__ import annotations

import os
import re
import shutil
import struct
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from ..config import DEV_LAUNCHERS, FROZEN, PROJECT_ROOT, home, xdg
from ..options import Engine, Options, OptionsError, Preset

NAME = "GZDoom"
SECTION = "IWADs"
# Lower-case ini/exe name -> the folder name the port uses in Documents and app bundles.
PORTS = {"gzdoom": "GZDoom", "uzdoom": "UZDoom", "vkdoom": "VKDoom"}
FLATPAKS = {"org.zdoom.gzdoom": "gzdoom"}
EXES = tuple(n for p in PORTS for n in (f"{p}.exe", p)) + tuple(FLATPAKS)
SETTINGS_NAMES = EXES
IWAD_EXTS = (".iwad", ".ipk3", ".ipk7")
RECURSIVE_LIMIT = 5000

# The port's own iwadinfo decides names and order; without it, these file names are still recognised.
_FALLBACK_NAMES = (
    "doom_complete.pk3", "doom2.wad", "doom2xbox.wad", "doom2unity.wad", "doom2kex.wad", "doom2f.wad", "doomu.wad",
    "doom.wad", "doomxbox.wad", "doomunity.wad", "doomkex.wad", "doom1.wad", "bfgdoom.wad", "bfgdoom2.wad",
    "doombfg.wad", "doom2bfg.wad", "plutonia.wad", "plutoniaunity.wad", "plutoniakex.wad", "tnt.wad",
    "tntunity.wad", "tntkex.wad", "freedoom1.wad", "freedoom2.wad", "freedoomu.wad", "freedoom.wad", "freedm.wad",
    "heretic.wad", "hereticsr.wad", "heretic1.wad", "hexen.wad", "hexdd.wad", "hexendemo.wad", "hexdemo.wad",
    "strife1.wad", "sve.wad", "strife0.wad", "strife.wad", "blasphem.wad", "blasphemer.wad", "chex.wad",
    "chex3.wad", "action2.wad", "harm1.wad", "hacx.wad", "hacx2.wad", "square1.pk3", "delaweare.wad", "rotwb.wad",
)

# Storefront folders the port searches when i_searchdistributors is on (UZDoom src/d_steam.cpp, win32/i_steam.cpp).
_STEAM_DIRS = (
    "Doom 2/base", "Final Doom/base", "Heretic Shadow of the Serpent Riders/base", "Hexen/base",
    "Hexen Deathkings of the Dark Citadel/base", "Ultimate Doom/base", "Ultimate Doom/base/doom2",
    "Ultimate Doom/base/tnt", "Ultimate Doom/base/plutonia", "DOOM 3 BFG Edition/base/wads", "Strife",
    "Ultimate Doom/rerelease/DOOM_Data/StreamingAssets", "Ultimate Doom/rerelease",
    "Doom 2/rerelease/DOOM II_Data/StreamingAssets", "Doom 2/finaldoombase", "Master Levels of Doom/doom2",
    "Heretic + Hexen/dos/base/heretic", "Heretic + Hexen/dos/base/hexen", "Heretic + Hexen/dos/base/hexendk",
)
_GOG_GAMES = (
    ("1435827232", ("",)), ("2015545325", ("DOOM_Data/StreamingAssets",)), ("1435848814", ("doom2",)),
    ("1426071866", ("DOOM II_Data/StreamingAssets",)), ("1413291984", ("",)), ("1435848742", ("TNT", "Plutonia")),
    ("1135892318", ("base/wads",)), ("1432899949", ("",)), ("1290366318", ("",)), ("1247951670", ("",)),
    ("1983497091", ("",)),
)
_BETHESDA_DIRS = (
    "DOOM_Classic_2019/base", "DOOM_Classic_2019/rerelease/DOOM_Data/StreamingAssets", "DOOM_II_Classic_2019/base",
    "DOOM_II_Classic_2019/rerelease/DOOM II_Data/StreamingAssets", "DOOM 3 BFG Edition/base/wads",
    "Heretic Shadow of the Serpent Riders/base", "Hexen/base", "Hexen Deathkings of the Dark Citadel/base",
)


@dataclass
class IwadInfo:
    name: str
    lumps: list[str]
    required: str = ""


@dataclass
class IwadTable:
    infos: list[IwadInfo] = field(default_factory=list)
    names: set[str] = field(default_factory=set)
    order: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- which port, where


def port_of(path: Path) -> str | None:
    """'uzdoom' for uzdoom.exe, a UZDoom AppImage or a GZDoom Flatpak launcher; None if it isn't one of these ports."""
    name = path.name.lower()
    if name in FLATPAKS:
        return FLATPAKS[name]
    if name.endswith(".appimage"):
        name = name.removesuffix(".appimage").split("-")[0]
    name = name.removesuffix(".exe")
    return name if name in PORTS else None


def matches(path: Path) -> bool:
    return port_of(path) is not None and path.is_file()


def label(path: Path) -> str:
    return PORTS.get(port_of(path) or "", NAME)


def beside(folder: Path) -> Path | None:
    """The port in a dropped folder, including a macOS app bundle."""
    bins = [folder, folder / "Contents" / "MacOS"]
    return next((p for d in bins for n in EXES if (p := d / n).is_file()), None)


def _program_files() -> list[Path]:
    return [Path(v) for k in ("ProgramFiles", "ProgramFiles(x86)") if (v := os.environ.get(k))]


def candidates() -> list[Path]:
    found: list[Path] = []
    folders = [PROJECT_ROOT, PROJECT_ROOT.parent] if FROZEN else []
    if DEV_LAUNCHERS:
        folders.append(DEV_LAUNCHERS)
    for port, title in PORTS.items():
        found += [f / (f"{port}.exe" if os.name == "nt" else port) for f in folders]
        if which := shutil.which(port):
            found.append(Path(which))
        if os.name == "nt":
            found += [base / title / f"{port}.exe" for base in _program_files()]
        elif sys.platform == "darwin":
            found += [base / f"{title}.app" / "Contents" / "MacOS" / port for base in (Path("/Applications"), home() / "Applications")]
        else:
            found += [Path(d) / port for d in ("/usr/bin", "/usr/games", "/usr/local/bin", "/usr/local/games")]
            found.append(Path("/opt") / port / port)
    if os.name != "nt" and sys.platform != "darwin":
        for app in FLATPAKS:
            flatpak_id = "org.zdoom.GZDoom" if app == "org.zdoom.gzdoom" else app
            found += [Path("/var/lib/flatpak/exports/bin") / flatpak_id,
                      xdg("XDG_DATA_HOME", ".local/share") / "flatpak" / "exports" / "bin" / flatpak_id]
    return list(dict.fromkeys(found))


def _documents() -> Path:
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:  # CSIDL_PERSONAL
            return Path(buf.value)
    except (AttributeError, OSError):
        pass
    return home() / "Documents"


def _is_flatpak(exe: Path) -> bool:
    return exe.name.lower() in FLATPAKS


def ini_candidates(exe: Path) -> list[Path]:
    """Where the port reads its ini from, most specific first (UZDoom's M_GetConfigPath per OS)."""
    port = port_of(exe) or "gzdoom"
    title = PORTS.get(port, port)
    if os.name == "nt":
        found = []
        if not any(str(exe).lower().startswith(str(p).lower()) for p in _program_files()):
            found.append(exe.parent / f"{port}_portable.ini")
        found.append(_documents() / "My Games" / title / f"{port}.ini")
        if user := os.environ.get("USERNAME"):
            found.append(exe.parent / f"{port}-{user.replace('/', '_').replace(chr(92), '_')}.ini")
        if appdata := os.environ.get("APPDATA"):
            found.append(Path(appdata) / title / f"{port}.ini")
        return found
    if sys.platform == "darwin":
        return [home() / "Library" / "Preferences" / f"{port}.ini"]
    if _is_flatpak(exe):
        app = home() / ".var" / "app" / exe.name
        return [app / "config" / port / f"{port}.ini", app / ".config" / port / f"{port}.ini"]
    return [xdg("XDG_CONFIG_HOME", ".config") / port / f"{port}.ini"]


def _read_ini(path: Path) -> dict[str, list[tuple[str, str]]]:
    """The port's ini repeats keys (Path=...), so it's read as ordered (key, value) pairs per section."""
    sections: dict[str, list[tuple[str, str]]] = {}
    current: list[tuple[str, str]] | None = None
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1].lower(), [])
        elif current is not None and "=" in line:
            key, value = line.split("=", 1)
            current.append((key.strip(), value.strip()))
    return sections


def _default_search(exe: Path) -> list[tuple[str, str]]:
    """What a port writes into a fresh ini (UZDoom src/gameconfigfile.cpp), for one that has never been started."""
    port = port_of(exe) or "gzdoom"
    paths = [".", "$DOOMWADDIR"]
    if os.name == "nt":
        paths += ["$HOME", "$PROGDIR"]
    elif sys.platform == "darwin":
        title = PORTS.get(port, port)
        paths += [str(home() / "Documents" / title), str(home() / "Library" / "Application Support" / title),
                  f"/Library/Application Support/{title}", "$PROGDIR"]
    else:
        data = xdg("XDG_DATA_HOME", ".local/share")
        paths.append("$PROGDIR")
        for sub in (f"/games/{port}", "/games/doom", "/doom"):
            paths += [f"{data}{sub}", f"/usr/local/share{sub}", f"/usr/share{sub}"]
    return [("Path", p) for p in paths]


# ---------------------------------------------------------------- search folders


_VAR = re.compile(r"\$([0-9A-Za-z_]+)")


def _expand(value: str, progdir: Path) -> str:
    """The port's NicePath: ~ on Unix, $PROGDIR, and any other $VAR from the environment (unset ones vanish)."""
    if os.name != "nt" and value.startswith("~"):
        value = str(home()) + value[1:]

    def var(m: re.Match) -> str:
        return str(progdir) if m.group(1).lower() == "progdir" else os.environ.get(m.group(1), "")

    return _VAR.sub(var, value)


def _steam_root() -> Path | None:
    if os.name == "nt":
        return Path(p) if (p := _registry([("HKCU", r"Software\Valve\Steam", "SteamPath"),
                                            ("HKLM", r"Software\Valve\Steam", "InstallPath")])) else None
    if sys.platform == "darwin":
        return home() / "Library" / "Application Support" / "Steam"
    return home() / ".local" / "share" / "Steam"


def _registry(lookups: list[tuple[str, str, str]]) -> str | None:
    try:
        import winreg
    except ImportError:
        return None
    hives = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
    for hive, key, value in lookups:
        try:
            with winreg.OpenKey(hives[hive], key) as k:
                v, kind = winreg.QueryValueEx(k, value)
                if kind == winreg.REG_SZ and v:
                    return v
        except OSError:
            continue
    return None


def _distributor_dirs() -> list[Path]:
    found: list[Path] = []
    if os.name == "nt":
        gog = r"Software\Wow6432Node\GOG.com\Games" if sys.maxsize > 2**32 else r"Software\GOG.com\Games"
        for game_id, subs in _GOG_GAMES:
            if base := _registry([("HKLM", rf"{gog}\{game_id}", "Path")]):
                found += [Path(base) / s if s else Path(base) for s in subs]
    steam = _steam_root()
    if steam and steam.is_dir():
        libraries: list[Path] = []
        try:
            vdf = (steam / "config" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
            libraries = [Path(m.replace("\\\\", "\\")) / "steamapps" / "common"
                         for m in re.findall(r'"path"\s+"((?:[^"\\]|\\.)*)"', vdf, re.I)]
        except OSError:
            pass
        libraries.append(steam / "steamapps" / "common")
        found += [lib / d for d in _STEAM_DIRS for lib in libraries if (lib / d).is_dir()]
    if os.name == "nt":
        beth = r"Software\Wow6432Node\Bethesda Softworks\Bethesda.net" if sys.maxsize > 2**32 else r"Software\Bethesda Softworks\Bethesda.net"
        if base := _registry([("HKLM", beth, "installLocation")]):
            found += [Path(base) / "games" / d for d in _BETHESDA_DIRS]
    return found


def search_dirs(exe: Path, ini: dict[str, list[tuple[str, str]]] | None) -> tuple[list[Path], list[Path]]:
    """(plain, recursive) IWAD folders, in the port's search order."""
    entries = ini.get("iwadsearch.directories") if ini is not None else None
    if entries is None:
        entries = _default_search(exe)
    plain: list[Path] = []
    recursive: list[Path] = []
    for key, value in entries:
        k = key.lower()
        if k not in ("path", "recursivepath"):
            continue
        expanded = _expand(value, exe.parent)
        if not expanded:
            continue
        p = Path(expanded)
        (plain if k == "path" else recursive).append(p if p.is_absolute() else exe.parent / p)
    settings = dict((k.lower(), v) for k, v in (ini or {}).get("globalsettings", []))
    if settings.get("i_searchdistributors", "true").lower() not in ("false", "0"):
        plain += _distributor_dirs()
    return plain, recursive


# ---------------------------------------------------------------- iwadinfo


_TOKEN = re.compile(r'"([^"]*)"|([^\s,={}"]+)|([={},])')


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def parse_iwadinfo(text: str) -> IwadTable:
    table = IwadTable()
    tokens = [(m.group(1) if m.group(1) is not None else m.group(2) or m.group(3), m.group(1) is not None)
              for m in _TOKEN.finditer(_strip_comments(text))]
    i = 0
    while i < len(tokens):
        word = tokens[i][0].lower()
        if i + 1 >= len(tokens) or tokens[i + 1][0] != "{":
            i += 1
            continue
        end = next((j for j in range(i + 2, len(tokens)) if tokens[j][0] == "}" and not tokens[j][1]), len(tokens))
        body = tokens[i + 2:end]
        if word == "iwad":
            fields: dict[str, list[str]] = {}
            key = None
            for j, (tok, quoted) in enumerate(body):
                if not quoted and j + 1 < len(body) and body[j + 1] == ("=", False):
                    key = tok.lower()
                    fields[key] = []
                elif key and (quoted or tok not in ("=", ",")):
                    fields[key].append(tok)
            if name := (fields.get("name") or [""])[0]:
                table.infos.append(IwadInfo(name, fields.get("mustcontain", []), (fields.get("required") or [""])[0]))
        elif word == "names":
            table.names |= {tok.lower() for tok, quoted in body if quoted}
        elif word == "order":
            table.order += [tok for tok, quoted in body if quoted]
        i = end + 1
    if not table.order:
        table.order = [info.name for info in table.infos]
    return table


def _engine_data_dirs(exe: Path) -> list[Path]:
    port = port_of(exe) or "gzdoom"
    dirs = [exe.parent, exe.parent.parent / "Resources", exe.parent.parent / "share" / "games" / port,
            exe.parent.parent / "share" / port, exe.parent.parent / "lib" / port]
    if os.name != "nt" and sys.platform != "darwin":
        dirs += [xdg("XDG_DATA_HOME", ".local/share") / "games" / port]
        dirs += [Path(p) / port for p in ("/usr/share/games", "/usr/local/share/games", "/usr/share", "/usr/lib", "/opt")]
        if _is_flatpak(exe):
            for root in (Path("/var/lib/flatpak/app"), xdg("XDG_DATA_HOME", ".local/share") / "flatpak" / "app"):
                files = root / exe.name / "current" / "active" / "files"
                dirs += [files, files / "share" / "games" / port, files / "share" / port, files / "lib" / port]
    return dirs


def load_iwadinfo(exe: Path) -> IwadTable | None:
    port = port_of(exe) or "gzdoom"
    for folder in _engine_data_dirs(exe):
        for pk3 in ("game_support.pk3", f"{port}.pk3"):
            path = folder / pk3
            if not path.is_file():
                continue
            try:
                with zipfile.ZipFile(path) as zf:
                    member = next((n for n in zf.namelist() if n.lower() in ("iwadinfo.txt", "iwadinfo")), None)
                    if member:
                        return parse_iwadinfo(zf.read(member).decode("latin-1"))
            except (OSError, zipfile.BadZipFile):
                continue
    return None


# ---------------------------------------------------------------- identifying a file


def _wad_lumps(path: Path) -> list[tuple[str, int, int]] | None:
    """(name, offset, size) for every lump of a WAD, or None if it isn't one."""
    with open(path, "rb") as fh:
        head = fh.read(12)
        if len(head) < 12 or head[:4] not in (b"IWAD", b"PWAD"):
            return None
        count, offset = struct.unpack("<ii", head[4:])
        if count < 0 or offset < 0:
            return None
        fh.seek(offset)
        raw = fh.read(16 * count)
    lumps = []
    for k in range(len(raw) // 16):
        pos, size, name = struct.unpack("<ii8s", raw[16 * k:16 * k + 16])
        lumps.append((name.split(b"\0", 1)[0].decode("latin-1"), pos, size))
    return lumps


def _short_names(path: Path) -> set[str] | None:
    """What the port compares MustContain against: lump names, archive file names without extension,
    and map names from maps/*.wad."""
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                names = set()
                for n in zf.namelist():
                    if n.endswith("/"):
                        continue
                    names.add(Path(n).stem.upper())
                    if n.lower().startswith("maps/"):
                        names.add(n[5:].split(".")[0].upper())
                return names
        lumps = _wad_lumps(path)
    except (OSError, struct.error, zipfile.BadZipFile):
        return None
    return {n.upper() for n, _, _ in lumps} if lumps is not None else None


def _own_iwadinfo_name(path: Path) -> str | None:
    """A .iwad/.ipk3 names itself in its own IWADINFO."""
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                member = next((n for n in zf.namelist() if n.lower() in ("iwadinfo.txt", "iwadinfo")), None)
                text = zf.read(member).decode("latin-1") if member else None
        else:
            lumps = _wad_lumps(path) or []
            hit = next(((pos, size) for n, pos, size in lumps if n.upper() == "IWADINFO"), None)
            text = None
            if hit:
                with open(path, "rb") as fh:
                    fh.seek(hit[0])
                    text = fh.read(hit[1]).decode("latin-1")
    except (OSError, struct.error, zipfile.BadZipFile):
        return None
    if not text:
        return None
    table = parse_iwadinfo(text)
    return table.infos[0].name if table.infos else None


def identify(path: Path, table: IwadTable) -> str | None:
    if path.suffix.lower() in IWAD_EXTS:
        return _own_iwadinfo_name(path)
    found = _short_names(path)
    if found is None:
        return None
    return next((info.name for info in table.infos if info.lumps and all(l.upper() in found for l in info.lumps)), None)


# ---------------------------------------------------------------- the list


def _scan(folder: Path, recursive: bool, names: set[str]) -> list[Path]:
    out: list[Path] = []
    try:
        if recursive:
            seen = 0
            for dirpath, _, files in os.walk(folder):
                for f in files:
                    seen += 1
                    if seen > RECURSIVE_LIMIT:
                        return out
                    if f.lower() in names or Path(f).suffix.lower() in IWAD_EXTS:
                        out.append(Path(dirpath) / f)
        else:
            out = [p for p in sorted(folder.iterdir()) if p.is_file() and
                   (p.name.lower() in names or p.suffix.lower() in IWAD_EXTS)]
    except OSError:
        pass
    return out


def find_iwads(exe: Path, ini: dict[str, list[tuple[str, str]]] | None) -> tuple[list[tuple[str, Path]], list[Path]]:
    """([(display name, file)], folders searched), the way the port's IWAD picker would list them."""
    table = load_iwadinfo(exe)
    fallback = table is None
    if table is None:
        table = IwadTable(names=set(_FALLBACK_NAMES))
    plain, recursive = search_dirs(exe, ini)
    files: list[Path] = []
    for folder in plain:
        if folder.is_dir():
            files += _scan(folder, False, table.names)
    for folder in recursive:
        if folder.is_dir():
            files += _scan(folder, True, table.names)

    found: list[tuple[str, Path, bool]] = []  # (name, path, from its own IWADINFO)
    for f in files:
        if fallback and f.suffix.lower() not in IWAD_EXTS:
            found.append((f.name, f, True))
        elif name := identify(f, table):
            found.append((name, f, f.suffix.lower() in IWAD_EXTS))

    known = {n for n, _, _ in found}
    required = {info.name: info.required for info in table.infos if info.required}
    found = [x for x in found if not required.get(x[0]) or required[x[0]] in known]

    picks: list[tuple[str, Path]] = []
    for name in table.order:
        if hit := next((x for x in found if x[0] == name), None):
            picks.append((name, hit[1]))
    picked = {os.path.normcase(str(p)) for _, p in picks}
    order = set(table.order)
    for name, path, own in found:
        if own and name not in order and os.path.normcase(str(path)) not in picked:
            picks.append((name, path))
            picked.add(os.path.normcase(str(path)))
            order.add(name)
    return picks, plain + recursive


def find_ini(exe: Path) -> Path | None:
    return next((p for p in ini_candidates(exe) if p.is_file()), None)


def load(path: Path) -> Options:
    exe = path
    port = port_of(exe) or "gzdoom"
    title = label(exe)
    ini_path = find_ini(exe)
    ini = _read_ini(ini_path) if ini_path else None
    iwads, searched = find_iwads(exe, ini)
    if not iwads:
        raise OptionsError("No IWADs found", f"{title} found no game IWADs in these folders:",
                           list(dict.fromkeys(searched)) or [exe.parent], title,
                           hint=f"Put doom.wad, doom2.wad or freedoom2.wad in one of them, or add a folder to "
                                f"[IWADSearch.Directories] in {ini_path or port + '.ini'}.")
    engine = Engine(id=port, name=title, path=exe, config_dir=ini_path.parent if ini_path else None, family=NAME)
    presets = [Preset(name=name, section=SECTION, engine_id=port, iwad=file, mods=[]) for name, file in iwads]
    return Options(path=exe, engines={port: engine}, default_engine=port, presets=presets, global_args="",
                   global_env={}, cmd_prefix="", sections=[SECTION], launcher=title)
