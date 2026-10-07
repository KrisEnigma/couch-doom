"""The standard Windows "Open" dialog, through ctypes so the build needs no GUI toolkit."""
from __future__ import annotations

import ctypes
import os
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


def open_file(title: str, filters: list[tuple[str, str]], owner: int | None = None) -> Path | None:
    """filters: (label, "*.exe;options.json") pairs. Returns None if cancelled or not on Windows."""
    if os.name != "nt":
        return None
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
