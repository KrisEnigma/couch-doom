"""Read-only view of ZDL (qZDL / lcferrum's ZDL 3): qZDL.ini plus any saved .zdl setups.

qZDL.ini holds the engine and IWAD lists and the setup currently loaded in ZDL. Each saved
.zdl file is just another [zdl.save] section that refers to those lists by name.
"""
from __future__ import annotations

import configparser
import os
from pathlib import Path

from ..config import FROZEN, PROJECT_ROOT, xdg
from ..options import Engine, Options, Preset

NAME = "ZDL"
EXES = ("zdl.exe", "qzdl.exe", "zdl", "qzdl")
SETTINGS_NAMES = ("zdl.ini", "qZDL.ini")
CURRENT = "Current setup"
SAVED = "Saved setups"
SCAN_DEPTH = 3
SCAN_LIMIT = 500
# Ports that understand +map; the rest get vanilla -warp.
_ZDOOM_LIKE = ("zdoom", "zandronum", "vkdoom", "skulltag", "zdaemon", "odamex")


def candidates() -> list[Path]:
    found = [PROJECT_ROOT / "qZDL.ini", PROJECT_ROOT.parent / "qZDL.ini"] if FROZEN else []
    if os.name == "nt":
        if base := os.environ.get("APPDATA"):
            found += [Path(base) / "Vectec Software" / "qZDL.ini", Path(base) / "Vectec Software" / "zdl.ini"]
    else:
        found.append(xdg("XDG_CONFIG_HOME", ".config") / "Vectec Software" / "qZDL.ini")  # Qt's per-user ini location
    return found


def matches(path: Path) -> bool:
    return path.suffix.lower() in (".ini", ".zdl")


def _read(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(interpolation=None, strict=False, delimiters=("=",), comment_prefixes=(";",))
    cp.optionxform = str  # keys are case-sensitive (p0n, i0f, ...)
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    cp.read_string(text, source=str(path))
    return cp


def _value(cp: configparser.ConfigParser, section: str, key: str) -> str:
    v = cp.get(section, key, fallback="").strip()
    # Qt's QSettings quotes values containing commas and similar characters.
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v


def _numbered(cp: configparser.ConfigParser, section: str, prefix: str) -> dict[str, str]:
    """zdl.ports/p0n=name, p0f=path, ... -> {name: path}."""
    out: dict[str, str] = {}
    n = 0
    while cp.has_option(section, f"{prefix}{n}n"):
        name, file = _value(cp, section, f"{prefix}{n}n"), _value(cp, section, f"{prefix}{n}f")
        if name and file:
            out[name] = file
        n += 1
    return out


def _files(cp: configparser.ConfigParser) -> list[Path]:
    files, n = [], 0
    while cp.has_option("zdl.save", f"file{n}"):
        if v := _value(cp, "zdl.save", f"file{n}"):
            files.append(Path(v))
        n += 1
    return files


def _warp_args(warp: str, zdoom_like: bool) -> list[str]:
    if zdoom_like:
        return ["+map", warp]
    w = warp.upper()
    if len(w) == 4 and w[0] == "E" and w[2] == "M":  # E1M1 -> -warp 1 1
        return ["-warp", w[1], w[3]]
    if w.startswith("MAP") and w[3:].isdigit():  # MAP02 -> -warp 2
        return ["-warp", str(int(w[3:]))]
    return ["-warp", warp]


def _preset(cp: configparser.ConfigParser, name: str, section: str, engines: dict[str, Engine], iwads: dict[str, str]) -> Preset:
    port = _value(cp, "zdl.save", "port")
    iwad = _value(cp, "zdl.save", "iwad")
    args: list[str] = []
    if warp := _value(cp, "zdl.save", "warp"):
        engine = engines.get(port)
        zdoom_like = bool(engine) and any(k in engine.path.name.lower() for k in _ZDOOM_LIKE)
        args += _warp_args(warp, zdoom_like)
    skill = _value(cp, "zdl.save", "skill")
    if skill.isdigit() and int(skill) > 0:
        args += ["-skill", skill]
    extra = _value(cp, "zdl.save", "extra")
    return Preset(
        name=name,
        section=section,
        engine_id=port,
        iwad=Path(iwads[iwad]) if iwad in iwads else None,
        mods=_files(cp),
        additional_args=" ".join([*args, extra]).strip(),
    )


def _pretty(stem: str) -> str:
    return stem.replace("_", " ").strip() or stem


def _scan(roots: list[Path]) -> list[Path]:
    """Saved .zdl setups near where ZDL last saved one, without walking whole drives."""
    seen: set[Path] = set()
    out: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            if len(Path(dirpath).parts) - base_depth >= SCAN_DEPTH:
                dirnames.clear()
            for f in filenames:
                p = (Path(dirpath) / f).resolve()
                if f.lower().endswith(".zdl") and p not in seen:
                    seen.add(p)
                    out.append(p)
                    if len(out) >= SCAN_LIMIT:
                        return out
    return out


def load(path: Path) -> Options:
    if path.suffix.lower() == ".zdl":
        return _load_single(path)
    cp = _read(path)
    engines = {
        name: Engine(id=name, name=name, path=Path(file), config_dir=None, family="ZDL")
        for name, file in _numbered(cp, "zdl.ports", "p").items()
    }
    iwads = _numbered(cp, "zdl.iwads", "i")
    presets: list[Preset] = []

    if cp.has_section("zdl.save") and (_files(cp) or _value(cp, "zdl.save", "iwad")):
        current = _preset(cp, "", CURRENT, engines, iwads)
        current.name = _pretty(current.mods[-1].stem) if current.mods else (_value(cp, "zdl.save", "iwad") or "ZDL")
        presets.append(current)

    roots = [Path(d) for key in ("zdlLastDir", "lastDir") if (d := _value(cp, "zdl.general", key))]
    roots.append(path.parent)
    saved: list[Preset] = []
    top = {r.resolve() for r in roots if r.is_dir()}
    for zdl in _scan(roots):
        try:
            z = _read(zdl)
        except (OSError, configparser.Error):
            continue
        if not z.has_section("zdl.save"):
            continue
        # Setups saved straight into ZDL's folder are "Saved setups"; subfolders the user made become sections.
        section = SAVED if zdl.parent in top else zdl.parent.name
        saved.append(_preset(z, _pretty(zdl.stem), section, engines, iwads))
    saved.sort(key=lambda p: (p.section != SAVED, p.section.lower(), p.name.lower()))
    presets += saved

    sections = list(dict.fromkeys(p.section for p in presets))
    return Options(
        path=path,
        engines=engines,
        default_engine=next(iter(engines), ""),
        presets=presets,
        global_args=_value(cp, "zdl.general", "alwaysadd"),
        global_env={},
        cmd_prefix="",
        sections=sections,
        launcher=NAME,
    )


def _load_single(zdl: Path) -> Options:
    """--options pointed at one .zdl: use it with the engine and IWAD lists from the installed ZDL."""
    main = next((p for p in candidates() if p.is_file()), None)
    opts = load(main) if main else Options(zdl, {}, "", [], "", {}, "", [], NAME)
    z = _read(zdl)
    iwads = _numbered(_read(main), "zdl.iwads", "i") if main else {}
    preset = _preset(z, _pretty(zdl.stem), SAVED, opts.engines, iwads)
    opts.presets = [preset]
    opts.sections = [SAVED]
    opts.path = zdl
    return opts
