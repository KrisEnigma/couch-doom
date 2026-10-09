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
from .known import lookup

PNG_SIG = b"\x89PNG\r\n\x1a\n"
TITLEPAGE_RE = re.compile(rb'titlepage\s*=\s*"([^"]+)"', re.IGNORECASE)
TITLEMAP_RE = re.compile(rb'\bmap\s+(titlemap)\b', re.IGNORECASE)
MAINMENU_RE = re.compile(rb'listmenu\s+"mainmenu"\s*\{(.*?)\}', re.IGNORECASE | re.DOTALL)
STATICPATCH_RE = re.compile(rb'staticpatch(?:centered)?\s+-?\d+\s*,\s*-?\d+\s*,\s*"([^"]+)"', re.IGNORECASE)
GRAPHIC_FOLDERS = ("graphics/", "")
STAND_INS = ("INTERPIC", "INTERBG")
STARTUP_PLANAR = 48 + 640 * 480 // 2  # Hexen-style startup screen: 16-colour palette, four bit planes
TEXTURE_PATCH = rb'(?:graphic|texture|walltexture|sprite|flat)\s+"?%s"?\s*,[^{]*\{[^}]*?\bpatch\s+"?([^",\s]+)'


@dataclass
class Art:
    kind: str  # "encoded" (png/jpg bytes) | "indexed" (8-bit pixels + palette)
    data: bytes
    size: tuple[int, int] = (0, 0)
    palette: bytes = b""
    mask: bytes = b""  # indexed only: 255 where a patch has a pixel, 0 where it's transparent
    fallback: bool = False  # not the mod's own title picture: the base game's, or a stand-in


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


def _known_art(own: list, palette: bytes) -> Art | None:
    """The picture a known.py entry names, for mods whose best one no rule would pick."""
    for a in own:
        known = lookup(a.path.name)
        real = known and known.art and getattr(a, "names", {}).get(known.art.lower())
        if real and (art := _decode(a.read(real), palette)):
            return art
    return None


def find_title_art(iwad: Path | None, files: list[Path]) -> Art | None:
    with Archives(iwad, files) as arcs:
        if not arcs.items:
            return None
        page = arcs.mapinfo_value(TITLEPAGE_RE)
        candidates = ([page] if page else []) + ["TITLEPIC", "TITLE"]
        palette = _palette(arcs)
        searches = [(candidates, arcs.items)]
        own = [a for a in arcs.items if a.path != iwad]
        if known := _known_art(own, palette):
            return known
        if any(a.mapinfo_value(TITLEMAP_RE) for a in own):
            # A mod's 3D title map we can't render: its own intermission backdrop beats the IWAD's picture.
            searches.insert(0, (candidates + list(STAND_INS), own))
        for names, items in searches:
            for name in names:
                for a in items:
                    data = a.lump(name, GRAPHIC_FOLDERS)
                    if data and (art := _decode(data, palette)):
                        art.fallback = bool(files) and (a.path == iwad or name in STAND_INS)
                        return art
        return None


LOGO_LUMPS = ["M_DOOM", "M_HTIC", "M_STRIFE"]  # main-menu logo: Doom, Heretic/Hexen, Strife
LOGO_MAX_H = 130  # menu logos are small patches; taller "logos" are full screens or menu frames
LOGO_MIN_RATIO = 2.5  # a fallback *logo* image must be a wordmark, not an emblem or icon
LOGO_MIN_W = 160  # smaller ones are icons and HUD bits
TITLE_MIN_RATIO = 1.5  # a *title* card (Brutal Wolfenstein's 1280x720 ZMCTITLE), not a portrait or tile
STOCK_TITLES = re.compile(r"^(titlepi\w*|title|titlemap|interpic)$")
CREDIT_LOGOS = re.compile(r"^(db|udb|gz|zd|uz|lz|id|sd|doombuilder|gzdoom|zdoom|uzdoom)_?logo")  # editor and engine credits


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
        if not files:
            return _game_logo(base, palette, None)
        stock = base.find(LOGO_LUMPS, GRAPHIC_FOLDERS)
        return _game_logo(own, palette, _decode_patch(stock) if stock else None)


def _game_logo(arcs: Archives, palette: bytes, stock_patch: tuple | None) -> Art | None:
    """In order: the picture the main menu names, the usual logo lump, a wide *logo* image, a TEXTURES
    alias of the menu's picture (often a plainer menu version), then a *title* card."""
    name = _menu_logo(arcs)
    renamed = name if name and name.upper() not in LOGO_LUMPS else None
    if renamed and (data := _anywhere(arcs, renamed)):
        return _logo_art(data, palette)
    if data := arcs.find(LOGO_LUMPS, GRAPHIC_FOLDERS):
        patch = None if data.startswith(PNG_SIG) else _decode_patch(data)
        if not (patch and stock_patch and _same_picture(patch, stock_patch)):
            art = _logo_art(data, palette)  # None when blanked on purpose: the mod wants no logo
            if art and (card := _named_logo(arcs, "title")) and _width(card) >= 2 * _width(art):
                return card  # a high-res title card of the same logo (Simon's Destiny's 640px vs its 200px menu logo)
            return art
    if art := _named_logo(arcs, "logo"):
        return art
    if renamed and (alias := _texture_patch(arcs, renamed)) and (data := _anywhere(arcs, alias)):
        return _logo_art(data, palette)
    return _named_logo(arcs, "title")


