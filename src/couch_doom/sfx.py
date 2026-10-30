"""Launcher UI sounds from a Doom-family IWAD or the bundled Freedoom fallback."""
from __future__ import annotations

import io
import struct
from collections import Counter
from pathlib import Path

import pygame

from .archive import Wad, open_archive
from .config import ASSET_DIR
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
EASTER_EGG_LUMP = "DSGETPOW"
IWAD_NAMES = {
    "doom.wad", "doom1.wad", "doom2.wad", "tnt.wad", "plutonia.wad",
    "freedoom1.wad", "freedoom2.wad", "freedm.wad",
}
FREEDOOM_SOUNDS = ASSET_DIR / "freedoom"


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
    """Find the most-used known Doom-family IWAD, excluding shared Hexen/Strife lumps."""
    counts = Counter(p.iwad for p in opts.presets if p.iwad and p.iwad.is_file())
    for iwad, _ in counts.most_common():
        if iwad.name.casefold() not in IWAD_NAMES:
            continue
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
        archive = open_archive(iwad) if iwad else None
        try:
            for name, lump in LUMPS.items():
                sound = self._from_lump(archive, lump) if archive else None
                sound = sound or self._from_file(FREEDOOM_SOUNDS / f"{lump.lower()}.wav")
                self._store(name, sound, VOLUMES[name])
            secret = self._from_lump(archive, EASTER_EGG_LUMP) if archive else None
            if secret is None:
                secret = self._from_file(FREEDOOM_SOUNDS / "dsgetpow.wav")
            self._store("secret", secret, 0.42)
        finally:
            if archive:
                archive.close()

    @staticmethod
    def _from_lump(archive, lump: str) -> pygame.mixer.Sound | None:
        data = archive.lump(lump)
        wav = _dmx_to_wav(data) if data else None
        return Sfx._from_file(io.BytesIO(wav)) if wav else None

    @staticmethod
    def _from_file(source) -> pygame.mixer.Sound | None:
        try:
            return pygame.mixer.Sound(file=source)
        except (pygame.error, OSError):
            return None

    def _store(self, name: str, sound: pygame.mixer.Sound | None, volume: float) -> None:
        if sound is None:
            return
        sound.set_volume(volume)
        self.sounds[name] = sound

    def play(self, name: str) -> None:
        snd = self.sounds.get(name)
        if snd is None:
            return
        if name == "move":
            self.channel.play(snd)
        else:
            snd.play()
