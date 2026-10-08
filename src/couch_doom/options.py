"""The launcher-neutral model every source (DoomRunner, ZDL, ...) is read into."""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Engine:
    id: str
    name: str
    path: Path
    config_dir: Path | None
    family: str


@dataclass
class Preset:
    name: str
    section: str
    engine_id: str
    iwad: Path | None
    mods: list[Path]
    mappacks: list[Path] = field(default_factory=list)
    load_maps_after_mods: bool = False
    additional_args: str = ""
    # DoomRunner-only knobs; other launchers leave them empty.
    selected_config: str = ""
    alternative_paths: dict[str, str] = field(default_factory=dict)
    env_vars: dict[str, str] = field(default_factory=dict)
    groups: dict[str, dict] = field(default_factory=dict)
    # The checked mod list in order, where a str is a custom command-line argument rather than a file.
    mod_entries: list[Path | str] = field(default_factory=list)
    # (archive, member, destination): files that only exist once unpacked, done lazily by unpack().
    unpack: list[tuple[Path, str, Path]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)  # problems the source found while reading the preset


def unpack(preset: Preset) -> str | None:
    """Extract the preset's archive members if they aren't already; returns an error message on failure."""
    for archive, member, dest in preset.unpack:
        try:
            if dest.is_file() and dest.stat().st_mtime >= archive.stat().st_mtime:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as zf, zf.open(member) as src:
                tmp = dest.with_suffix(dest.suffix + ".part")
                tmp.write_bytes(src.read())
                tmp.replace(dest)
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            return f"Couldn't unpack {Path(member).name} from {archive.name}: {exc}"
    return None


@dataclass
class Options:
    path: Path
    engines: dict[str, Engine]
    default_engine: str
    presets: list[Preset]
    global_args: str
    global_env: dict[str, str]
    cmd_prefix: str
    sections: list[str]
    launcher: str = ""  # display name of the launcher these presets came from

    def engine_for(self, preset: Preset) -> Engine | None:
        return self.engines.get(preset.engine_id or self.default_engine)


class OptionsError(Exception):
    """Why no presets could be loaded, phrased for the player rather than as a traceback."""

    def __init__(self, title: str, detail: str, tried: list[Path], launcher: str = "", hint: str = ""):
        super().__init__(f"{title}: {detail}")
        self.title, self.detail, self.tried, self.launcher = title, detail, tried, launcher
        self.hint = hint  # what to do about it; {pick} becomes the launcher-picker button


def empty_options(path: Path, launcher: str = "") -> Options:
    return Options(path, {}, "", [], "", {}, "", [], launcher)
