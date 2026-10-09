"""Title music: find the track a preset's engine would play on the title screen, and render it.

Engine-agnostic: MIDI/MUS is rendered with TinySoundFont using any SoundFont we can find
(--soundfont, DOOMRUNNER_SOUNDFONT, ./soundfonts, or next to a configured engine), and
digital/tracker formats go straight to SDL_mixer.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import math
import os
import re
import struct
import threading
from array import array
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pygame

from .archive import Archives
from .config import APP_BUNDLE, DATA_DIR, PROJECT_ROOT
from .options import Options

TITLEMUSIC_RE = re.compile(rb'titlemusic\s*=\s*"([^"]+)"', re.IGNORECASE)
# Without titlemusic, a mod with a TITLEMAP plays that map's music on the title screen (Elementalism).
ACS_MUSIC_RE = re.compile(rb'music/[\w\-. ]+\.(?:mp3|ogg|flac|opus|wav|mid|mus|it|xm|s3m|mod)', re.IGNORECASE)
TITLEMAP_MUSIC_RE = re.compile(rb'\bmap\s+titlemap\b[^{]*\{[^}]*?\bmusic\s*=\s*"([^"]+)"', re.IGNORECASE)
# Per-game defaults; the IWAD itself tells us which one applies.
# Strife has D_INTRO too, but its title plays D_LOGO, so that one is checked first.
DEFAULT_TITLE_LUMPS = ("D_DM2TTL", "D_LOGO", "D_INTRO", "MUS_TITL", "HEXEN")
MUSIC_FOLDERS = ("music/", "")
# Mods that start their title music from a script or a custom title map declare it nowhere we can read, so as a last
# resort a pk3 track named like a title song is used.
TITLE_GUESS_RE = re.compile(r"^(tit|intro|menu|opening)|title", re.IGNORECASE)
DEH_TEXT_RE = re.compile(r"^Text\s+(\d+)\s+(\d+)[^\n]*\n", re.IGNORECASE | re.MULTILINE)
BEX_MUSIC_RE = re.compile(r"^\[MUSIC\][^\n]*\n(.*?)(?=^\[|\Z)", re.IGNORECASE | re.MULTILINE | re.DOTALL)
SF_EXTS = (".sf2", ".sf3")

RATE = 44100
# Rendering is synchronous before playback (~16 ms per second of dense MIDI) and PCM is float32 stereo at
# ~0.35 MB per second, so the cap sets both the wait before a track starts and how many fit in the cache.
MAX_SECONDS = 30
CUT_FADE_SECONDS = 2.5  # a track the cap cuts off fades out instead of stopping mid-phrase
TAIL_SECONDS = 2.0
VOLUME = 0.55  # streamed tracks (OGG, MP3, ...) play as mastered, at this level
# Rendered MIDI has no level of its own; each track is brought to this loudness (RMS, dBFS after gain) so the
# list sounds even. Matching peaks instead left tracks with one loud hit, like Doom II's title, much quieter.
MIDI_LOUDNESS_DB = -23.0
PEAK_TARGET = 0.9  # never louder than this, so nothing clips
# Just long enough to skip presets flown past while holding a direction (repeat is 70 ms).
DWELL_SECONDS = 0.12
FADE_IN_MS = 500
FADE_OUT_MS = 700
CACHE_BYTES = 96 * 1024 * 1024  # recent tracks kept so flipping back to a preset restarts instantly


@dataclass
class Track:
    kind: str  # "midi" | "stream" (ogg/mp3/flac/wav and mod/xm/it/s3m, decoded by SDL_mixer)
    data: bytes
    name: str


# ---------- finding ----------

def _classify(data: bytes) -> str | None:
    if data.startswith(b"MUS\x1a") or data.startswith(b"MThd"):
        return "midi"
    if data[:4] in (b"OggS", b"fLaC") or data.startswith(b"ID3") or (data[:4] == b"RIFF" and data[8:12] == b"WAVE"):
        return "stream"
    if len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0:  # bare MP3 frame sync
        return "stream"
    if data.startswith(b"Extended Module:") or data.startswith(b"IMPM") or data[44:48] == b"SCRM":
        return "stream"
    if len(data) > 1084 and data[1080:1084] in (b"M.K.", b"M!K!", b"FLT4", b"4CHN", b"6CHN", b"8CHN"):
        return "stream"
    return None


def _music_renames(arcs: Archives) -> dict[str, str]:
    """DeHackEd music renames (lump names without D_): classic `Text` string swaps, which only count when
    both sides fit a 6-character music name, and BEX [MUSIC] entries. Later-loaded files win."""
    out: dict[str, str] = {}
    for a in reversed(arcs.items):
        data = a.lump("DEHACKED")
        if not data:
            continue
        text = data.decode("latin-1").replace("\r", "")
        for m in DEH_TEXT_RE.finditer(text):
            old_len, new_len = int(m[1]), int(m[2])
            body = text[m.end():m.end() + old_len + new_len]
            old, new = body[:old_len], body[old_len:]
            if old_len <= 6 and new_len <= 6 and old.isalnum() and new.isalnum():
                out[old.upper()] = new.upper()
        if bex := BEX_MUSIC_RE.search(text):
            for line in bex[1].splitlines():
                old, eq, new = line.partition("=")
                if eq and old.strip() and new.strip():
                    out[old.strip().upper()] = new.strip().upper()
    return out


def find_title_music(iwad: Path | None, files: list[Path]) -> Track | None:
    with Archives(iwad, files) as arcs:
        if not arcs.items:
            return None
        renames = _music_renames(arcs)

        def renamed(lump: str) -> str:
            short = lump[2:].upper() if lump.upper().startswith("D_") else None
            return f"D_{renames[short]}" if short in renames else lump

        names = []
        if custom := arcs.mapinfo_value(TITLEMUSIC_RE) or arcs.mapinfo_value(TITLEMAP_MUSIC_RE) or _acs_title_music(arcs):
            names.append(custom)
        defaults = [renamed(n) for n in DEFAULT_TITLE_LUMPS]
        base = arcs.items[-1] if iwad and arcs.items[-1].path == iwad else None
        default = next((n for n in defaults if base and base.lump(n)), None)
        names += [default] if default else defaults
        for name in names:
            for a in arcs.items:
                data = a.lump(name, MUSIC_FOLDERS)
                if data and (kind := _classify(data)):
                    if data.startswith(b"MUS\x1a"):
                        data = mus_to_midi(data)
                    return Track(kind, data, Path(name).stem.upper())
        if (data := arcs.guess_music(TITLE_GUESS_RE)) and (kind := _classify(data)):
            return Track(kind, data, "TITLE")
        return None


def _acs_title_music(arcs: Archives) -> str | None:
    """A track that a compiled script for the title map starts itself (Doom Infinite)."""
    for a in arcs.items:
        for n, real in getattr(a, "names", {}).items():
            if n.startswith("acs/") and n.endswith(".o"):
                data = a.read(real)
                if b"TITLEMAP" in data.upper() and (m := ACS_MUSIC_RE.search(data)):
                    return m.group(0).decode("ascii", "replace")
    return None


# ---------- MUS -> MIDI ----------

_MUS_CONTROLLERS = {1: 0, 2: 1, 3: 7, 4: 10, 5: 11, 6: 91, 7: 93, 8: 64, 9: 67}
_MUS_SYSTEM = {10: 120, 11: 123, 12: 126, 13: 127, 14: 121}
MUS_TICKS_PER_QN = 70  # with 500000 us/qn this is MUS's 140 Hz clock


def _varlen(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def mus_to_midi(mus: bytes) -> bytes:
    """Convert DMX MUS to a format-0 Standard MIDI File."""
    score_len, score_start = struct.unpack_from("<HH", mus, 4)
    pos, end = score_start, min(len(mus), score_start + score_len)
    track = bytearray(b"\x00\xff\x51\x03\x07\xa1\x20")  # tempo 500000
    channel_map: dict[int, int] = {}
    volumes = [127] * 16
    delay = 0

    def midi_channel(mus_ch: int) -> int:
        if mus_ch == 15:
            return 9
        if mus_ch not in channel_map:
            used = set(channel_map.values())
            channel_map[mus_ch] = next(c for c in range(16) if c != 9 and c not in used)
        return channel_map[mus_ch]

    def emit(*data: int) -> None:
        nonlocal delay
        track.extend(_varlen(delay))
        track.extend(data)
        delay = 0

    while pos < end:
        desc = mus[pos]
        pos += 1
        kind, ch = (desc >> 4) & 7, midi_channel(desc & 0x0F)
        if kind == 0:  # release
            emit(0x80 | ch, mus[pos] & 0x7F, 0)
            pos += 1
        elif kind == 1:  # play
            note = mus[pos]
            pos += 1
            if note & 0x80:
                volumes[ch] = mus[pos] & 0x7F
                pos += 1
            emit(0x90 | ch, note & 0x7F, volumes[ch])
        elif kind == 2:  # pitch bend, 0..255 centred on 128
            bend = mus[pos] * 64
            pos += 1
            emit(0xE0 | ch, bend & 0x7F, (bend >> 7) & 0x7F)
        elif kind == 3:
            ctrl = mus[pos]
            pos += 1
            if ctrl in _MUS_SYSTEM:
                emit(0xB0 | ch, _MUS_SYSTEM[ctrl], 0)
        elif kind == 4:
            ctrl, value = mus[pos], min(127, mus[pos + 1])
            pos += 2
            if ctrl == 0:
                emit(0xC0 | ch, value)
            elif ctrl in _MUS_CONTROLLERS:
                emit(0xB0 | ch, _MUS_CONTROLLERS[ctrl], value)
        elif kind == 5:  # end of measure
            pass
        elif kind == 6:  # score end
            break
        else:
            pos += 1
        if desc & 0x80:
            ticks = 0
            while pos < end:
                b = mus[pos]
                pos += 1
                ticks = (ticks << 7) | (b & 0x7F)
                if not b & 0x80:
                    break
            delay += ticks
    track.extend(b"\x00\xff\x2f\x00")
    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, MUS_TICKS_PER_QN)
    return header + b"MTrk" + struct.pack(">I", len(track)) + bytes(track)


# ---------- SoundFont + rendering ----------

def _fonts_in(folder: Path | None) -> list[Path]:
    if not folder or not folder.is_dir():
        return []
    return [p for p in folder.iterdir() if p.suffix.lower() in SF_EXTS and p.is_file()]


def find_soundfont(opts: Options, explicit: str | None = None) -> Path | None:
    """Explicit choice first, then our own soundfonts/ folder, then anything shipped beside an engine.

    Within a tier the largest file wins: bigger General MIDI banks are almost always the better-sounding ones.
    """
    explicit = explicit or os.environ.get("DOOMRUNNER_SOUNDFONT")
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    tiers = [_fonts_in(DATA_DIR / "soundfonts") + (_fonts_in(PROJECT_ROOT / "soundfonts") if APP_BUNDLE else [])]
    engine_fonts: list[Path] = []
    for e in opts.engines.values():
        root = e.path.parent
        for folder in (root / "soundfonts", root, e.config_dir / "soundfonts" if e.config_dir else None):
            engine_fonts += _fonts_in(folder)
    tiers.append(engine_fonts)
    for tier in tiers:
        if tier:
            return max(tier, key=lambda p: p.stat().st_size)
    return None


class MidiRenderer:
    """Owns one TinySoundFont synth; only ever used from the music worker thread."""

    def __init__(self, soundfont: Path):
        self.soundfont = soundfont
        self._synth = None

    def _ensure(self):
        if self._synth is None:
            import tinysoundfont

            synth = tinysoundfont.Synth(samplerate=RATE)
            synth.sfload(str(self.soundfont))
            self._synth = synth
        return self._synth

    def render(self, midi: bytes, cancel: threading.Event) -> tuple[bytes, float, float] | None:
        """Float32 stereo PCM plus its peak and RMS. The synth's float output isn't clipped, so the
        caller can normalize with channel volume (SDL scales before it clamps)."""
        from tinysoundfont import Sequencer, midi as tsf_midi

        synth = self._ensure()
        synth.sounds_off()
        for ch in range(16):
            synth.control_change(ch, 121, 0)  # reset controllers left over from the previous song
            synth.pitchbend(ch, 8192)
            try:
                synth.program_change(ch, 0, ch == 9)
            except Exception:
                pass
        seq = Sequencer(synth)
        seq.add(tsf_midi.load_memory(midi))
        out = bytearray()
        chunk = RATE // 2
        tail = 0.0
        cut = True
        while len(out) < MAX_SECONDS * RATE * 8:
            if cancel.is_set():
                return None
            out += synth.generate(chunk)
            if seq.is_empty():
                tail += chunk / RATE
                if tail >= TAIL_SECONDS:
                    cut = False
                    break
        samples = array("f", out)
        if cut:
            fade = min(len(samples), int(CUT_FADE_SECONDS * RATE) * 2)
            start = len(samples) - fade
            for i in range(fade):
                samples[start + i] *= 1.0 - i / fade
            out = samples.tobytes()
        peak = max(max(samples, default=0.0), -min(samples, default=0.0))
        rms = math.sqrt(sum(x * x for x in samples) / len(samples)) if samples else 0.0
        return bytes(out), peak, rms


# ---------- playback ----------

@dataclass
class Prepared:
    kind: str  # "pcm" (rendered float32 stereo) | "stream" (encoded file for mixer.music)
    data: bytes
    volume: float
    sig: str = ""  # identifies the track itself, so presets sharing one can keep it playing


def midi_volume(peak: float, rms: float) -> float:
    """Channel volume that brings a rendered track to MIDI_LOUDNESS_DB without its peak passing PEAK_TARGET."""
    if peak <= 0 or rms <= 0:
        return VOLUME
    return min(1.0, 10 ** (MIDI_LOUDNESS_DB / 20) / rms, PEAK_TARGET / peak)


def _prepare(
    iwad: Path | None, files: list[Path], renderer: MidiRenderer | None, cancel: threading.Event, ready: dict[str, Prepared]
) -> Prepared | None:
    track = find_title_music(iwad, files)
    if track is None or cancel.is_set():
        return None
    sig = hashlib.sha1(track.data).hexdigest()
    if sig in ready:
        return ready[sig]  # another preset's copy of the same track, already rendered
    if track.kind == "midi":
        if renderer is None:
            return None
        result = renderer.render(track.data, cancel)
        if not result:
            return None
        pcm, peak, rms = result
        return Prepared("pcm", pcm, midi_volume(peak, rms), sig)
    return Prepared("stream", track.data, VOLUME, sig)


class MusicPlayer:
    """One preset's title track at a time, crossfading on change.

    Moving to a preset that uses the same track (the stock title music, say) keeps it playing instead of starting
    it over; the current track keeps going until the next preset's track is known.
    Rendered MIDI alternates between two channels so the old track fades out under the new one.
    Streamed formats share SDL_mixer's single music slot, so a new stream waits for the old one's
    fade-out to finish instead of cutting it.
    """

    def __init__(self, soundfont: Path | None, channels: tuple[pygame.mixer.Channel, pygame.mixer.Channel]):
        self.renderer = MidiRenderer(soundfont) if soundfont and importlib.util.find_spec("tinysoundfont") else None
        self.channels = channels
        self.active = 0  # index of the channel the current PCM track is on
        self.sounds: list[pygame.mixer.Sound | None] = [None, None]
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="music")
        self.want: object = None
        self.job: tuple[object, tuple, Future, threading.Event] | None = None
        self.pending: tuple[object, Prepared] | None = None
        self.cache: OrderedDict[str, Prepared] = OrderedDict()  # by track sig
        self.tracks: dict[tuple, str | None] = {}  # (iwad, files) -> track sig, None when it has no title music
        self.playing: str | None = None  # sig of the track currently audible (not fading out)
        self.streaming = False

    def request(self, key: object, iwad: Path | None = None, files: list[Path] | None = None) -> None:
        """Ask for `key`'s track; None stops. Cheap to call every frame."""
        if key == self.want:
            return
        self.want = key
        self._cancel()
        if key is None:
            self.stop()
            return
        ident = (iwad, tuple(files or ()))
        if ident in self.tracks:
            sig = self.tracks[ident]
            if sig is not None and sig == self.playing and self._audible():
                return  # same track: let it play on
            self.stop()
            if sig in self.cache:
                self.cache.move_to_end(sig)
                self.pending = (key, self.cache[sig])
                return
            if sig is None:
                return
        cancel = threading.Event()
        future = self.pool.submit(_prepare, iwad, list(files or ()), self.renderer, cancel, dict(self.cache))
        self.job = (key, ident, future, cancel)

    def _cancel(self) -> None:
        if self.job:
            self.job[3].set()
            self.job = None
        self.pending = None

    def _audible(self) -> bool:
        if self.streaming:
            return pygame.mixer.music.get_busy()
        return self.channels[self.active].get_busy()

    def stop(self, fade_ms: int = FADE_OUT_MS) -> None:
        self._cancel()
        self.playing = None
        self.channels[self.active].fadeout(fade_ms)
        if self.streaming:
            pygame.mixer.music.fadeout(fade_ms)
            self.streaming = False

    def update(self) -> None:
        if self.job and self.job[2].done():
            key, ident, future, _ = self.job
            self.job = None
            try:
                prepared = future.result()
            except Exception:
                prepared = None
            self.tracks[ident] = prepared.sig if prepared else None
            if prepared is not None:
                self.cache[prepared.sig] = prepared
                self.cache.move_to_end(prepared.sig)
                while len(self.cache) > 1 and sum(len(p.data) for p in self.cache.values()) > CACHE_BYTES:
                    self.cache.popitem(last=False)
            if key == self.want and not (prepared and prepared.sig == self.playing and self._audible()):
                self.stop()
                if prepared is not None:
                    self.pending = (key, prepared)
        if self.pending:
            self._start()

    def _start(self) -> None:
        key, prepared = self.pending
        if key != self.want:
            self.pending = None
            return
        try:
            if prepared.kind == "stream":
                if pygame.mixer.music.get_busy():
                    return  # previous stream still fading; try again next frame
                pygame.mixer.music.load(io.BytesIO(prepared.data))
                pygame.mixer.music.set_volume(prepared.volume)
                pygame.mixer.music.play(fade_ms=FADE_IN_MS)
                self.streaming = True
            else:
                self.active ^= 1
                snd = pygame.mixer.Sound(buffer=prepared.data)
                snd.set_volume(prepared.volume)
                self.sounds[self.active] = snd
                self.channels[self.active].play(snd, fade_ms=FADE_IN_MS)
            self.playing = prepared.sig
        except pygame.error:
            pass
        self.pending = None

    def shutdown(self) -> None:
        self.stop(0)
        self.pool.shutdown(wait=False, cancel_futures=True)
