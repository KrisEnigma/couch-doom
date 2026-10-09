"""Minimal read-only access to WAD and PK3/ZIP lumps."""
from __future__ import annotations

import re
import struct
import threading
import zipfile
from collections import OrderedDict
from pathlib import Path

ZIP_EXTS = {".pk3", ".ipk3", ".zip", ".pke"}
WAD_EXTS = {".wad", ".iwad"}
_MAPINFO = ("zmapinfo", "mapinfo")
_INCLUDE_RE = re.compile(rb'^\s*include\s+"?([^"\s]+)"?', re.IGNORECASE | re.MULTILINE)


def _search_mapinfo(read, data: bytes, pattern: re.Pattern, seen: set[str]) -> str | None:
    """Search one MAPINFO and the files it includes; big TCs keep GameInfo in an included file."""
    if m := pattern.search(data):
        return m.group(1).decode("ascii", "replace")
    for inc in _INCLUDE_RE.findall(data):
        name = inc.decode("ascii", "replace").lower()
        if name not in seen and len(seen) < 64:
            seen.add(name)
            if (sub := read(name)) and (v := _search_mapinfo(read, sub, pattern, seen)):
                return v
    return None


# WADs inside a pk3 are compressed: reaching a lump means decompressing up to it, which takes a noticeable moment
# in a 100+ MB WAD. Their directories, and the lumps actually read, are kept across lookups.
_EMBED_LOCK = threading.Lock()
_EMBED_DIRS: dict[tuple, dict[str, tuple[int, int]]] = {}
_EMBED_LUMPS: OrderedDict[tuple, bytes] = OrderedDict()
EMBED_CACHE_BYTES = 48 * 1024 * 1024


class Wad:
    def __init__(self, path: Path, f=None, key: tuple | None = None):
        self.path = path
        self.key = key  # set for a WAD inside a pk3, whose reads are cached
        self.f = f if f is not None else path.open("rb")
        try:
            with _EMBED_LOCK:
                lumps = _EMBED_DIRS.get(key) if key else None
            if lumps is None:
                lumps = self._directory()
                if key:
                    with _EMBED_LOCK:
                        _EMBED_DIRS[key] = lumps
        except Exception:
            self.f.close()
            raise
        self.lumps = lumps

    def _directory(self) -> dict[str, tuple[int, int]]:
        magic, count, offset = struct.unpack("<4sii", self.f.read(12))
        if magic not in (b"IWAD", b"PWAD"):
            raise ValueError("not a wad")
        self.f.seek(offset)
        raw = self.f.read(16 * count)
        lumps: dict[str, tuple[int, int]] = {}
        for i in range(count):
            pos, size, name = struct.unpack_from("<ii8s", raw, i * 16)
            lumps[name.split(b"\0", 1)[0].decode("ascii", "replace").upper()] = (pos, size)
        return lumps

    def lump(self, name: str, folders: tuple[str, ...] = ()) -> bytes | None:
        key = Path(name).stem.upper()[:8]
        entry = self.lumps.get(key)
        if not entry or entry[1] <= 0:
            return None
        if self.key is None:
            self.f.seek(entry[0])
            return self.f.read(entry[1])
        ck = (self.key, key)
        with _EMBED_LOCK:
            if (data := _EMBED_LUMPS.get(ck)) is not None:
                _EMBED_LUMPS.move_to_end(ck)
                return data
        self.f.seek(entry[0])
        data = self.f.read(entry[1])
        if len(data) <= EMBED_CACHE_BYTES // 4:
            with _EMBED_LOCK:
                _EMBED_LUMPS[ck] = data
                while sum(len(v) for v in _EMBED_LUMPS.values()) > EMBED_CACHE_BYTES:
                    _EMBED_LUMPS.popitem(last=False)
        return data

    def music_names(self) -> list[str]:
        return []  # WAD lumps are found by name; only pk3 folders can be searched blind

    def mapinfo_value(self, pattern: re.Pattern) -> str | None:
        for name in _MAPINFO:
            data = self.lump(name)
            if data and (v := _search_mapinfo(self.lump, data, pattern, set())):
                return v
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

    def music_names(self) -> list[str]:
        return sorted(n for n in self.names if n.startswith("music/") and "/" not in n[6:])

    def embedded(self) -> list[Wad]:
        """WADs in the pk3's root, which GZDoom loads right after the pk3 itself (big TCs keep everything in one)."""
        try:
            stamp = self.path.stat().st_mtime_ns
        except OSError:
            return []
        out = []
        for n in sorted(n for n in self.names if "/" not in n and Path(n).suffix in WAD_EXTS):
            real = self.names[n]
            try:
                out.append(Wad(self.path / real, self.z.open(real), (str(self.path), stamp, real)))
            except (OSError, ValueError, struct.error, zipfile.BadZipFile, RuntimeError):
                pass
        return out

    def mapinfo_value(self, pattern: re.Pattern) -> str | None:
        for n, real in self.names.items():
            if "/" not in n and Path(n).stem in _MAPINFO:
                if v := _search_mapinfo(self._path, self.read(real), pattern, set()):
                    return v
        return None

    def _path(self, name: str) -> bytes | None:
        real = self.names.get(name.lower().replace("\\", "/"))
        return self.read(real) if real else None

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
                if isinstance(a, Zip):
                    self.items += reversed(a.embedded())
                self.items.append(a)

    def __enter__(self) -> "Archives":
        return self

    def __exit__(self, *exc) -> None:
        for a in self.items:
            a.close()

    def mapinfo_value(self, pattern: re.Pattern) -> str | None:
        return next((v for a in self.items if (v := a.mapinfo_value(pattern))), None)

    def guess_music(self, pattern: re.Pattern) -> bytes | None:
        """A track in a pk3's music folder whose name matches pattern, in override order."""
        for a in self.items:
            for n in a.music_names():
                if pattern.search(Path(n).stem) and (data := a.read(a.names[n])):
                    return data
        return None

    def find(self, names: list[str], folders: tuple[str, ...] = ("",)) -> bytes | None:
        """First name (in priority order) that any archive provides, honoring override order per name."""
        for name in names:
            for a in self.items:
                if data := a.lump(name, folders):
                    return data
        return None
