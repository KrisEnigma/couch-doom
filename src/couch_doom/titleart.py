"""Find a preset's title screen inside its WAD/PK3 files.

Search runs from the last-loaded file back to the IWAD, matching the engine's
override order. Returns raw data only; surfaces are built on the main thread.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

from .archive import Archives

PNG_SIG = b"\x89PNG\r\n\x1a\n"
TITLEPAGE_RE = re.compile(rb'titlepage\s*=\s*"([^"]+)"', re.IGNORECASE)
GRAPHIC_FOLDERS = ("graphics/", "")


@dataclass
class Art:
    kind: str  # "encoded" (png/jpg bytes) | "indexed" (8-bit pixels + palette)
    data: bytes
    size: tuple[int, int] = (0, 0)
    palette: bytes = b""
    mask: bytes = b""  # indexed only: 255 where a patch has a pixel, 0 where it's transparent


def _decode_patch(data: bytes) -> tuple[int, int, bytes, bytes] | None:
    """Doom picture format (column posts, tall-patch aware): width, height, pixels, mask."""
    if len(data) < 8:
        return None
    w, h, _, _ = struct.unpack_from("<hhhh", data, 0)
    if not (0 < w <= 2048 and 0 < h <= 2048) or len(data) < 8 + 4 * w:
        return None
    offsets = struct.unpack_from(f"<{w}I", data, 8)
    buf = bytearray(w * h)
    mask = bytearray(w * h)
    n = len(data)
    for x, off in enumerate(offsets):
        if off >= n:
            return None
        top = -1
        while off < n and data[off] != 0xFF:
            delta, length = data[off], data[off + 1] if off + 1 < n else 0
            top = delta + top if delta <= top else delta
            pixels = data[off + 3 : off + 3 + length]
            for i, px in enumerate(pixels):
                y = top + i
                if y < h:
                    buf[y * w + x] = px
                    mask[y * w + x] = 255
            off += length + 4
    return w, h, bytes(buf), bytes(mask)


def _decode(data: bytes, palette: bytes | None) -> Art | None:
    if data.startswith(PNG_SIG) or data.startswith(b"\xff\xd8"):
        return Art("encoded", data)
    if not palette:
        return None
    if len(data) == 320 * 200:  # Heretic/Hexen raw TITLE
        return Art("indexed", data, (320, 200), palette)
    if patch := _decode_patch(data):
        w, h, pixels, mask = patch
        return Art("indexed", pixels, (w, h), palette, mask)
    return None


def _palette(arcs: Archives) -> bytes | None:
    return next((p[:768] for a in arcs.items if (p := a.lump("PLAYPAL")) and len(p) >= 768), None)


def find_title_art(iwad: Path | None, files: list[Path]) -> Art | None:
    with Archives(iwad, files) as arcs:
        if not arcs.items:
            return None
        page = arcs.mapinfo_value(TITLEPAGE_RE)
        candidates = ([page] if page else []) + ["TITLEPIC", "TITLE"]
        palette = _palette(arcs)
        for name in candidates:
            for a in arcs.items:
                data = a.lump(name, GRAPHIC_FOLDERS)
                if data and (art := _decode(data, palette)):
                    return art
        return None


LOGO_LUMPS = ["M_DOOM", "M_HTIC", "M_STRIFE"]  # main-menu logo: Doom, Heretic/Hexen, Strife
LOGO_MAX_H = 130  # menu logos are small patches; taller "logos" are full screens or menu frames


def _same_picture(a: tuple, b: tuple) -> bool:
    """Is this the stock logo again? Re-saves differ by a byte or two and mods with their own palette
    recolour it, so compare the silhouette (patch mask), not bytes or palette indices."""
    if a[:2] != b[:2]:
        return False
    differ = sum(1 for p, q in zip(a[3], b[3]) if p != q)
    return differ < len(a[3]) * 0.02


def _logo_rgba(patch: tuple, palette: bytes) -> Art | None:
    w, h, pixels, mask = patch
    if h > LOGO_MAX_H or w < h:
        return None
    out = bytearray(w * h * 4)
    ink = 0
    for i, (p, m) in enumerate(zip(pixels, mask)):
        if m:
            r, g, b = palette[p * 3 : p * 3 + 3]
            out[i * 4 : i * 4 + 4] = bytes((r, g, b, 255))
            ink += r + g + b > 120
    if ink < w * h * 0.05:  # blank or near-black: authors who hid the menu logo on purpose
        return None
    return Art("rgba", bytes(out), (w, h))


def find_logo(iwad: Path | None, files: list[Path]) -> Art | None:
    """The preset's own main-menu logo. The IWAD's logo only when nothing else is loaded: on a mod
    it would name the base game, and PWADs that merely re-ship it count as having none."""
    with Archives(iwad, []) as base, Archives(None, files) as own:
        palette = _palette(own) or _palette(base)
        if not palette:
            return None
        stock = base.find(LOGO_LUMPS, GRAPHIC_FOLDERS)
        stock_patch = _decode_patch(stock) if stock else None
        if not files:
            return _logo_rgba(stock_patch, palette) if stock_patch else None
        data = own.find(LOGO_LUMPS, GRAPHIC_FOLDERS)
        if not data:
            return None
        if data.startswith(PNG_SIG):
            return Art("encoded", data)
        patch = _decode_patch(data)
        if not patch or (stock_patch and _same_picture(patch, stock_patch)):
            return None
        return _logo_rgba(patch, palette)