def _logo_art(data: bytes, palette: bytes) -> Art | None:
    if data.startswith(PNG_SIG) or data.startswith(b"\xff\xd8"):
        return Art("encoded", data)
    patch = _decode_patch(data)
    return _logo_rgba(patch, palette) if patch else None


def _width(art: Art) -> int:
    return art.size[0] if art.kind != "encoded" else (_png_size(art.data) or (0, 0))[0]


def _png_size(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(PNG_SIG) or len(data) < 24:
        return None
    return struct.unpack_from(">II", data, 16)


def _named_logo(own: Archives, word: str) -> Art | None:
    """A wide picture named like a logo or title card, which some mods draw on a 3D title map, show in an
    intro, or keep among their textures instead of a menu logo."""
    ratio = LOGO_MIN_RATIO if word == "logo" else TITLE_MIN_RATIO
    for a in own.items:
        names = getattr(a, "names", None)
        entries = names.items() if names is not None else ((k.lower(), k) for k in a.lumps)
        for n, real in entries:
            stem = Path(n).stem.lower()
            if word not in stem or STOCK_TITLES.match(stem) or CREDIT_LOGOS.match(stem):
                continue
            data = a.read(real) if names is not None else a.lump(real)
            if data and (size := _png_size(data)) and size[0] >= max(LOGO_MIN_W, size[1] * ratio):
                return Art("encoded", data)
    return None


def _menu_logo(own: Archives) -> str | None:
    """The picture a mod's own main menu draws, which is its logo whatever the lump is called."""
    for a in own.items:
        data = a.lump("MENUDEF")
        if data and (menu := MAINMENU_RE.search(data)) and (m := STATICPATCH_RE.search(menu.group(1))):
            return m.group(1).decode("ascii", "replace")
    return None


def _renamed_menu_logo(arcs: Archives) -> bytes | None:
    """The main menu's own picture when it isn't a stock logo name. Stock names stay in the usual folders:
    elsewhere a mod's "M_DOOM" can be an unrelated menu panel."""
    name = _menu_logo(arcs)
    if not name or name.upper() in LOGO_LUMPS:
        return None
    if data := _anywhere(arcs, name):
        return data
    patch = _texture_patch(arcs, name)
    return _anywhere(arcs, patch) if patch else None


def _texture_patch(arcs: Archives, name: str) -> str | None:
    """A TEXTURES/HIRESTEX alias (Bloom's menu draws "LOGO", defined as its M_BLOOM picture)."""
    pattern = re.compile(TEXTURE_PATCH % re.escape(name.encode()), re.IGNORECASE | re.DOTALL)
    for a in arcs.items:
        for lump in ("TEXTURES", "HIRESTEX"):
            data = a.lump(lump)
            if data and (m := pattern.search(re.sub(rb"//[^\n]*", b"", data))):
                return m.group(1).decode("ascii", "replace")
    return None


def _anywhere(own: Archives, name: str) -> bytes | None:
    """A lump by name, in any folder: menus can draw sprites and textures, not just graphics."""
    stem = Path(name).stem.lower()
    for a in own.items:
        names = getattr(a, "names", None)
        if names is None:
            if data := a.lump(name):
                return data
            continue
        for n, real in names.items():
            if not n.endswith("/") and Path(n).stem == stem:
                return a.read(real)
    return None


_BITS = [[bytes(((b >> (7 - k)) & 1) << plane for k in range(8)) for b in range(256)] for plane in range(4)]


def _planar(data: bytes) -> Art:
    """Hexen's 640x480 startup screen: a 6-bit 16-colour palette, then one bit plane per colour bit."""
    palette = bytes((c << 2) | (c >> 4) for c in data[:48]).ljust(768, b"\0")
    size = 640 * 480 // 8
    pixels = 0
    for plane in range(4):
        bits = _BITS[plane]
        chunk = data[48 + plane * size : 48 + (plane + 1) * size]
        pixels |= int.from_bytes(b"".join(bits[b] for b in chunk), "big")
    return Art("indexed", pixels.to_bytes(640 * 480, "big"), (640, 480), palette)


def find_startup(files: list[Path]) -> Art | None:
    """The screen the engine shows while a mod loads. Mods without a title picture or logo of their own
    often put their real key art here."""
    with Archives(None, files) as own:
        data = own.find(["STARTUP"], GRAPHIC_FOLDERS)
    if not data:
        return None
    if data.startswith(PNG_SIG) or data.startswith(b"\xff\xd8"):
        return Art("encoded", data)
    return _planar(data) if len(data) == STARTUP_PLANAR else None
