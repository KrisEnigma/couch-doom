"""Read-only view of DoomRunner's options.json."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .. import engine_traits
from ..config import DEV_LAUNCHERS, FROZEN, PROJECT_ROOT, home, xdg
from ..options import Engine, Options, Preset

NAME = "DoomRunner"
EXES = ("doomrunner.exe", "doomrunner")
SETTINGS_NAMES = ("options.json",)

# DoomRunner's OptionsStorage enum.
DONT_STORE, STORE_GLOBALLY, STORE_TO_PRESET = 0, 1, 2

_STORAGE_KEYS = {
    "launch": ("launch_opts", "launch_options"),
    "gameplay": ("gameplay_opts", "gameplay_options"),
    "compat": ("compat_opts", "compatibility_options"),
    "video": ("video_opts", "video_options"),
    "audio": ("audio_opts", "audio_options"),
}


def candidates() -> list[Path]:
    env = os.environ.get("DOOMRUNNER_OPTIONS")
    if env:
        return [Path(env)]
    # Portable DoomRunner keeps options.json beside its exe; installed, in the per-user app data folder.
    found = [PROJECT_ROOT / "options.json", PROJECT_ROOT.parent / "options.json"] if FROZEN else []
    if DEV_LAUNCHERS:
        found.append(DEV_LAUNCHERS / "DoomRunner" / "options.json")
    if os.name == "nt":
        for var in ("LOCALAPPDATA", "APPDATA"):
            if base := os.environ.get(var):
                found.append(Path(base) / "DoomRunner" / "options.json")
    elif sys.platform == "darwin":
        found.append(home() / "Library" / "Application Support" / "DoomRunner" / "options.json")
    else:
        found += [xdg("XDG_DATA_HOME", ".local/share") / "DoomRunner" / "options.json",
                  home() / ".var/app/io.github.Youda008.DoomRunner/data/DoomRunner/options.json",
                  home() / ".var/app/io.github.Youda008.DoomRunner/.local/share/DoomRunner/options.json"]
    return found


def matches(path: Path) -> bool:
    return path.suffix.lower() == ".json"


def _section_title(raw: str) -> str:
    return raw.strip().strip("-").strip() or "Presets"


def _path(base: Path, value: str | None) -> Path | None:
    if not value:
        return None
    p = Path(value)
    return p if p.is_absolute() else (base / p)


def load(path: Path) -> Options:
    data = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent

    engines_block = data.get("engines") or {}
    engines: dict[str, Engine] = {}
    for e in engines_block.get("engine_list") or []:
        exe = _path(base, e.get("path"))
        if not exe:
            continue
        eid = e.get("id") or e.get("name") or str(exe)
        engines[eid] = Engine(
            id=eid,
            name=e.get("name") or exe.stem,
            path=exe,
            config_dir=_path(base, e.get("config_dir")),
            family=engine_traits.detect(e.get("family"), exe),
        )

    storage = data.get("options_storage") or {}
    global_groups = {
        group: data.get(json_key) or {}
        for group, (_, json_key) in _STORAGE_KEYS.items()
    }

    presets: list[Preset] = []
    sections: list[str] = []
    section = "Presets"
    for raw in data.get("presets") or []:
        if raw.get("separator"):
            section = _section_title(raw.get("name", ""))
            continue
        if section not in sections:
            sections.append(section)

        groups: dict[str, dict] = {}
        for group, (storage_key, json_key) in _STORAGE_KEYS.items():
            mode = storage.get(storage_key, STORE_GLOBALLY)
            if mode == STORE_TO_PRESET:
                groups[group] = raw.get(json_key) or {}
            elif mode == STORE_GLOBALLY:
                groups[group] = global_groups[group]
            else:
                groups[group] = {}

        entries: list[Path | str] = []
        for m in raw.get("mods") or []:
            if m.get("separator") or not m.get("checked", True):
                continue
            if m.get("cmd_argument"):
                entries.append(m.get("value") or "")
            elif p := _path(base, m.get("path")):
                entries.append(p)

        presets.append(
            Preset(
                name=raw.get("name", "Unnamed"),
                section=section,
                engine_id=raw.get("selected_engine") or "",
                iwad=_path(base, raw.get("selected_IWAD")),
                mods=[e for e in entries if isinstance(e, Path)],
                mod_entries=entries,
                mappacks=[
                    p for v in raw.get("selected_mappacks") or [] if (p := _path(base, v))
                ],
                load_maps_after_mods=bool(raw.get("load_maps_after_mods")),
                additional_args=raw.get("additional_args") or "",
                selected_config=raw.get("selected_config") or "",
                alternative_paths=raw.get("alternative_paths") or {},
                env_vars=raw.get("env_vars") or {},
                groups=groups,
            )
        )

    global_opts = data.get("global_options") or {}
    return Options(
        path=path,
        engines=engines,
        default_engine=engines_block.get("default_engine") or "",
        presets=presets,
        global_args=global_opts.get("additional_args") or "",
        global_env=global_opts.get("env_vars") or {},
        cmd_prefix=global_opts.get("cmd_prefix") or "",
        sections=sections,
        launcher=NAME,
    )
