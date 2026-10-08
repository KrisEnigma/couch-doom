"""The system "Open" dialog: Windows' own through ctypes, zenity or kdialog elsewhere, so no GUI toolkit is needed."""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
from ctypes import wintypes
from pathlib import Path

_OFN_NOCHANGEDIR, _OFN_PATHMUSTEXIST, _OFN_FILEMUSTEXIST, _OFN_EXPLORER = 0x8, 0x800, 0x1000, 0x80000


class _OpenFileName(ctypes.Structure):
    _fields_ = [
        ("lStructSize", wintypes.DWORD), ("hwndOwner", wintypes.HWND), ("hInstance", wintypes.HINSTANCE),
        ("lpstrFilter", wintypes.LPCWSTR), ("lpstrCustomFilter", wintypes.LPWSTR), ("nMaxCustFilter", wintypes.DWORD),
        ("nFilterIndex", wintypes.DWORD), ("lpstrFile", wintypes.LPWSTR), ("nMaxFile", wintypes.DWORD),
        ("lpstrFileTitle", wintypes.LPWSTR), ("nMaxFileTitle", wintypes.DWORD), ("lpstrInitialDir", wintypes.LPCWSTR),
        ("lpstrTitle", wintypes.LPCWSTR), ("Flags", wintypes.DWORD), ("nFileOffset", wintypes.WORD),
        ("nFileExtension", wintypes.WORD), ("lpstrDefExt", wintypes.LPCWSTR), ("lCustData", wintypes.LPARAM),
        ("lpfnHook", ctypes.c_void_p), ("lpTemplateName", wintypes.LPCWSTR), ("pvReserved", ctypes.c_void_p),
        ("dwReserved", wintypes.DWORD), ("FlagsEx", wintypes.DWORD),
    ]


def _unix_tool() -> str | None:
    """zenity (GNOME and most desktops) or kdialog (KDE); KDE users get theirs first."""
    order = ("kdialog", "zenity") if "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper() else ("zenity", "kdialog")
    return next((p for name in order if (p := shutil.which(name))), None)


def available() -> bool:
    return os.name == "nt" or _unix_tool() is not None


def open_file(title: str, filters: list[tuple[str, str]], owner: int | None = None) -> Path | None:
    """filters: (label, "*.exe;options.json") pairs. Returns None if cancelled or no dialog is available."""
    if os.name != "nt":
        return _open_unix(title, filters)
    buf = ctypes.create_unicode_buffer(1024)
    spec = "".join(f"{label}\0{pattern}\0" for label, pattern in filters) + "\0"
    ofn = _OpenFileName()
    ofn.lStructSize = ctypes.sizeof(ofn)
    ofn.hwndOwner = owner
    ofn.lpstrFilter = spec
    ofn.nFilterIndex = 1
    ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
    ofn.nMaxFile = len(buf)
    ofn.lpstrTitle = title
    ofn.Flags = _OFN_EXPLORER | _OFN_FILEMUSTEXIST | _OFN_PATHMUSTEXIST | _OFN_NOCHANGEDIR
    if not ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn)):
        return None
    return Path(buf.value) if buf.value else None


def _open_unix(title: str, filters: list[tuple[str, str]]) -> Path | None:
    tool = _unix_tool()
    if not tool:
        return None
    globs = [(label, ["*" if p == "*.*" else p for p in pattern.split(";")]) for label, pattern in filters]
    if Path(tool).name == "kdialog":
        spec = "\n".join(f"{label} ({' '.join(pats)})" for label, pats in globs)
        argv = [tool, "--title", title, "--getopenfilename", str(Path.home()), spec]
    else:
        argv = [tool, "--file-selection", f"--title={title}",
                *(f"--file-filter={label} | {' '.join(pats)}" for label, pats in globs)]
    try:
        out = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError:
        return None
    path = out.stdout.strip()
    return Path(path) if out.returncode == 0 and path else None
