"""Targets of the user's Windows shortcuts (Start Menu, Desktop, taskbar), read straight from the .lnk files.

Portable launchers have no install record, but people nearly always make a shortcut to them.
Parses just enough of the Shell Link format ([MS-SHLLINK]) to get the local target path.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

SCAN_LIMIT = 2000
_HAS_ID_LIST, _HAS_LINK_INFO, _UNICODE = 0x1, 0x2, 0x80
_VOLUME_ID_AND_LOCAL_BASE_PATH = 0x1


def _folders() -> list[Path]:
    env = os.environ.get
    out = []
    if appdata := env("APPDATA"):
        out += [Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
                Path(appdata) / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned" / "TaskBar"]
    if programdata := env("PROGRAMDATA"):
        out.append(Path(programdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    if profile := env("USERPROFILE"):
        out += [Path(profile) / "Desktop", Path(profile) / "OneDrive" / "Desktop"]
    if public := env("PUBLIC"):
        out.append(Path(public) / "Desktop")
    return out


def lnk_target(data: bytes) -> Path | None:
    if len(data) < 0x4C or struct.unpack_from("<I", data, 0)[0] != 0x4C:
        return None
    flags = struct.unpack_from("<I", data, 0x14)[0]
    pos = 0x4C
    if flags & _HAS_ID_LIST:
        pos += 2 + struct.unpack_from("<H", data, pos)[0]
    if not flags & _HAS_LINK_INFO or pos + 28 > len(data):
        return None
    size, header, info_flags, _, base_off, _, suffix_off = struct.unpack_from("<7I", data, pos)
    if not info_flags & _VOLUME_ID_AND_LOCAL_BASE_PATH:
        return None  # network-only target
    info = data[pos:pos + size]
    # The target is LocalBasePath + CommonPathSuffix (often "D:\" + "Games\Launcher.exe").
    if header >= 0x24 and len(info) >= 0x24:
        wide_base, wide_suffix = struct.unpack_from("<2I", info, 0x1C)
        text = _wide(info, wide_base) + _wide(info, wide_suffix)
    else:
        text = _ansi(info, base_off) + _ansi(info, suffix_off)
    return Path(text) if text else None


def _wide(buf: bytes, off: int) -> str:
    end = off
    while end + 1 < len(buf) and buf[end:end + 2] != b"\0\0":
        end += 2
    return buf[off:end].decode("utf-16-le", "replace")


def _ansi(buf: bytes, off: int) -> str:
    end = buf.find(b"\0", off)
    return buf[off:end if end >= 0 else len(buf)].decode("mbcs" if os.name == "nt" else "latin-1", "replace")


def targets(names: set[str]) -> list[Path]:
    """Shortcut targets whose file name (lower-case) is in `names`, de-duplicated, existing only."""
    found: dict[str, Path] = {}
    seen = 0
    for folder in _folders():
        if not folder.is_dir():
            continue
        for dirpath, _, files in os.walk(folder):
            for f in files:
                if not f.lower().endswith(".lnk"):
                    continue
                seen += 1
                if seen > SCAN_LIMIT:
                    return list(found.values())
                try:
                    with open(Path(dirpath) / f, "rb") as fh:
                        target = lnk_target(fh.read(64 * 1024))
                except OSError:
                    continue
                if target and target.name.lower() in names and target.is_file():
                    found.setdefault(str(target).lower(), target)
    return list(found.values())
