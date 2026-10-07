"""Minimal read-only access to WAD and PK3/ZIP lumps."""
from __future__ import annotations

import re
import struct
import zipfile
from pathlib import Path

ZIP_EXTS = {".pk3", ".ipk3", ".zip", ".pke"}
WAD_EXTS = {".wad", ".iwad"}
_MAPINFO = ("zmapinfo", "mapinfo")


class Wad:
    def __init__(self, path: Path):
        self.path = path
        self.f = path.open("rb")
        magic, count, offset = struct.unpack("<4sii", self.f.read(12))
        if magic not in (b"IWAD", b"PWAD"):
            raise ValueError("not a wad")
        self.f.seek(offset)
        raw = self.f.read(16 * count)
        self.lumps: dict[str, tuple[int, int]] = {}
        for i in range(count):
            pos, size, name = struct.unpack_from("<ii8s", raw, i * 16)
            self.lumps[name.split(b"\0", 1)[0].decode("ascii", "replace").upper()] = (pos, size)

    def lump(self, name: str, folders: tuple[str, ...] = ()) -> bytes | None:
        key = Path(name).stem.upper()[:8]
        entry = self.lumps.get(key)
        if not entry or entry[1] <= 0:
            return None
        self.f.seek(entry[0])
        return self.f.read(entry[1])

    def mapinfo_value(self, pattern: re.Pattern) -> str | None:
        for name in _MAPINFO:
            data = self.lump(name)
            if data and (m := pattern.search(data)):
                return m.group(1).decode("ascii", "replace")
        return None

    def close(self) -> None:
        self.f.close()


class Zip:
    def __init__(self, path: Path):
        self.path = path
        self.z = zipfile.ZipFile(path)
        self.names = {n.lower(): n for n in self.z.namelist() if not n.endswith("/")}

    def read(self, real: str) -> bytes:
        return self.z.read(real)

    def lump(self, name: str, folders: tuple[str, ...] = ("",)) -> bytes | None:
        """Exact path first, then a file with that stem (any extension) inside one of `folders`."""
        lname = name.lower().replace("\\", "/")
        if lname in self.names:
            return self.read(self.names[lname])
        stem = Path(lname).stem
        for folder in folders:
            for n, real in self.names.items():
                if n.startswith(folder) and "/" not in n[len(folder):] and Path(n).stem == stem:
                    return self.read(real)
        return None

    def mapinfo_value(self, pattern: re.Pattern) -> str | None:
        for n, real in self.names.items():
            if "/" not in n and Path(n).stem in _MAPINFO:
                if m := pattern.search(self.read(real)):
                    return m.group(1).decode("ascii", "replace")
        return None

    def close(self) -> None:
        self.z.close()


def open_archive(path: Path) -> Wad | Zip | None:
    ext = path.suffix.lower()
    try:
        if ext in ZIP_EXTS:
            return Zip(path)
        if ext in WAD_EXTS:
            return Wad(path)
    except (OSError, ValueError, zipfile.BadZipFile, struct.error):
        pass
    return None


class Archives:
    """Open archives in override order: last-loaded file first, IWAD last."""

    def __init__(self, iwad: Path | None, files: list[Path]):
        self.items: list[Wad | Zip] = []
        for path in [*reversed(files), *([iwad] if iwad else [])]:
            if path.is_file() and (a := open_archive(path)):
                self.items.append(a)

    def __enter__(self) -> "Archives":
        return self

    def __exit__(self, *exc) -> None:
        for a in self.items:
            a.close()

    def mapinfo_value(self, pattern: re.Pattern) -> str | None:
        return next((v for a in self.items if (v := a.mapinfo_value(pattern))), None)

    def find(self, names: list[str], folders: tuple[str, ...] = ("",)) -> bytes | None:
        """First name (in priority order) that any archive provides, honoring override order per name."""
        for name in names:
            for a in self.items:
                if data := a.lump(name, folders):
                    return data
        return None
