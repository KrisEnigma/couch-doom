"""ENDOOM-style exit screens: 80x25 text-mode cells (code-page-437 character + VGA attribute byte)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .archive import Archives

COLS, ROWS = 80, 25
SIZE = COLS * ROWS * 2
LUMPS = ["ENDOOM", "ENDTEXT", "ENDSTRF"]  # Doom/Boom ports, Heretic/Hexen, Strife
VGA = [
    (0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170), (170, 0, 0), (170, 0, 170), (170, 85, 0), (170, 170, 170),
    (85, 85, 85), (85, 85, 255), (85, 255, 85), (85, 255, 255), (255, 85, 85), (255, 85, 255), (255, 255, 85), (255, 255, 255),
]


@dataclass
class Endoom:
    source: str
    data: bytes

    def cells(self):
        """(column, row, character, foreground RGB, background RGB) per cell; the blink bit is ignored."""
        for i in range(COLS * ROWS):
            code, attr = self.data[i * 2], self.data[i * 2 + 1]
            ch = bytes([code]).decode("cp437") if code >= 32 else " "
            yield i % COLS, i // COLS, ch, VGA[attr & 15], VGA[(attr >> 4) & 7]


def find_endoom(files: list[Path]) -> Endoom | None:
    """Only the preset's own files: every IWAD ships one, and the stock screen says nothing about the mod."""
    with Archives(None, files) as arcs:
        for name in LUMPS:
            for a in arcs.items:
                data = a.lump(name)
                if data and len(data) >= SIZE:
                    return Endoom(a.path.name, data[:SIZE])
    return None
