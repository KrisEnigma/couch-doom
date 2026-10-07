"""Launcher UI sounds, taken from the game data itself (Doom's menu sounds in the IWAD).

Nothing engine-specific: any Doom-format IWAD carries these lumps. Without one the launcher is silent.
"""
from __future__ import annotations

import io
import struct
from collections import Counter
from pathlib import Path

import pygame

from .archive import Wad, open_archive
from .options import Options

# Same lumps Doom's own menu uses for each gesture.
LUMPS = {
    "move": "DSPSTOP",
    "confirm": "DSPISTOL",
    "open": "DSSWTCHN",
    "close": "DSSWTCHX",
    "error": "DSOOF",
}
VOLUMES = {"move": 0.22, "confirm": 0.30, "open": 0.30, "close": 0.30, "error": 0.32}


def _dmx_to_wav(data: bytes) -> bytes | None:
    """DMX digital sound (format 3, 8-bit unsigned mono) wrapped as a WAV so SDL resamples it."""
    if len(data) < 8:
        return None
    fmt, rate, count = struct.unpack_from("<HHI", data, 0)
    if fmt != 3 or not rate:
        return None
    # DMX pads 16 bytes on each side of the samples.
    pcm = data[8 + 16 : 8 + count - 16] if count > 32 else data[8 : 8 + count]
    header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, 1, rate, rate, 1, 8, b"data", len(pcm))
    return header + pcm


def _source_iwad(opts: Options) -> Path | None:
    """The IWAD most presets use is the one the player knows the menu sounds from."""
    counts = Counter(p.iwad for p in opts.presets if p.iwad and p.iwad.is_file())
    for iwad, _ in counts.most_common():
        a = open_archive(iwad)
        if isinstance(a, Wad):
            has = a.lump(LUMPS["move"]) is not None
            a.close()
            if has:
                return iwad
        elif a:
            a.close()
    return None


class Sfx:
    def __init__(self, opts: Options, channel: pygame.mixer.Channel):
        self.channel = channel  # "move" gets its own channel so fast scrolling doesn't stack clicks
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        iwad = _source_iwad(opts)
        if not iwad:
            return
        a = open_archive(iwad)
        if not a:
            return
        try:
            for name, lump in LUMPS.items():
                data = a.lump(lump)
                wav = _dmx_to_wav(data) if data else None
                if not wav:
                    continue
                try:
                    snd = pygame.mixer.Sound(file=io.BytesIO(wav))
                except pygame.error:
                    continue
                snd.set_volume(VOLUMES[name])
                self.sounds[name] = snd
        finally:
            a.close()

    def play(self, name: str) -> None:
        snd = self.sounds.get(name)
        if snd is None:
            return
        if name == "move":
            self.channel.play(snd)
        else:
            snd.play()
