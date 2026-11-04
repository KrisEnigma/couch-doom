"""Fullscreen couch UI."""
from __future__ import annotations

import ctypes
import io
import math
import os
import sys
import threading
import time
import webbrowser
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Callable

import pygame

from . import __version__, canvas, draw, easter_eggs
from . import update as updates
from . import self_update
from . import whats_new
from . import config
from .config import ASSET_DIR
from . import handover, asset_cache
from .background import lower_current_thread_priority
from .filebrowser import Browser as FileBrowser
from .gamepad import Action, Input, keyboard_repeat_timing
from .glyphs import BUTTON_NAMES, Glyphs
from .i18n import LANGUAGES, current_language, set_language
from .i18n import t as tr  # not `t`: draw helpers bind local `t` to ease floats
from .launch import LaunchCommand, build_command, load_order, load_rows, presented_files, split_args
from . import log
from .log import closed_early, last_line, needs_extract_retry, spawn
from .launchers import Launchers
from .music import DWELL_SECONDS, MusicPlayer, find_engine_soundfont, find_soundfont
from .options import Options, OptionsError, Preset, unpack
from .endoom import COLS, ROWS, Endoom, find_endoom
from .readme import Readme, beside_stamp, find_readme
from .sfx import Sfx
from .sources import SOURCES, Choice
from .state import State
from .theme import HOUSE, PALETTES, Theme, from_art, theme_for_palette
from .titleart import Art, find_logo, find_startup, find_title_art

TEXT = (240, 232, 218)
MUTED = (164, 150, 134)
DIM = (104, 93, 84)
ERROR = (255, 110, 90)
PANEL = (18, 14, 13)
KEY_IDLE = (48, 39, 35)

OSK_ROWS = [
    list("1234567890"),
    list("QWERTYUIOP"),
    list("ASDFGHJKL'"),
    list("ZXCVBNM-:!"),
    ["SPACE", "DELETE", "CLEAR", "DONE"],
]
OSK_LABELS = {"SPACE": "osk.space", "DELETE": "hint.delete", "CLEAR": "osk.clear", "DONE": "hint.done"}

QUIT_CONFIRM_SECONDS = 2.0
LAUNCH_WIPE_SECONDS = 0.6
LAUNCH_ART_WAIT_SECONDS = 1.2  # a cold unpack or a slow drive: open on the plain backdrop instead of waiting
HANDOVER_TIMEOUT_SECONDS = handover.DEFAULT_TIMEOUT
HANDOVER_GRACE_SECONDS = 4 / 60  # cover the engine's first paint; the frame count follows the display
WINDOW_RETRIES = 20  # half a second apart
INPUT_COOLDOWN = 0.45
FALLBACK_FPS = 60  # used only when the display will not report a refresh rate
HIDDEN_FPS = 10
WINDOW_EVENTS = {
    pygame.QUIT, pygame.WINDOWCLOSE, pygame.WINDOWMINIMIZED, pygame.WINDOWHIDDEN, pygame.WINDOWRESTORED,
    pygame.WINDOWSHOWN, pygame.WINDOWEXPOSED, pygame.WINDOWDISPLAYCHANGED, pygame.RENDER_DEVICE_RESET,
}
ART_FADE_SECONDS = 0.3
ART_CACHE_SIZE = 24
ART_CACHE_BYTES = 96 * 1024 * 1024  # 24 panels at 1080p, but only ~8 at 4K
# Each theme holds a full-screen background plus an art-panel veil (~11 MB at 1080p, ~45 MB at 4K).
# Only the live and fading themes need to stay warm; rebuilding one takes a few milliseconds.
THEME_CACHE_SIZE = 6
ART_MIN_FILL = 0.62  # of the art panel's height
ART_MAX_ZOOM = 1.25
FAVORITES_ID = "favorites"
RECENT_ID = "recent"
INFO_TAB_COUNT = 2
ENDOOM_TAB = 1
HELP_SECTION_COUNT = 9
ISSUE_URL = "https://github.com/KrisEnigma/couch-doom/issues"
UPDATE_DELAY_SECONDS = 1.0  # let the list settle briefly before a notice appears over it
UPDATE_VERIFY_HOLD_SECONDS = 0.4


def info_tabs() -> tuple[str, str]:
    return (tr("info.readme"), tr("info.endoom"))


def help_sections() -> list[tuple[str, str]]:
    facts = _help_facts()
    return [(tr(f"help.{i}.title"), tr(f"help.{i}.body", **facts)) for i in range(HELP_SECTION_COUNT)]


@lru_cache(maxsize=1)
def _help_facts() -> dict[str, str]:
    return {"version": __version__, "log": log.display_path()}


def update_choices(info: dict | None, packaged: bool) -> tuple[tuple[str, str, str], ...]:
    # "later" stays index 1 among the base trio because B and a click outside both mean it;
    # insert install at 0 when available so later shifts with the list.
    choices = [
        ("open", tr("update.open"), tr("update.open_cap")),
        ("later", tr("update.later"), tr("update.later_cap")),
        ("skip", tr("update.skip"), tr("update.skip_cap")),
    ]
    if info and info.get("asset") and packaged:
        choices.insert(0, ("install", tr("update.install"), tr("update.install_cap")))
    return tuple(choices)
LOGO_MAX_H = 168  # design px; menu logos are compact, so they need more height than a text title to read as big
INFO_SLIDE_SECONDS = 0.22
INFO_STICK_LINES_PER_SEC = 48
MUSIC_CHANNELS, MOVE_CHANNEL = (0, 1), 2
MOUSE_EVENTS = {pygame.MOUSEMOTION, pygame.MOUSEWHEEL, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP}
FONTS = ASSET_DIR / "fonts"
PROGRAM = ".exe" if os.name == "nt" else "program"


@dataclass
class Row:
    kind: str  # "header" | "preset"
    text: str
    preset: int = -1
    count: int = 0
    fav: bool = False  # the copy shown in the Favorites section
    collapsed: bool = False
    group_id: str | None = None  # stable collapse key for Favorites / Recently Played


def _header_key(row: Row) -> str:
    return row.group_id or row.text


@dataclass
class Toast:
    text: str
    color: tuple[int, int, int]
    born: float
    ttl: float = 3.2


@dataclass
class Hit:
    """A clickable area, recorded while drawing so clicks use exactly what's on screen."""
    rect: pygame.Rect
    click: Callable[[], None]
    hover: Callable[[], None] | None = None


def _lerp(a: float, b: float, k: float) -> float:
    return a + (b - a) * k


def _approach(current: float, target: float, rate: float, dt: float) -> float:
    """Close `rate` of the remaining gap per second.

    A faster display adds frames. It does not shorten the motion: each frame covers a slice of `dt`.
    """
    return _lerp(current, target, min(1.0, dt * rate))


@lru_cache(maxsize=1)
def _core_graphics():
    cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    cg.CGMainDisplayID.restype = ctypes.c_uint32
    cg.CGDisplayCopyDisplayMode.restype = ctypes.c_void_p
    cg.CGDisplayCopyDisplayMode.argtypes = [ctypes.c_uint32]
    cg.CGDisplayModeGetRefreshRate.restype = ctypes.c_double
    cg.CGDisplayModeGetRefreshRate.argtypes = [ctypes.c_void_p]
    cg.CGDisplayModeRelease.argtypes = [ctypes.c_void_p]
    return cg


def _macos_refresh_rate() -> int:
    """Core Graphics' refresh rate for the main display, 0 when unknown.

    pygame.display only knows windows made by display.set_mode. The Mac build uses pygame.Window, which makes
    that call raise "No open window", so the loop fell back to 60 on a 120 Hz ProMotion panel.
    """
    try:
        cg = _core_graphics()
        mode = cg.CGDisplayCopyDisplayMode(cg.CGMainDisplayID())
        if not mode:
            return 0
        try:
            return round(cg.CGDisplayModeGetRefreshRate(mode))
        finally:
            cg.CGDisplayModeRelease(mode)
    except (OSError, AttributeError):
        return 0


def display_refresh_rate() -> int:
    """Hz of the display the window is on. 60 when nothing can say, so the loop still has a cap."""
    rate = 0
    try:
        rate = pygame.display.get_current_refresh_rate()
    except pygame.error:
        pass  # the Mac build's pygame.Window: see _macos_refresh_rate
    if rate <= 0 and sys.platform == "darwin":
        rate = _macos_refresh_rate()
    return rate if rate > 0 else FALLBACK_FPS


def use_gpu() -> bool:
    """Draw through the GPU canvas. On by default on macOS, where it is tested; COUCHDOOM_RENDERER=software or
    =gpu overrides it. Windows and Linux open their window with display.set_mode, which has no canvas yet."""
    choice = os.environ.get("COUCHDOOM_RENDERER", "").lower()
    if choice in ("gpu", "software"):
        return choice == "gpu"
    return sys.platform == "darwin"


def show_fps() -> bool:
    """Dev overlay. A release stays clean unless the process was started with COUCHDOOM_SHOW_FPS=1."""
    return os.environ.get("COUCHDOOM_SHOW_FPS") == "1"


def _mb(size: int) -> str:
    return f"{size / (1024 * 1024):.1f}".replace(".", tr("update.decimal"))


def _theme_cache(cache: OrderedDict, key: int, create: Callable):
    if key in cache:
        cache.move_to_end(key)
        return cache[key]
    return _theme_cache_put(cache, key, create())


def _theme_cache_put(cache: OrderedDict, key: int, value):
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > THEME_CACHE_SIZE:
        cache.popitem(last=False)
    return value


def _surface_bytes(surface) -> int:
    if not isinstance(surface, pygame.Surface):
        return 0
    w, h = surface.get_size()
    return w * h * surface.get_bytesize()


def _ease_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _ease_out_expo(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 if t >= 1 else (1 - 2 ** (-10 * t)) / (1 - 2 ** -10)


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _pretty_args(text: str) -> str:
    """Show path arguments by file name only; full paths don't fit and aren't what you scan for."""
    out = []
    for token in split_args(text):
        out.append(Path(token).name if ("/" in token or "\\" in token) else token)
    return " ".join(out)


def _reset_alpha(surf: pygame.Surface) -> None:
    """Undo a fade's set_alpha. An opaque surface left at alpha 255 keeps taking SDL's blended blit path,
    several times slower at full screen; a per-pixel-alpha surface set to None would lose its alpha channel."""
    surf.set_alpha(255 if surf.get_masks()[3] else None)


def _entry_card(preset: Preset, iwad: Path | None, row: list[Path]) -> tuple[Art | None, Readme | None, Art | None] | None:
    """Art, readme and logo when this one launcher entry has a face of its own.

    A title picture, a logo or a readme counts. The base game's picture does not, so a gameplay
    mod with none of the three leaves the entry above it on the card.
    """
    archives = [path for path in row if path.suffix.lower() != ".dmb"]
    art = logo = readme = None
    try:
        if archives:
            art = find_title_art(iwad, archives)
    except Exception:
        art = None
    try:
        if archives:
            logo = find_logo(iwad, archives)
    except Exception:
        logo = None
    try:
        # The readme walk takes maps and mods off the preset. This entry's files are the whole list.
        readme = find_readme(replace(preset, mods=list(row), mappacks=[], load_maps_after_mods=False))
    except Exception:
        readme = None
    if logo is None and readme is None and (art is None or art.fallback):
        return None
    if archives and (logo is None or art is None or art.fallback):
        try:
            if startup := find_startup(archives):
                art = startup
        except Exception:
            pass
    return art, readme, logo


def _card(preset: Preset, iwad: Path | None, shown: list[Path], files: list[Path]) -> tuple[Art | None, Readme | None, Art | None]:
    """The card's art, readme and logo.

    The first loaded entry that brings its own face supplies all three. A logo or a readme on an
    entry lower in the list used to paint over the map above it, because art follows the engine's
    last-loaded lump and the readme follows the first file that has one.
    """
    for row in load_rows(preset):
        if (card := _entry_card(preset, iwad, row)) is not None:
            return card
    try:
        art = find_title_art(iwad, shown)
    except Exception:
        art = None
    try:
        logo = find_logo(iwad, files)  # an add-on IWAD is the base game's logo, not a mod's
    except Exception:
        logo = None
    if shown and (logo is None or art is None or art.fallback):
        try:
            if startup := find_startup(shown):
                art = startup
        except Exception:
            pass
    try:
        readme = find_readme(preset)
    except Exception:
        readme = None
    return art, readme, logo


def _load_extras(preset: Preset) -> tuple[Art | None, Readme | None, Endoom | None, Art | None]:
    unpack(preset)
    files = load_order(preset)
    iwad, shown = presented_files(preset)
    try:
        key = asset_cache.key_for(preset, iwad, files)
        if cached := asset_cache.get(key):
            # The key ignores a text file beside the wad. A stamp of those files lets an edit refresh the
            # readme and leave the title art cached. No stamp at all is an older entry: re-read when a text
            # file is there, and only record the stamp when there is nothing beside the wad to contradict it.
            try:
                stamp = beside_stamp(preset)
            except Exception:
                stamp = cached.readme_stamp
            if cached.readme_stamp != stamp:
                if cached.readme_stamp is None and stamp == "":
                    cached.readme_stamp = ""
                else:
                    try:
                        cached.readme = _card(preset, iwad, shown, files)[1]
                    except Exception:
                        stamp = cached.readme_stamp
                    cached.readme_stamp = stamp
                try:
                    asset_cache.put(key, cached)
                except Exception:
                    pass
            return cached.art, cached.readme, cached.endoom, cached.logo
    except Exception:
        key = None
    art, readme, logo = _card(preset, iwad, shown, files)
    try:
        endoom = find_endoom(files)
    except Exception:
        endoom = None
    try:
        if key:
            try:
                stamp = beside_stamp(preset)
            except Exception:
                stamp = None
            asset_cache.put(key, asset_cache.CachedAssets(art, readme, endoom, logo, stamp))
    except Exception:
        pass
    return art, readme, endoom, logo


def _dark_backed(img: pygame.Surface) -> bool:
    """An opaque logo on a near-black card (Brutal Wolfenstein's), which the engine draws additively."""
    w, h = img.get_size()
    corners = [img.get_at((x, y)) for x in (0, w - 1) for y in (0, h - 1)]
    return all(c.a == 255 and max(c.r, c.g, c.b) < 40 for c in corners)


_DARK_KEY = bytes(min(255, max(0, (v - 20) * 255 // 20)) for v in range(256))  # 20 and below vanish, 40 is solid


def _key_out_dark(img: pygame.Surface) -> pygame.Surface:
    """Brightness becomes opacity, so the card's dark backing disappears and the lettering stays."""
    rgba = bytearray(pygame.image.tobytes(img, "RGBA"))
    gray = pygame.image.tobytes(pygame.transform.grayscale(img), "RGBA")[0::4]
    rgba[3::4] = gray.translate(_DARK_KEY)
    return pygame.image.frombytes(bytes(rgba), img.get_size(), "RGBA").convert_alpha()


def _set_window_icon(window=None) -> None:
    """Finder and Explorer use the bundle or exe icon. The Dock and taskbar use the window's own, which
    pygame leaves as its logo. pygame.Window applies that logo again at the end of construction, so an
    icon set before the window exists does not stick on macOS. Windows also groups taskbar buttons by
    app ID, which would otherwise be python's."""
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("com.krisenigma.couchdoom")
        except (AttributeError, OSError):
            pass
    try:
        icon = pygame.image.load(str(ASSET_DIR / "icon.png"))
        pygame.display.set_icon(icon)
        if window is not None:
            window.set_icon(icon)
    except (pygame.error, FileNotFoundError, AttributeError):
        pass


def _is_rule(line: str) -> bool:
    """A separator drawn with one or two punctuation characters: -----, =====, -=-=-=, *~*~*."""
    ink = line.strip()
    return len(ink) >= 4 and len(set(ink)) <= 2 and not any(c.isalnum() or c.isspace() for c in ink)


def _wrap_mono(text: str, per_line: int) -> list[str]:
    """Hard-wrap preformatted text, breaking at a space when one is reasonably close."""
    out: list[str] = []
    for raw in text.split("\n"):
        raw = raw.rstrip()
        if _is_rule(raw):
            raw = raw[:per_line]  # a wrapped ----- or ===== reads as two separators
        while len(raw) > per_line:
            cut = raw.rfind(" ", 0, per_line + 1)
            if cut < per_line // 2:
                cut = per_line
            out.append(raw[:cut].rstrip())
            raw = raw[cut:].lstrip()
        out.append(raw)
    return out


def _set_dpi_aware() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _force_foreground() -> None:
    """Bring the launcher in front of the terminal (or the game that just exited)."""
    if sys.platform == "win32":
        # Windows blocks background processes from stealing focus; a synthetic Alt press lifts that lock.
        try:
            hwnd = pygame.display.get_wm_info().get("window")
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            VK_MENU, KEYUP = 0x12, 0x0002
            user32.keybd_event(VK_MENU, 0, 0, 0)
            user32.SetForegroundWindow(hwnd)
            user32.keybd_event(VK_MENU, 0, KEYUP, 0)
        except (AttributeError, OSError, pygame.error):
            pass
        return
    if sys.platform == "darwin":
        _force_foreground_macos()


def _appkit():
    """(objc, send, NSApp) through ctypes, or None; pygame exposes no AppKit handles of its own."""
    import ctypes.util

    lib = ctypes.util.find_library("objc")
    if not lib:
        return None
    objc = ctypes.cdll.LoadLibrary(lib)
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]

    def send(obj: int, sel: bytes, *args, restype=ctypes.c_void_p, argtypes=()):
        fn = objc.objc_msgSend
        fn.restype = restype
        fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
        return fn(obj, objc.sel_registerName(sel), *args)

    NSApp = send(objc.objc_getClass(b"NSApplication"), b"sharedApplication")
    return (objc, send, NSApp) if NSApp else None


def _disable_macos_fullscreen_shadow() -> None:
    """Avoid Tahoe's visible one-pixel fullscreen edge from the SDL Cocoa window shadow."""
    try:
        kit = _appkit()
        if not kit:
            return
        _, send, app = kit
        windows = send(app, b"windows")
        count = send(windows, b"count", restype=ctypes.c_ulong)
        for index in range(count):
            window = send(windows, b"objectAtIndex:", ctypes.c_ulong(index), argtypes=[ctypes.c_ulong])
            title = send(window, b"title")
            if title and send(title, b"UTF8String", restype=ctypes.c_char_p) == b"CouchDoom":
                send(window, b"setHasShadow:", False, restype=None, argtypes=[ctypes.c_bool])
                return
    except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError, pygame.error):
        pass


def _macos_window_levels(levels: list[int] | None = None) -> list[int]:
    """Drop this app's windows to the normal level (the fullscreen one sits above dialogs), or restore `levels`.
    Returns the levels they had."""
    try:
        kit = _appkit()
        if not kit:
            return []
        _, send, NSApp = kit
        windows = send(NSApp, b"windows")
        previous = []
        for i in range(send(windows, b"count", restype=ctypes.c_ulong)):
            win = send(windows, b"objectAtIndex:", ctypes.c_ulong(i), argtypes=[ctypes.c_ulong])
            previous.append(send(win, b"level", restype=ctypes.c_long))
            level = levels[i] if levels and i < len(levels) else 0
            send(win, b"setLevel:", ctypes.c_long(level), restype=None, argtypes=[ctypes.c_long])
        return previous
    except (AttributeError, OSError, TypeError, ValueError):
        return []


def _force_foreground_macos() -> None:
    """Activate via AppKit. macOS 14+ may ignore this without a prior user gesture (cooperative activation)."""
    try:
        kit = _appkit()
        if not kit:
            return
        objc, send, NSApp = kit
        # Regular policy so a bare python process can become the active app.
        send(NSApp, b"setActivationPolicy:", ctypes.c_long(0), restype=ctypes.c_long, argtypes=[ctypes.c_long])
        send(NSApp, b"activateIgnoringOtherApps:", True, restype=None, argtypes=[ctypes.c_bool])
        # Fallback used by newer AppKit; NSApplicationActivateIgnoringOtherApps = 1 << 1.
        running = send(objc.objc_getClass(b"NSRunningApplication"), b"currentApplication")
        if running:
            send(running, b"activateWithOptions:", ctypes.c_ulong(2), restype=ctypes.c_bool, argtypes=[ctypes.c_ulong])
    except (AttributeError, OSError, TypeError, ValueError):
        pass


# convert() takes the window's format, which is RGBA on macOS: fresh surfaces start at alpha 0 and
# vanish when blitted. Opaque layers convert to this no-alpha format instead, as they get on Windows/Linux.
_OPAQUE = pygame.Surface((1, 1), 0, 32, (0xFF0000, 0xFF00, 0xFF, 0))


class App:
    screen = None  # set per window; the defaults let window code run before (or without) one
    refresh_hz = FALLBACK_FPS

    def __init__(
        self,
        opts: Options,
        state: State,
        windowed: bool = False,
        soundfont: str | None = None,
        problem: OptionsError | None = None,
        reload: Callable[[], Options] | None = None,
        launchers: Launchers | None = None,
        pick: bool = False,
    ):
        self.opts = opts
        self.state = state
        set_language(state.language)
        self.windowed = windowed
        self.problem = problem  # options.json missing/unreadable: the notice screen replaces the list
        self.launchers = launchers
        self.reload = reload or (launchers.load if launchers else None)
        self.picker: list[Choice | None] = []  # None is the "find it myself" row
        self.picker_sel = 0
        self.picker_opened = 0.0
        self.file_browser: FileBrowser | None = None
        self.browser_scroll = 0
        # A newer release, shown once as a notice: {"version", "current", "notes": [str], "url"}.
        self.update: dict | None = None
        self.update_sel = 1
        self.update_opened = 0.0
        self.update_choice: str | None = None
        self.update_job: Future | None = None
        self.update_pool: ThreadPoolExecutor | None = None
        self.update_started = 0.0
        self.update_install_job: Future | None = None
        self.update_cancel: threading.Event | None = None
        self.update_progress: tuple[str, int, int | None] = ("checking", 0, None)  # see self_update.PHASES
        self.update_error: str | None = None
        self.update_handoff = False  # quitting so the apply helper can swap; skip interpreter shutdown
        # After an update, the notes for every release since the last one that ran: {"version", "previous", "sections"}.
        self.whats_new = whats_new.pending(state.seen_version, state.returning, __version__)
        self.whats_new_opened = 0.0
        if state.seen_version != __version__:
            state.set_seen_version(__version__)
        self.soundfont_choice = soundfont
        self._engine_soundfonts: dict[tuple, Path | None] = {}

        # Check while the window, assets, and music are being initialized so a ready notice can appear promptly.
        self._start_update_check(time.monotonic())

        _set_dpi_aware()
        if not windowed:
            os.environ.setdefault("SDL_VIDEO_WINDOW_POS", "0,0")
            # Stay on the current Space, like GZDoom's default fullscreen, so launching a game doesn't swipe between Spaces.
            os.environ.setdefault("SDL_VIDEO_MAC_FULLSCREEN_SPACES", "0")
        pygame.mixer.pre_init(44100, 32, 2, 1024)
        pygame.init()
        pygame.key.set_repeat(*keyboard_repeat_timing())
        pygame.display.set_caption("CouchDoom")
        self.input = Input()

        self.soundfont = find_soundfont(soundfont)
        self.music: MusicPlayer | None = None
        self.sfx: Sfx | None = None
        self._music_sel: int | None = None
        self._music_since = 0.0
        self._audio_up()

        self.commands: list[LaunchCommand] = [build_command(opts, p) for p in opts.presets]
        self.filter = ""
        self.mode = "list"  # "list" | "menu" | "search" | "info" | "help" | "launcher" | "browse" | "update"
        self.menu_sel = 0
        self.menu_opened = 0.0
        self.menu_status = ""
        self.menu_status_at = 0.0
        self.quit_at: float | None = None
        self.help_scroll = 0.0
        self.help_view = 0.0
        self.info_tab = 0
        self.info_scrolls = [0.0] * INFO_TAB_COUNT  # per-tab position, kept while the sheet is open
        self.info_scroll = 0.0
        self.info_view = 0.0
        self.info_opened = 0.0
        self.info_lines: tuple[tuple, list[str]] = ((), [])
        self.osk = [0, 0]
        self.osk_moved = 0.0
        self.toast: Toast | None = None
        self.quit_armed_until = 0.0
        self.ignore_until = 0.0
        self.hits: list[Hit] = []
        self.mouse_on = False
        self.mouse_travel = 0
        self.free_scroll: float | None = None  # set by the wheel; pad/keyboard moves hand scrolling back to the selection
        self.scrollbars: dict[str, tuple[pygame.Rect, int, float]] = {}  # kind -> (track on screen, thumb height, max scroll)
        self.drag: tuple[str, int] | None = None  # scrollbar being dragged, and where on the thumb it was grabbed
        self.mouse_pos = (0, 0)
        self.running = True
        self.hidden = False  # minimized or hidden: the loop ticks slowly and skips drawing
        self.dt = 1 / FALLBACK_FPS  # last frame's duration; draws before the first tick still move at this pace
        self._fps_clock: pygame.time.Clock | None = None  # set in run() when the dev overlay is on
        self._fps_hz = 0
        self.row_offset: dict[tuple[bool, int], float] = {}

        self.art_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="titleart")
        self.art_jobs: dict[int, Future] = {}
        self.art_render_jobs: dict[int, Future] = {}
        self.logo_render_jobs: dict[int, Future] = {}
        self.art_cache: OrderedDict[int, pygame.Surface | None] = OrderedDict()
        self.art_layers: list[tuple[int, pygame.Surface | None, float]] = []
        self.readmes: dict[int, Readme | None] = {}
        self.endooms: dict[int, Endoom | None] = {}
        self.logos: dict[int, pygame.Surface | None] = {}
        self.endoom_cache: dict[tuple, pygame.Surface] = {}
        self.themes: dict[int, Theme] = {}
        self.theme = HOUSE
        self.theme_from: Theme | None = None  # set while the previous theme fades out
        self.theme_born = 0.0
        self.theme_t = 1.0
        self._theme_bgs: OrderedDict[int, pygame.Surface] = OrderedDict()
        self._theme_bars: OrderedDict[int, pygame.Surface] = OrderedDict()
        self._theme_layers: OrderedDict[int, dict] = OrderedDict()
        self._footer_band: pygame.Surface | None = None
        self._detail_panel: tuple[tuple, tuple, pygame.Surface] | None = None
        self._warm_generation = 0  # bumped per cache-warming pass; older workers stop when it moves on
        self._warm_allowed = threading.Event()  # cleared while a game runs
        self._warm_allowed.set()

        self.rows: list[Row] = []
        self.collapsed_sections: set[str] = set()
        self.current = 0
        self.cur_row = -1  # a preset can appear twice (Favorites + its section); this says which copy
        self._pick_start()
        self._rebuild_rows()

        self._open_window()
        self.scroll = self._target_scroll()
        self.bar_y = self.row_y[self._sel_row()] if self.rows else 0
        self.thumb_scroll, self.thumb_moved = self.scroll, -math.inf
        self._loading_cache: tuple | None = None
        self.detail_changed = time.monotonic()
        self._warm_cache()
        self._report_update_result()
        if pick:
            self._open_picker()

    def _pick_start(self) -> None:
        names = {p.name: i for i, p in enumerate(self.opts.presets)}
        favs = [f for f in self.state.favorites if f in names]
        # Favorites lead the list, so start there; the last-played one if it is a favorite.
        start = self.state.last_played if self.state.last_played in favs or not favs else favs[0]
        self.current = names.get(start, 0)

    @property
    def blocked(self) -> bool:
        """Nothing to pick from: the notice screen stands in for the list and details."""
        return self.problem is not None or not self.opts.presets

    def _reload(self) -> None:
        if not self.reload:
            return
        try:
            opts = self.reload()
        except OptionsError as exc:
            self.problem = exc
            if self.launchers and self.launchers.must_pick:
                self._open_picker()  # the second look found several: the player has to say which
                return
            self._sound("error")
            self._notify(tr("toast.still_same", detail=f"{exc.title[0].lower()}{exc.title[1:]}"), ERROR)
            return
        in_menu = self.mode == "menu"
        self._apply(opts, announce=not in_menu)
        if in_menu:
            self.menu_status = tr("menu.refreshed")
            self.menu_status_at = time.monotonic()

    def _apply(self, opts: Options, *, announce: bool = True) -> None:
        """Show a freshly loaded set of presets: a reload, or another launcher picked."""
        for job in self.art_jobs.values():
            job.cancel()
        for job in self.art_render_jobs.values():
            job.cancel()
        for job in self.logo_render_jobs.values():
            job.cancel()
        for cache in (self.art_jobs, self.art_render_jobs, self.logo_render_jobs, self.art_cache, self.readmes, self.endooms, self.logos, self.themes, self.row_offset):
            cache.clear()
        self.art_layers.clear()
        self.opts, self.problem = opts, None
        self.commands = [build_command(opts, p) for p in opts.presets]
        self._audio_down()  # sounds and SoundFont come from the engines and IWADs in the new settings
        self._engine_soundfonts.clear()
        self.soundfont = find_soundfont(self.soundfont_choice)
        self._audio_up()
        self.filter = ""
        self._pick_start()
        self._rebuild_rows()
        self.scroll = self._target_scroll()
        self.bar_y = self.row_y[self._sel_row()] if self.rows else 0
        self.detail_changed = time.monotonic()
        self._warm_cache()
        if opts.presets:
            self._sound("open")
            if announce:
                source = f" from {opts.launcher}" if opts.launcher else ""
                self._notify(tr("toast.loaded", count=len(opts.presets), source=source), MUTED)
        else:
            self._sound("error")

    # ---------- launcher picker ----------

    def _open_picker(self) -> None:
        if not self.launchers:
            return
        # Startup already discovered these choices. Re-scanning and loading every settings file here made F4 stall.
        choices = self.launchers.choices
        self.picker = [*choices, None]
        current = self.launchers.current
        self.picker_sel = next((i for i, c in enumerate(choices) if current and c.id == current.id), 0)
        self.picker_opened = time.monotonic()
        self.mode = "launcher"
        self._sound("open")

    def _on_picker_action(self, action: Action, *, repeat: bool = False) -> None:
        if action in (Action.UP, Action.DOWN):
            step = -1 if action == Action.UP else 1
            target = self.picker_sel + step
            sel = max(0, min(len(self.picker) - 1, target)) if repeat else target % len(self.picker)
            if sel != self.picker_sel:
                self.picker_sel = sel
                self._sound("move")
        elif action == Action.CONFIRM:
            self._picker_pick(self.picker_sel)
        elif action == Action.BACK:
            self._close_overlay()

    def _picker_hover(self, i: int) -> None:
        if i != self.picker_sel:
            self.picker_sel = i
            self._sound("move")

    def _picker_pick(self, i: int) -> None:
        self.picker_sel = i
        choice = self.picker[i]
        if choice is None:
            self._open_browser()
            return
        current = self.launchers.current
        if current and choice.id == current.id and not self.problem:
            self._close_overlay()
            return
        self._choose(choice)

    # ---------- what's new after an update ----------

    def _poll_whats_new(self, now: float) -> None:
        """Open once the list is showing, so the launcher picker or a problem screen comes first."""
        if not self.whats_new or self.mode != "list":
            return
        if self.blocked or now < self.ignore_until:
            return
        self.whats_new_opened = now
        self.mode = "whatsnew"
        self._sound("open")

    def _close_whats_new(self) -> None:
        self.whats_new = None
        self._close_overlay()

    # ---------- update notice ----------

    def _open_update(self, info: dict) -> None:
        self.update = info
        choices = update_choices(info, bool(getattr(sys, "frozen", False)))
        self.update_sel = next(i for i, item in enumerate(choices) if item[0] == "later")
        self.update_choice = None
        self.update_opened = time.monotonic()
        self.mode = "update"
        self._sound("open")

    def _update_cancellable(self) -> bool:
        return self.update_install_job is not None and self.update_progress[0] != "preparing"

    def _on_update_action(self, action: Action) -> None:
        choices = update_choices(self.update, bool(getattr(sys, "frozen", False)))
        if action == Action.BACK and self._update_cancellable() and self.update_cancel:
            self.update_cancel.set()
            return
        if self.update_install_job is not None:
            return
        if action in (Action.UP, Action.DOWN):
            sel = max(0, min(len(choices) - 1, self.update_sel + (-1 if action == Action.UP else 1)))
            if sel != self.update_sel:
                self.update_sel = sel
                self._sound("move")
        elif action == Action.CONFIRM:
            self._update_pick(self.update_sel)
        elif action == Action.BACK:
            self._update_pick(next(i for i, item in enumerate(choices) if item[0] == "later"))

    def _update_hover(self, i: int) -> None:
        if i != self.update_sel:
            self.update_sel = i
            self._sound("move")

    def _update_pick(self, i: int) -> None:
        choices = update_choices(self.update, bool(getattr(sys, "frozen", False)))
        if not 0 <= i < len(choices):
            return
        self.update_sel = i
        self.update_choice = choices[i][0]
        info = self.update or {}
        if self.update_install_job is not None and self.update_choice != "install":
            return
        if self.update_choice == "install":
            if self.update_install_job is not None:
                if self._update_cancellable() and self.update_cancel:
                    self.update_cancel.set()
                return
            self._start_update_install()
            return
        if self.update_choice == "open" and info.get("url"):
            try:
                webbrowser.open(info["url"])
            except webbrowser.Error:
                pass
            # Counts as "later": if they don't update, the notice returns next launch.
        elif self.update_choice == "skip" and info.get("version"):
            self.state.skip_update(info["version"])
        self._close_overlay()

    def _start_update_install(self) -> None:
        info = self.update or {}
        asset = info.get("asset")
        if not asset or self.update_install_job and not self.update_install_job.done():
            return
        install_path = self_update.installation_path(Path(sys.executable), asset.target)
        if install_path is None:
            self.update_error = tr("update.packaged_only")
            return
        self.update_error = None
        self.update_progress = ("checking", 0, None)
        self.update_cancel = threading.Event()
        if self.update_pool is None:
            self.update_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="update")

        def progress(phase: str, done: int, total: int | None) -> None:
            self.update_progress = (phase, done, total)
            if phase == "verifying":
                time.sleep(UPDATE_VERIFY_HOLD_SECONDS)  # the hash is ready at the last byte; let the step read

        self.update_install_job = self.update_pool.submit(
            self_update.download_and_prepare, asset, info["version"], staging_root=install_path.parent,
            platform=asset.target, progress=progress, cancel=self.update_cancel)

    def _start_update_check(self, now: float) -> None:
        if not self.state.update_check or updates.disabled():
            return
        self.update_started = now
        self.update_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="update")  # apart from the art pool: a slow network must not stall title art
        self.update_job = self.update_pool.submit(updates.check, __version__, self.state.update_skip)

    def _poll_update(self, now: float) -> None:
        """Show the notice once, a few seconds in, and only from the plain list so it never interrupts anything."""
        install_job = self.update_install_job
        if install_job is not None and install_job.done():
            self.update_install_job = None
            staged = None
            cancelled = bool(self.update_cancel and self.update_cancel.is_set())
            try:
                staged = install_job.result()
                if cancelled:
                    self_update.discard_staged(staged)
                    self.update_error = tr("update.cancelled")
                    return
                # Only a process spawn here: the job already unpacked and copied everything.
                info = self.update or {}
                install_path = self_update.installation_path(Path(sys.executable), info["asset"].target)
                self_update.launch_apply_helper(staged, install_path, os.getpid(), info["asset"].target,
                                                config.STATE_DIR / self_update.RESULT_FILE)
                # The helper waits for this process to exit. Leave via os._exit once pygame is down:
                # interpreter shutdown frees tinysoundfont, and the unpatched Intel build aborts there.
                # That crash dialog is the update "exiting with a crash" before the new copy opens.
                self.update_handoff = True
                self.running = False
            except Exception as exc:
                if staged:
                    self_update.discard_staged(staged)
                if cancelled:
                    self.update_error = tr("update.cancelled")
                else:
                    self.update_error = str(exc)
                    self._sound("error")
        job = self.update_job
        if job is None or not job.done() or now - self.update_started < UPDATE_DELAY_SECONDS:
            return
        if self.mode != "list" or now < self.ignore_until:
            return
        self.update_job = None
        try:
            info = job.result()
        except Exception:
            info = None
        if info:
            self._open_update(info)

    def _report_update_result(self) -> None:
        result = self_update.take_result(config.STATE_DIR / self_update.RESULT_FILE)
        if result is None:
            return
        if result["ok"]:
            if self.whats_new:
                return  # the What's new screen already says which version this is
            self.toast = Toast(tr("toast.updated", version=__version__), self.theme.label, time.monotonic(), ttl=6.0)
        else:
            log.write("update failed", str(result.get("error", "")))
            self.toast = Toast(tr("toast.update_failed"), ERROR, time.monotonic(), ttl=8.0)

    def _choose(self, choice: Choice, added: bool = False) -> None:
        try:
            opts = self.launchers.choose(choice, added)
        except OptionsError as exc:
            self._notify(exc.title, ERROR)
            self._sound("error")
            return
        self.mode = "list"
        self._apply(opts)

    def _open_browser(self, directory: Path | None = None) -> None:
        names = {name for source in SOURCES for name in (*source.module.EXES, *source.module.SETTINGS_NAMES)}
        names.update(easter_eggs.SELF_EXECUTABLE_NAMES)
        if config.FROZEN:
            names.update(path.name for path in easter_eggs.self_paths())
        start = directory or config.self_location() or (config.PROJECT_ROOT if config.SOURCE_TREE else None)
        labels = {".zdl": "ZDL"}
        for source in SOURCES:
            for name in (*source.module.EXES, *source.module.SETTINGS_NAMES):
                # Both Doom Launchers share a database name; the first keeps it.
                labels.setdefault(name, getattr(source.module, "LABELS", {}).get(name, source.module.NAME))
        self.file_browser = FileBrowser(start=start, names=names, include=easter_eggs.self_matcher(), labels=labels)
        self.browser_scroll = 0
        self.mode = "browse"
        self._sound("open")

    def _browser_action(self, action: Action, *, wrap: bool = True) -> None:
        browser = self.file_browser
        if browser is None:
            self.mode = "launcher"
            return
        before = browser.directory, browser.selected, browser.show_all
        if action == Action.UP:
            browser.move(-1, wrap=wrap)
        elif action == Action.DOWN:
            browser.move(1, wrap=wrap)
        elif action in (Action.PAGE_UP, Action.LEFT):
            page_size = self._browser_page_size()
            browser.move(-page_size, wrap=False)
            self.browser_scroll = max(0, self.browser_scroll - page_size)
        elif action in (Action.PAGE_DOWN, Action.RIGHT):
            page_size = self._browser_page_size()
            browser.move(page_size, wrap=False)
            self.browser_scroll += page_size
        elif action == Action.HOME:
            browser.move(-browser.selected, wrap=False)
            self.browser_scroll = 0
        elif action == Action.END:
            browser.move(len(browser.entries) - 1 - browser.selected, wrap=False)
            self.browser_scroll = max(0, len(browser.entries) - self._browser_page_size())
        elif action == Action.ALT:
            browser.toggle_all()
            self.browser_scroll = 0
        elif action == Action.CONFIRM:
            entry = browser.entries[browser.selected] if browser.entries else None
            if entry is not None and entry.root_selector:
                browser.select_root(entry.path)
                self.browser_scroll = 0
            elif entry is not None and entry.parent_selector:
                browser.back()
            else:
                if entry is not None and not entry.is_dir and (reaction := easter_eggs.react_to_pick(entry.path)):
                    self._show_reaction(reaction)
                    return
                path = browser.open_selected()
                if path is not None:
                    self.file_browser = None
                    self.mode = "launcher"
                    self._on_drop(path)
        elif action == Action.BACK:
            if browser.back():
                browser.move(0)
            else:
                self.file_browser = None
                self.mode = "launcher"
                self._sound("close")
        page_size = self._browser_page_size()
        if browser.selected < self.browser_scroll:
            self.browser_scroll = browser.selected
        elif browser.selected >= self.browser_scroll + page_size:
            self.browser_scroll = browser.selected - page_size + 1
        self.browser_scroll = max(0, min(self.browser_scroll, max(0, len(browser.entries) - page_size)))
        if self.mode == "browse" and before != (browser.directory, browser.selected, browser.show_all):
            self._sound("move")

    def _browser_head_h(self) -> int:
        """Title plus the folder path; the drive list has no path line."""
        browser = self.file_browser
        return int((64 if browser is not None and browser.selecting_root else 92) * self.s)

    def _browser_page_size(self) -> int:
        pad, row_h, head_h = int(28 * self.s), int(54 * self.s), self._browser_head_h()
        max_height = self.h - self.footer_h - int(32 * self.s)
        return max(1, min(16, (max_height - 2 * pad - head_h) // row_h))

    def _on_drop(self, path: Path) -> None:
        """A file or folder dropped on the window, or picked in the browser: use the launcher it belongs to."""
        if reaction := easter_eggs.react_to_pick(path):
            self._show_reaction(reaction)
            return
        if not self.launchers:
            if path.is_dir() and (reaction := easter_eggs.react_to_folder(path)):
                self._show_reaction(reaction)
            return
        choice = self.launchers.add(path)
        if choice is None:
            if path.is_dir() and (reaction := easter_eggs.react_to_folder(path)):
                self._show_reaction(reaction)
                return
            exe = next((s for s in SOURCES if path.name.lower() in s.module.EXES), None)
            if exe:
                self._notify(tr("toast.no_settings", name=exe.name), ERROR)
            else:
                self._notify(tr("toast.not_launcher", name=path.name), ERROR)
            self._sound("error")
            return
        self._choose(choice, added=True)

    def _show_reaction(self, reaction: easter_eggs.Reaction) -> None:
        """The only place an easter egg is presented, so handlers stay free of message and sound details."""
        self._notify(reaction.message, self.theme.label)
        if reaction.sound and self.state.menu_sounds and self.sfx:
            self.sfx.play(reaction.sound)

    # ---------- audio ----------

    def _audio_up(self) -> None:
        if not pygame.mixer.get_init():
            try:
                pygame.mixer.init(44100, 32, 2, 1024)
            except pygame.error:
                return
        pygame.mixer.set_num_channels(8)
        pygame.mixer.set_reserved(3)
        self.music = MusicPlayer(self.soundfont, tuple(pygame.mixer.Channel(c) for c in MUSIC_CHANNELS))
        self.sfx = Sfx(self.opts, pygame.mixer.Channel(MOVE_CHANNEL))

    def _audio_down(self) -> None:
        """Release the audio device while a game runs; some engines open it exclusively."""
        if self.music:
            self.music.shutdown()
        self.music = self.sfx = None
        self._music_sel = None
        pygame.mixer.quit()

    def _sound(self, name: str) -> bool:
        if self.state.menu_sounds and self.sfx:
            return self.sfx.play(name)
        return False

    def _update_music(self, now: float) -> None:
        if not self.music:
            return
        self.music.update()
        moved = self.current != self._music_sel
        if moved:
            self._music_sel, self._music_since = self.current, now
        if not self.state.music or not self.rows or self._category_selected():
            self.music.request(None)
        elif self.music.want == self.current:
            # Playing, loading, or finished; title tracks play once, like on the engine's title screen.
            # Meanwhile render the neighbours, so the next move starts from the cache.
            self._warm_nearby_music()
        elif now - self._music_since >= DWELL_SECONDS:
            p = self.opts.presets[self.current]
            self.music.request(self.current, soundfont=self._music_font(p), preset=p)
        elif moved:
            # A track the next preset doesn't share fades now rather than trailing through the dwell and the
            # next track's preparation.
            p = self.opts.presets[self.current]
            self.music.leave(self.current, soundfont=self._music_font(p), preset=p)

    def _warm_nearby_music(self) -> None:
        """One neighbour at a time, the one below the selection first: that is where a held direction goes."""
        music = self.music
        if not music or music.job or music.pending or not self.rows:
            return
        sel = self._sel_row()
        if self.rows[sel].kind != "preset":
            return
        seen: list[int] = []
        for row in (*self.rows[sel + 1:], *reversed(self.rows[:sel])):
            if row.kind == "preset" and row.preset != self.current and row.preset not in seen:
                seen.append(row.preset)
            if len(seen) == 2:
                break
        for idx in seen:
            p = self.opts.presets[idx]
            music.warm(idx, soundfont=self._music_font(p), preset=p)
            if music.job:
                return

    def _music_font(self, preset: Preset) -> Path | None:
        overrides = (self.soundfont_choice, os.environ.get("DOOMRUNNER_SOUNDFONT"))
        engine_font = None
        if not any(font and Path(font).is_file() for font in overrides):
            engine_font = self._engine_soundfont_for(self.opts.engine_for(preset))
        return engine_font or self.soundfont

    def _set_music(self, on: bool) -> None:
        if self.state.music == on:
            return
        self.state.set_music(on)
        self._music_sel = None
        self._sound("open" if on else "close")
        log.write("music: toggled", "Title music on" if on else "Title music off")

    def _toggle_favorite(self) -> None:
        if not self.rows:
            return
        sel = self._sel_row()
        was_fav, old_y = self.rows[sel].fav, self.row_y[sel]
        next_below = next((row.preset for row in self.rows[sel + 1:] if row.kind == "preset"), None) if was_fav else None
        on = self.state.toggle_favorite(self.opts.presets[self.current].name)
        self._rebuild_rows()
        if not on and next_below is not None:
            self.current = next_below
        copies = [i for i, r in enumerate(self.rows) if r.kind == "preset" and r.preset == self.current]
        if copies:
            self.cur_row = next((i for i in copies if self.rows[i].fav == was_fav), copies[0])
            # Rows above may have appeared or vanished; shift the view with them so the cursor stays put.
            shift = self.row_y[self.cur_row] - old_y
            self.scroll += shift
            self.bar_y += shift
        self._sound("open" if on else "close")
        self._notify(tr("toast.added_favorite") if on else tr("toast.removed_favorite"), self.theme.label if on else MUTED)

    # ---------- window / layout ----------

    def _open_window(self) -> None:
        # Right after a game exits, Windows may still be freeing its window objects, and creating ours fails with
        # "used all of its system allowance of handles". That clears within seconds, so wait instead of crashing.
        for attempt in range(WINDOW_RETRIES):
            try:
                return self._create_window()
            except pygame.error as exc:
                if attempt == WINDOW_RETRIES - 1:
                    raise
                if attempt == 0:
                    log.write("window retry", f"{exc}\nTrying again for up to {WINDOW_RETRIES // 2} seconds.")
                time.sleep(0.5)
                self._close_window()
                pygame.display.init()
                pygame.display.set_caption("CouchDoom")

    def _close_window(self) -> None:
        """Release Pygame's display surface before destroying its window or video subsystem."""
        if isinstance(self.screen, canvas.Canvas):
            self.screen.close()  # textures and renderer first: SDL frees them with the window
        self.screen = None
        if self.window is not None:
            self.window.destroy()
            self.window = None
        pygame.display.quit()

    def _create_window(self) -> None:
        _set_window_icon()  # display.quit() after a game forgets it
        size = (1440, 810) if self.windowed else pygame.display.get_desktop_sizes()[0]
        self.window = None
        self.dpi = 1.0
        if sys.platform == "darwin":
            # display.set_mode renders in points and macOS upscales it on Retina; draw at backing pixels instead.
            self.window = pygame.Window("CouchDoom", size, allow_high_dpi=True)
            if not self.windowed:
                # A borderless window sits under the menu bar and Dock; fullscreen hides them.
                self.window.set_fullscreen(desktop=True)
                for _ in range(30):
                    pygame.event.pump()
                    time.sleep(0.01)
                _disable_macos_fullscreen_shadow()
            self.screen = self._window_target(self.window)
            self.dpi = self.screen.get_width() / self.window.size[0]
            _set_window_icon(self.window)  # Window() just installed pygame's Dock icon
        elif self.windowed:
            self.screen = pygame.display.set_mode(size)
        else:
            self.screen = pygame.display.set_mode(size, pygame.NOFRAME)
        self.refresh_hz = display_refresh_rate()  # per window: get_current_refresh_rate needs the window to exist
        self._mouse_off()
        pygame.key.start_text_input()
        self._layout()
        _force_foreground()

    @staticmethod
    def _window_target(window: pygame.Window) -> canvas.Canvas | pygame.Surface:
        """The GPU canvas when the system has one, else the window's own software surface."""
        if use_gpu():
            try:
                return canvas.Canvas(window)
            except canvas.ERRORS as exc:
                log.write("gpu renderer unavailable", f"{exc}\nDrawing in software instead.")
        return window.get_surface()

    def _frame_cap(self) -> int:
        """clock.tick's ceiling. On the canvas vsync paces the present, so the cap sits above the display: a
        reported 119 for a 119.88 Hz mode would otherwise drift a sleep past a vblank about once a second."""
        if isinstance(self.screen, canvas.Canvas):
            return round(self.refresh_hz * 1.25)
        return self.refresh_hz

    def _on_window_event(self, event) -> bool:
        """Window lifecycle events; True when handled. The canvas's hidden format window is not the app's."""
        source = getattr(event, "window", None)
        if isinstance(self.screen, canvas.Canvas) and source is not None and source is self.screen.format_window:
            return event.type in WINDOW_EVENTS
        if event.type == pygame.QUIT or event.type == pygame.WINDOWCLOSE:
            # With the format window open, the close button and Alt+F4 post WINDOWCLOSE and never QUIT.
            self.running = False
        elif event.type in (pygame.WINDOWMINIMIZED, pygame.WINDOWHIDDEN):
            self.hidden = True
        elif event.type in (pygame.WINDOWRESTORED, pygame.WINDOWSHOWN, pygame.WINDOWEXPOSED):
            self.hidden = False
        elif event.type == pygame.WINDOWDISPLAYCHANGED:
            self.refresh_hz = display_refresh_rate()
        elif event.type == pygame.RENDER_DEVICE_RESET:
            # The GPU dropped every texture (driver update, D3D device lost). A new window re-uploads them all.
            log.write("gpu device reset", "Recreating the window.")
            self._close_window()
            pygame.display.init()
            pygame.display.set_caption("CouchDoom")
            self._open_window()
            self.hidden = False
        else:
            return False
        return True

    def _flip(self) -> None:
        if isinstance(self.screen, canvas.Canvas):
            self.screen.present()
        elif self.window is not None:
            self.window.flip()
        else:
            pygame.display.flip()

    def _font(self, size: float, bold: bool = False, mono: bool = False) -> pygame.font.Font:
        px = max(9, int(size * self.s))
        key = (px, bold, mono)
        if key not in self._fonts:
            # Bundled files with a real bold, so every OS looks the same; SDL_ttf's synthetic bold has jagged edges.
            name = "JetBrainsMono-Regular.ttf" if mono else "Barlow-Bold.ttf" if bold else "Barlow-Regular.ttf"
            self._fonts[key] = pygame.font.Font(str(FONTS / name), px)
        return self._fonts[key]

    def _layout(self) -> None:
        w, h = self.screen.get_size()
        resized = (w, h) != getattr(self, "_size", None)
        self._size = self.w, self.h = w, h
        self.s = s = h / 1080
        self._fonts: dict = {}
        self._text_cache: dict = {}
        # Both caches key on Font objects, which were just replaced; drop the old fonts with them.
        App._fit.cache_clear()
        App._fit_start.cache_clear()
        App._wrap.cache_clear()
        self.glyphs = Glyphs(self._font, s)

        self.margin = int(72 * s)
        self.header_h = int(62 * s)
        self.preset_h = int(60 * s)
        self.footer_h = int(92 * s)
        list_top = self.margin + int(196 * s)
        self.list_edge = int(w * 0.50)
        self.scroll_w = max(2, int(4 * s))
        list_w = self.list_edge - self.scroll_w - int(28 * s) - self.margin
        self.list_rect = pygame.Rect(self.margin, list_top, list_w, h - list_top - self.footer_h - int(12 * s))
        detail_x = self.list_edge + self.margin
        self.detail_rect = pygame.Rect(detail_x, list_top, w - detail_x - self.margin, self.list_rect.height - int(8 * s))
        self.art_rect = pygame.Rect(self.list_edge, 0, w - self.list_edge, int(h * 0.72))

        self._compute_row_y()
        self._theme_bgs.clear()
        self._theme_bars.clear()
        self._theme_layers.clear()
        self.theme_from = None
        self._masks = self._make_masks()
        self.bar_surface = self._bar_for(self.theme)
        if resized:
            self._drop_sized_renders()
            self.art_cache.clear()
            self.art_layers.clear()
            self.logos.clear()

    def _background_for(self, theme: Theme) -> pygame.Surface:
        return _theme_cache(self._theme_bgs, theme.key, lambda: self._make_background(theme))

    def _bar_for(self, theme: Theme) -> pygame.Surface:
        def create() -> pygame.Surface:
            w = self.list_rect.width + int(28 * self.s)
            left, right = theme.bar
            return draw.horizontal_ramp(w, self.preset_h, (*left, 240), (*right, 0), curve=1.3)
        return _theme_cache(self._theme_bars, theme.key, create)

    def _make_background(self, theme: Theme) -> pygame.Surface:
        # Build the vertical gradient in a one-pixel strip, then expand it in C instead of
        # issuing one full-screen draw call per scanline on the UI thread.
        strip = pygame.Surface((1, self.h))
        top, bottom = theme.bg_top, theme.bg_bottom
        for y in range(self.h):
            t = (y / max(1, self.h - 1)) ** 1.6
            strip.set_at((0, y), [int(_lerp(top[i], bottom[i], t)) for i in range(3)])
        bg = pygame.transform.scale(strip.convert(_OPAQUE), (self.w, self.h))
        lines = pygame.Surface((1, self.h), pygame.SRCALPHA)
        step = max(3, int(4 * self.s))
        for y in range(0, self.h, step):
            lines.set_at((0, y), (0, 0, 0, 30))
        bg.blit(pygame.transform.scale(lines, (self.w, self.h)), (0, 0))
        return bg

    def _alpha_mask(self, size: tuple[int, int], fn) -> pygame.Surface:
        """White mask whose alpha is fn(u, v) in 0..1, computed coarse then smoothly upscaled."""
        lw, lh = 64, 48
        low = pygame.Surface((lw, lh), pygame.SRCALPHA)
        for j in range(lh):
            for i in range(lw):
                low.set_at((i, j), (255, 255, 255, int(255 * max(0.0, min(1.0, fn(i / (lw - 1), j / (lh - 1)))))))
        return pygame.transform.smoothscale(low, size)

    def _bg_overlay(self, bg: pygame.Surface, rect: pygame.Rect, mask: pygame.Surface) -> pygame.Surface:
        surf = pygame.Surface(rect.size, pygame.SRCALPHA)
        surf.blit(bg, (0, 0), rect)
        surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        return surf

    def _make_masks(self) -> dict[str, tuple[pygame.Rect, pygame.Surface]]:
        """Alpha shapes of the background-coloured overlays; they're filled from whatever background is current."""
        lr, s = self.list_rect, self.s
        fade_h = int(44 * s)
        x = lr.x - int(28 * s)
        width = self.list_edge - x
        top_rect = pygame.Rect(x, lr.y - int(4 * s), width, fade_h)
        bottom_rect = pygame.Rect(x, lr.bottom - fade_h + int(4 * s), width, fade_h)

        # Veil so the title art dissolves into the page at the bottom. Left and right stay crisp crop
        # edges: fading only one side made off-centre art look lopsided.
        def veil(u: float, v: float) -> float:
            bottom = _smoothstep((v - 0.22) / 0.56)
            top = 0.75 * (1 - _smoothstep(v / 0.16))
            return max(0.30, bottom, top)

        return {
            "top": (top_rect, self._alpha_mask(top_rect.size, lambda u, v: 1 - _smoothstep(v))),
            "bottom": (bottom_rect, self._alpha_mask(bottom_rect.size, lambda u, v: _smoothstep(v))),
            "veil": (self.art_rect, self._alpha_mask(self.art_rect.size, veil)),
        }

    def _layers_for(self, theme: Theme) -> dict[str, tuple[pygame.Surface, tuple[int, int]]]:
        """Background plus the overlays that must match it, cached per theme."""
        def create() -> dict[str, tuple[pygame.Surface, tuple[int, int]]]:
            bg = self._background_for(theme)
            return self._make_theme_layers(bg)
        return _theme_cache(self._theme_layers, theme.key, create)

    def _make_theme_layers(self, bg: pygame.Surface) -> dict[str, tuple[pygame.Surface, tuple[int, int]]]:
        layers = {"bg": (bg, (0, 0))}
        for name, (rect, mask) in self._masks.items():
            layers[name] = (self._bg_overlay(bg, rect, mask), rect.topleft)
        return layers

    def _blit_layer(self, name: str) -> None:
        """Mid-change, the old theme's layer goes down first and the new one fades in over it."""
        surf, pos = self._layers_for(self.theme)[name]
        if self.theme_from is None:
            self.screen.blit(surf, pos)
            return
        old = self._layers_for(self.theme_from)[name][0]
        if name == "bg":
            self.screen.blit(old, pos)
            surf.set_alpha(int(255 * self.theme_t))
            self.screen.blit(surf, pos)
            _reset_alpha(surf)
            return
        # Masked overlays share one alpha shape: stacking the new over the old would thicken it mid-fade
        # (it snaps back thin when the fade ends), so mix their colours and keep the alpha as is.
        if isinstance(self.screen, canvas.Canvas):
            self.screen.blit_mix(old, surf, self.theme_t, pos)
            return
        k = int(255 * self.theme_t)
        mixed = old.copy()
        mixed.fill((255 - k, 255 - k, 255 - k, 255), special_flags=pygame.BLEND_RGBA_MULT)
        incoming = surf.copy()
        incoming.fill((k, k, k, 255), special_flags=pygame.BLEND_RGBA_MULT)
        mixed.blit(incoming, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
        self.screen.blit(mixed, pos)

    def _update_theme(self, now: float) -> None:
        """Follow the title art on screen; the background crossfades in step with the art itself."""
        if not self.art_layers:
            return
        idx, surf, born = self.art_layers[-1]
        target = self._effective_theme(idx, surf is not None)
        if target != self.theme:
            # Changed again mid-fade: continue from whichever theme dominated the screen.
            if self.theme_from is None or self.theme_t >= 0.5:
                self.theme_from = self.theme
            self.theme = target
            self.theme_born = born
            self.bar_surface = self._bar_for(target)
        if self.theme_from is not None:
            self.theme_t = _smoothstep((now - self.theme_born) / ART_FADE_SECONDS)
            if self.theme_t >= 1 or self.theme_from == self.theme:
                self.theme_from = None

    def _current_palette_key(self) -> str:
        key = getattr(self.state, "color_palette", "auto")
        return key if key in {palette for palette, _ in PALETTES} else "auto"

    def _effective_theme(self, idx: int, has_art: bool) -> Theme:
        override = theme_for_palette(self._current_palette_key())
        if override is not None:
            return override
        if idx < 0 or not has_art:
            return HOUSE
        return self.themes.get(idx, HOUSE)

    def _apply_palette(self, key: str) -> None:
        self.state.set_color_palette(key)
        idx, surf = (self.art_layers[-1][0], self.art_layers[-1][1]) if self.art_layers else (self.current, None)
        has_art = surf is not None or (0 <= idx < len(self.opts.presets) and idx in self.themes)
        target = self._effective_theme(idx, has_art)
        self.theme_from = None
        self.theme = target
        self.theme_t = 1.0
        self.bar_surface = self._bar_for(target)

    # ---------- rows / selection ----------

    def _matches(self, idx: int, terms: list[str]) -> bool:
        p = self.opts.presets[idx]
        hay = f"{p.name} {p.section}".lower()
        return all(t in hay for t in terms)

    def _rebuild_rows(self) -> None:
        terms = self.filter.lower().split()
        rows: list[Row] = []
        names = {p.name: i for i, p in enumerate(self.opts.presets)}
        favs = [names[f] for f in self.state.favorites if f in names and self._matches(names[f], terms)]
        if favs:
            collapsed = not terms and FAVORITES_ID in self.collapsed_sections
            rows.append(Row("header", tr("group.favorites"), count=len(favs), collapsed=collapsed, group_id=FAVORITES_ID))
            if not collapsed:
                rows += [Row("preset", self.opts.presets[i].name, i, fav=True) for i in favs]
        if getattr(self.state, "recent_group", False):
            recent = [names[name] for name in getattr(self.state, "history", []) if name in names and self._matches(names[name], terms)]
            if recent:
                collapsed = not terms and RECENT_ID in self.collapsed_sections
                rows.append(Row("header", tr("group.recent"), count=len(recent), collapsed=collapsed, group_id=RECENT_ID))
                if not collapsed:
                    rows += [Row("preset", self.opts.presets[i].name, i) for i in recent]
        for section in self.opts.sections:
            hits = [i for i, p in enumerate(self.opts.presets) if p.section == section and self._matches(i, terms)]
            if hits:
                collapsed = not terms and section in self.collapsed_sections
                rows.append(Row("header", section, count=len(hits), collapsed=collapsed))
                if not collapsed:
                    rows += [Row("preset", self.opts.presets[i].name, i) for i in hits]
        self.rows = rows
        self.cur_row = -1
        self.free_scroll = None
        visible = [r.preset for r in rows if r.kind == "preset"]
        if visible and self.current not in visible:
            self.current = visible[0]
        if hasattr(self, "s"):
            self._compute_row_y()

    def _compute_row_y(self) -> None:
        y = 0
        self.row_y: list[int] = []
        for i, r in enumerate(self.rows):
            if r.kind == "header" and i > 0:
                y += int(20 * self.s)
            self.row_y.append(y)
            y += self.header_h if r.kind == "header" else self.preset_h
        self.content_h = y

    def _preset_rows(self) -> list[int]:
        return [i for i, r in enumerate(self.rows) if r.kind == "preset"]

    def _category_selected(self) -> bool:
        return bool(self.rows and self.rows[self._sel_row()].kind == "header")

    def _sel_row(self) -> int:
        if 0 <= self.cur_row < len(self.rows) and self.rows[self.cur_row].kind == "header":
            return self.cur_row
        if 0 <= self.cur_row < len(self.rows) and self.rows[self.cur_row].preset == self.current:
            return self.cur_row
        for i, r in enumerate(self.rows):
            if r.kind == "preset" and r.preset == self.current:
                return i
        return 0

    def _select_row(self, row: int) -> None:
        if 0 <= row < len(self.rows):
            self.cur_row = row
            if self.rows[row].kind == "preset" and self.rows[row].preset != self.current:
                self.current = self.rows[row].preset
            self.detail_changed = time.monotonic()
            self._sound("move")

    @staticmethod
    def _step_index(index: int, count: int, delta: int, *, wrap: bool) -> int:
        if count <= 0:
            return 0
        target = index + delta
        return target % count if wrap else max(0, min(count - 1, target))

    def _move(self, delta: int, *, wrap: bool = True) -> None:
        if not self.rows:
            return
        self.free_scroll = None
        sel = self._sel_row()
        selected = self._step_index(sel, len(self.rows), delta, wrap=wrap)
        if selected != sel:
            self._select_row(selected)

    def _copies_of(self, idx: int) -> dict[str, int]:
        """First visible row of this game in each group."""
        found: dict[str, int] = {}
        group: str | None = None
        for i, row in enumerate(self.rows):
            if row.kind == "header":
                group = _header_key(row)
            elif row.preset == idx and group is not None and group not in found:
                found[group] = i
        return found

    def _reveal_group(self, key: str) -> None:
        if key in self.collapsed_sections:
            self.collapsed_sections.discard(key)
            self._rebuild_rows()

    def _jump_to_last_played(self) -> None:
        """B or Ctrl: select the last game played.

        With Recently Played on, the game is listed there and in its own group. Pressing again
        switches between those two rows, so a list that opened on the recent copy can still
        reach the game where it lives.
        """
        name = getattr(self.state, "last_played", None)
        if not name:
            return
        idx = next((i for i, preset in enumerate(self.opts.presets) if preset.name == name), None)
        if idx is None:
            return
        section = self.opts.presets[idx].section
        history = getattr(self.state, "history", ())
        if getattr(self.state, "recent_group", False) and name in history:
            self._toggle_last_played(idx, section)
            return
        if not any(row.kind == "preset" and row.preset == idx for row in self.rows):
            if section not in self.collapsed_sections:
                return
            self._reveal_group(section)
        if any(i == self._sel_row() and row.kind == "preset" and row.preset == idx for i, row in enumerate(self.rows)):
            return
        target = next((i for i, row in enumerate(self.rows) if row.kind == "preset" and row.preset == idx), None)
        if target is None:
            return
        self.free_scroll = None
        self._select_row(target)

    def _toggle_last_played(self, idx: int, section: str) -> None:
        sel = self._sel_row() if self.rows else -1
        dest = section if self._copies_of(idx).get(RECENT_ID) == sel else RECENT_ID
        self._reveal_group(dest)
        target = self._copies_of(idx).get(dest)
        if target is None and dest == RECENT_ID:
            self._reveal_group(section)
            target = self._copies_of(idx).get(section)
        if target is None or target == self._sel_row():
            return
        self.free_scroll = None
        self._select_row(target)

    def _jump_section(self, direction: int) -> None:
        headers = [i for i, r in enumerate(self.rows) if r.kind == "header"]
        if not headers:
            return
        self.free_scroll = None
        sel = self._sel_row()
        current_header = sel if self.rows[sel].kind == "header" else max((h for h in headers if h < sel), default=headers[0])
        candidates = [h for h in headers if h < current_header] if direction < 0 else [h for h in headers if h > current_header]
        target = candidates[-1] if direction < 0 and candidates else candidates[0] if candidates else current_header
        self._select_row(target)

    def _toggle_section(self, row: int) -> None:
        if not 0 <= row < len(self.rows) or self.rows[row].kind != "header":
            return
        if self.filter:
            self._notify(tr("toast.clear_search_fold"), self.theme.label)
            return
        key = _header_key(self.rows[row])
        if key in self.collapsed_sections:
            self.collapsed_sections.remove(key)
        else:
            self.collapsed_sections.add(key)
        self._rebuild_rows()
        self.cur_row = next((i for i, row in enumerate(self.rows) if row.kind == "header" and _header_key(row) == key), -1)
        self.detail_changed = time.monotonic()
        self._sound("move")

    def _all_header_names(self) -> set[str]:
        names = set(self.opts.sections)
        if self.state.favorites:
            names.add(FAVORITES_ID)
        if getattr(self.state, "recent_group", False) and getattr(self.state, "history", None):
            names.add(RECENT_ID)
        return names

    def _bulk_fold_label(self) -> str:
        headers = self._all_header_names()
        if headers - self.collapsed_sections:
            return tr("hint.collapse_all")
        return tr("hint.expand_all")

    def _focus_header_after_bulk(self, prefer: str | None = None) -> None:
        if prefer:
            match = next((i for i, row in enumerate(self.rows) if row.kind == "header" and _header_key(row) == prefer), None)
            if match is not None:
                self.cur_row = match
                self.detail_changed = time.monotonic()
                return
        header = next((i for i, row in enumerate(self.rows) if row.kind == "header"), -1)
        self.cur_row = header
        self.detail_changed = time.monotonic()

    def _collapse_all_groups(self) -> None:
        if self.filter:
            self._notify(tr("toast.clear_search_fold"), self.theme.label)
            return
        prefer = _header_key(self.rows[self._sel_row()]) if self.rows and self.rows[self._sel_row()].kind == "header" else None
        self.collapsed_sections = set(self._all_header_names())
        self._rebuild_rows()
        self._focus_header_after_bulk(prefer)
        self._sound("move")

    def _expand_all_groups(self) -> None:
        if self.filter:
            self._notify(tr("toast.clear_search_fold"), self.theme.label)
            return
        prefer = _header_key(self.rows[self._sel_row()]) if self.rows and self.rows[self._sel_row()].kind == "header" else None
        self.collapsed_sections.clear()
        self._rebuild_rows()
        self._focus_header_after_bulk(prefer)
        self._sound("move")

    def _bulk_fold_from_alt(self) -> None:
        headers = self._all_header_names()
        if headers - self.collapsed_sections:
            self._collapse_all_groups()
        else:
            self._expand_all_groups()

    def _category_presets(self, row: Row) -> list[int]:
        if row.kind != "header":
            return []
        terms = self.filter.lower().split()
        if row.group_id == FAVORITES_ID:
            names = {preset.name: i for i, preset in enumerate(self.opts.presets)}
            return [names[name] for name in self.state.favorites if name in names and self._matches(names[name], terms)]
        if row.group_id == RECENT_ID:
            names = {preset.name: i for i, preset in enumerate(self.opts.presets)}
            return [names[name] for name in getattr(self.state, "history", []) if name in names and self._matches(names[name], terms)]
        return [i for i, preset in enumerate(self.opts.presets) if preset.section == row.text and self._matches(i, terms)]

    def _category_preview_capacity(self, count: int, width: int, height: int, row_h: int) -> tuple[int, int, int]:
        columns = 2 if width >= int(520 * self.s) else 1
        row_capacity = max(0, height // max(1, row_h))
        capacity = columns * row_capacity
        if count > capacity and row_capacity:
            visible = columns * (row_capacity - 1)  # save the last row for the remainder note
        else:
            visible = min(count, capacity)
        return columns, visible, count - visible

    def _target_scroll(self) -> float:
        if not self.rows:
            return 0.0
        if self.free_scroll is not None:
            target = self.free_scroll
        else:
            sel = self._sel_row()
            target = self.row_y[sel] - self.list_rect.height * 0.38
            if sel > 0 and self.rows[sel - 1].kind == "header":
                target = min(target, self.row_y[sel - 1])
        return max(0.0, min(target, max(0, self.content_h - self.list_rect.height)))

    def _delete_filter_word(self) -> None:
        """Ctrl+Backspace: drop the trailing word (and spaces after the previous one)."""
        text = self.filter
        i = len(text)
        while i > 0 and text[i - 1].isspace():
            i -= 1
        while i > 0 and not text[i - 1].isspace():
            i -= 1
        if i != len(text):
            self._set_filter(text[:i])

    def _set_filter(self, text: str) -> None:
        self.filter = text
        self._rebuild_rows()
        self.detail_changed = time.monotonic()

    # ---------- title art ----------

    def _engine_soundfont_for(self, engine) -> Path | None:
        if engine is None:
            return None
        key = (engine.id, engine.name, engine.path, engine.config_dir)
        if key not in self._engine_soundfonts:
            self._engine_soundfonts[key] = find_engine_soundfont(engine)
        return self._engine_soundfonts[key]

    def _request_art(self, idx: int) -> None:
        if idx in self.art_cache or idx in self.art_jobs or idx in self.art_render_jobs or not (0 <= idx < len(self.opts.presets)):
            return
        self.art_jobs[idx] = self.art_pool.submit(_load_extras, self.opts.presets[idx])

    def _drop_sized_renders(self) -> None:
        """Forget renders sized for the old window; a running one can't be stopped, so its result is ignored."""
        for jobs in (self.art_render_jobs, self.logo_render_jobs):
            for job in jobs.values():
                job.cancel()
            jobs.clear()

    def _trim_art_cache(self) -> None:
        """Bound art by count and bytes; a preset's logo, readme, ENDOOM and theme leave with its art."""
        total = sum(_surface_bytes(surface) for surface in self.art_cache.values())
        while len(self.art_cache) > 1 and (len(self.art_cache) > ART_CACHE_SIZE or total > ART_CACHE_BYTES):
            _, evicted = self.art_cache.popitem(last=False)
            total -= _surface_bytes(evicted)
        # Extras of presets whose render was cancelled mid-way never reach art_cache; drop them too.
        keep = set(self.art_cache) | {self.current}
        for extras in (self.logos, self.readmes, self.endooms, self.themes):
            for idx in [idx for idx in extras if idx not in keep]:
                del extras[idx]

    def _should_show_title_text(self, idx: int) -> bool:
        """Keep the fallback title hidden until async asset loading decides whether a logo exists."""
        if idx in self.logos:
            return self.logos[idx] is None
        return not any(idx in jobs for jobs in (self.art_jobs, self.art_render_jobs, self.logo_render_jobs))

    def _logo_surface(self, logo: Art | None) -> pygame.Surface | None:
        """Menu logo scaled for the details panel, with a soft drop shadow like the text title's."""
        if logo is None:
            return None
        try:
            if logo.kind == "rgba":
                img = pygame.image.frombytes(logo.data, logo.size, "RGBA").convert_alpha()
            else:
                img = pygame.image.load(io.BytesIO(logo.data)).convert_alpha()
        except (pygame.error, ValueError):
            return None
        if _dark_backed(img):
            img = _key_out_dark(img)
        ink = img.get_bounding_rect()
        if ink.height < 4:
            return None
        img = img.subsurface(ink).copy()  # high-res logos often sit in a padded canvas
        w, h = img.get_size()
        aspect = 1.2 if logo.kind == "rgba" else 1.0  # Doom patches have tall pixels too
        if w < h:
            return None
        s = self.s
        scale = min(self.detail_rect.width / w, LOGO_MAX_H * s / (h * aspect))
        size = (max(1, int(w * scale)), max(1, int(h * aspect * scale)))
        if scale > 1:
            # Whole-number nearest-neighbour first, then smooth to the exact size: fractional nearest
            # scaling makes some pixel rows thicker than others, and smoothing straight up blurs.
            k = math.ceil(scale * aspect)
            img = pygame.transform.scale(img, (w * k, h * k))
        img = pygame.transform.smoothscale(img, size)
        off = max(2, int(4 * s))
        shadow = img.copy()
        shadow.fill((0, 0, 0, 150), special_flags=pygame.BLEND_RGBA_MULT)
        out = pygame.Surface((size[0] + off, size[1] + off), pygame.SRCALPHA)
        out.blit(shadow, (off, off))
        out.blit(img, (0, 0))
        return out

    @staticmethod
    def _art_image(art: Art) -> tuple[pygame.Surface, float] | None:
        """Decoded title art cropped to its 16:9 centre, and the vertical stretch its pixels need."""
        try:
            if art.kind == "encoded":
                img = pygame.image.load(io.BytesIO(art.data)).convert(_OPAQUE)
            else:
                img = pygame.image.frombytes(art.data, art.size, "P")
                img.set_palette([tuple(art.palette[i * 3 : i * 3 + 3]) for i in range(256)])
                img = img.convert(_OPAQUE)
        except (pygame.error, ValueError):
            return None
        w, h = img.get_size()
        # Doom-era art is 200 (or 400) lines tall at any width (320, KEX's 426 widescreen, ...) and the
        # engine stretches those lines 1.2x, so the pixels aren't square.
        aspect = 1.2 if h in (200, 400) else 1.0
        # Ultrawide title art (KEX's 560x200, Axolotl's 854x200) pads its sides for wider-than-16:9
        # displays; the 16:9 centre is what authors compose for. A 4:3 crop would go too far: Master
        # Levels, MyHouse and Technicolor put their logos out past it.
        width_169 = round(h * aspect * 16 / 9)
        if w > width_169:
            img = img.subsurface(pygame.Rect((w - width_169) // 2, 0, width_169, h)).copy()
        return img, aspect

    def _panel_fit(self, w: int, h: int, aspect: float) -> tuple[float, tuple[int, int]]:
        """How `_render_art` places w x h art in the panel: its scale, and where its top-left lands relative to
        the panel's. Fits the width; art that's still short after that may zoom up to 25% so it isn't a thin
        strip (short art dissolves at the bottom)."""
        tw, th = self.art_rect.size
        scale = tw / w
        if h * aspect * scale < th * ART_MIN_FILL:
            scale = min(th * ART_MIN_FILL / (h * aspect), scale * ART_MAX_ZOOM)
        size = (int(w * scale) + 1, int(h * aspect * scale) + 1)
        return scale, (-((size[0] - tw) // 2), -max(0, (size[1] - th) // 3))

    def _window_cover(self, w: int, h: int, aspect: float) -> tuple[float, tuple[int, int]]:
        """How the loading screen places w x h art across the window, like `_panel_fit`. Cropping 4:3 art to
        the window keeps more of the top, where title pictures put their logo."""
        scale = max(self.w / w, self.h / (h * aspect))
        cover = (math.ceil(w * scale), math.ceil(h * aspect * scale))
        return scale, ((self.w - cover[0]) // 2, -(cover[1] - self.h) // 6)

    def _render_art(self, art: Art | None):
        """Prepare selected art off-thread; return (theme, art, background, layers) for the UI thread to adopt."""
        lower_current_thread_priority()
        decoded = self._art_image(art) if art is not None else None
        if decoded is None:
            return None, None, None, None
        img, aspect = decoded
        w, h = img.get_size()
        theme = from_art(img)
        tw, th = self.art_rect.size
        scale, (ox, oy) = self._panel_fit(w, h, aspect)
        size = (int(w * scale) + 1, int(h * aspect * scale) + 1)
        scaled = pygame.transform.scale(img, size) if w <= 640 else pygame.transform.smoothscale(img, size)
        out = pygame.Surface((tw, th)).convert(_OPAQUE)
        background = self._make_background(theme)
        out.blit(background, (0, 0), self.art_rect)  # its own theme, for short art
        layers = self._make_theme_layers(background)
        crop = scaled.subsurface(pygame.Rect(-ox, -oy, tw, min(th, size[1])))
        if crop.get_height() < th:
            # Art shorter than the panel: dissolve its bottom edge instead of leaving a hard line.
            crop = crop.convert_alpha()
            crop.blit(self._alpha_mask(crop.get_size(), lambda u, v: 1 - _smoothstep((v - 0.55) / 0.45)), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        out.blit(crop, (0, 0))
        return theme, out, background, layers

    def _update_art(self, now: float) -> None:
        # A heading stands for a whole group, so no one game's art (and theme) speaks for it.
        if not self.rows or self._category_selected():
            if not self.art_layers or self.art_layers[-1][0] != -1:
                self.art_layers.append((-1, None, now))
                self.art_layers = self.art_layers[-2:]
            return
        selected = self.current
        for idx, job in list(self.art_jobs.items()):
            if idx != selected:
                job.cancel()
                del self.art_jobs[idx]
        for idx, job in list(self.art_render_jobs.items()):
            if idx != selected:
                job.cancel()
                del self.art_render_jobs[idx]
        for idx, job in list(self.logo_render_jobs.items()):
            if idx != selected:
                job.cancel()
                del self.logo_render_jobs[idx]

        if selected in self.art_jobs and self.art_jobs[selected].done():
            job = self.art_jobs.pop(selected)
            try:
                art, readme, endoom, logo = job.result()
            except Exception:
                art, readme, endoom, logo = None, None, None, None
            self.readmes[selected] = readme
            self.endooms[selected] = endoom
            self.logo_render_jobs[selected] = self.art_pool.submit(self._logo_surface, logo)
            self.art_render_jobs[selected] = self.art_pool.submit(self._render_art, art)

        if selected in self.logo_render_jobs and self.logo_render_jobs[selected].done():
            job = self.logo_render_jobs.pop(selected)
            try:
                self.logos[selected] = job.result()
            except Exception:
                self.logos[selected] = None

        if selected in self.art_render_jobs and self.art_render_jobs[selected].done():
            job = self.art_render_jobs.pop(selected)
            try:
                theme, surface, background, layers = job.result()
            except Exception:
                theme, surface, background, layers = None, None, None, None
            if theme is not None:
                self.themes[selected] = theme
                _theme_cache_put(self._theme_bgs, theme.key, background)
                _theme_cache_put(self._theme_layers, theme.key, layers)
            self.art_cache[selected] = surface
            self._trim_art_cache()

        self._request_art(selected)

        if selected in self.art_cache and (not self.art_layers or self.art_layers[-1][0] != selected):
            self.art_cache.move_to_end(selected)
            self.art_layers.append((selected, self.art_cache[selected], now))
            self.art_layers = self.art_layers[-2:]

    def _neighbors(self) -> list[int]:
        rows = self._preset_rows()
        sel = self._sel_row()
        if sel not in rows:
            return []
        pos = rows.index(sel)
        return [self.rows[rows[p]].preset for p in (pos - 1, pos + 1) if 0 <= p < len(rows)]

    def _warm_cache(self) -> None:
        self._warm_generation += 1
        generation = self._warm_generation
        try:
            def worker():
                try:
                    lower_current_thread_priority()
                    present_keys = []
                    music_keys = []
                    rows = self._preset_rows()
                    sel = self._sel_row()
                    if sel in rows:
                        pos = rows.index(sel)
                    else:
                        pos = 0
                    # BFS outward from current
                    order = []
                    seen = set()
                    q = [pos]
                    seen.add(pos)
                    i = 0
                    while i < len(q):
                        p = q[i]
                        i += 1
                        order.append(p)
                        for d in (-1, 1):
                            np = p + d
                            if 0 <= np < len(rows) and np not in seen:
                                seen.add(np)
                                q.append(np)
                    # Snapshot now: rows are rebuilt by search and folding, and a reload swaps opts underneath us.
                    # Visible presets go first; folded or filtered ones still count, or their caches look stale.
                    opts = self.opts
                    targets = list(dict.fromkeys(self.rows[rows[p]].preset for p in order))
                    visible = set(targets)
                    targets += [i for i in range(len(opts.presets)) if i not in visible]
                    completed = True
                    for idx in targets:
                        self._warm_allowed.wait()  # paused while a game runs, so it can have the disk and CPU
                        if not self.running or self._warm_generation != generation:
                            completed = False
                            break
                        try:
                            preset = opts.presets[idx]
                            unpack(preset)
                            files = load_order(preset)
                            iwad, shown = presented_files(preset)
                            key = asset_cache.key_for(preset, iwad, files)
                            present_keys.append(key)
                            from . import music_cache
                            music_keys.append(music_cache.selection_key(key, iwad, shown))
                            if idx in self.art_cache or idx in self.art_jobs:
                                continue
                            if asset_cache.get(key):
                                continue
                            # load and cache raw assets
                            _load_extras(preset)
                        except Exception:
                            continue
                    if not completed:
                        return  # a partial pass would mistake every unvisited preset for a removed one
                    try:
                        from . import music_cache
                        asset_cache.prune()
                        asset_cache.invalidate_missing(set(present_keys))
                        music_cache.invalidate_selections(set(music_keys))
                    except Exception:
                        pass
                except Exception:
                    pass

            t = threading.Thread(target=worker, daemon=True)
            t.start()
        except Exception:
            pass

    def _draw_art(self, now: float) -> None:
        if not self.art_layers:
            return
        top_idx, top, born = self.art_layers[-1]
        t = _smoothstep((now - born) / ART_FADE_SECONDS)
        below = self.art_layers[-2][1] if len(self.art_layers) > 1 else None
        if t >= 1 and len(self.art_layers) > 1:
            self.art_layers = self.art_layers[-1:]
        if below is not None:
            if top is None:
                below.set_alpha(int(255 * (1 - t)))
            self.screen.blit(below, self.art_rect)
            _reset_alpha(below)
        if top is not None:
            if t < 1:
                top.set_alpha(int(255 * t))
            self.screen.blit(top, self.art_rect)
            _reset_alpha(top)
        self._blit_layer("veil")
        if self._category_selected() and self.rows:
            self._draw_category_mural(self.rows[self._sel_row()])

    def _category_count_label(self, row: Row) -> str:
        key = "group.n_presets" if row.count == 1 else "group.n_presets_plural"
        return tr(key, count=row.count)

    def _draw_category_mural(self, row: Row) -> None:
        """Category name as the art: kind, title, then preset count. No game picture."""
        ar, s = self.art_rect, self.s
        pad_x = int(72 * s)
        pad_top = int(96 * s)
        max_w = ar.width - pad_x - int(48 * s)
        max_bottom = self.detail_rect.y - int(12 * s)
        kind = tr("header.favorites_kind") if row.group_id == FAVORITES_ID else tr("header.category_kind")
        count = self._text(self._category_count_label(row), self._font(24), MUTED)

        y = ar.y + pad_top
        kind_surf = self._tracked(kind, 16, self.theme.label, tracking=0.28)
        self.screen.blit(kind_surf, (ar.x + pad_x, y))
        y += kind_surf.get_height() + int(14 * s)

        budget = max(40, max_bottom - y - count.get_height() - int(12 * s))
        size = 72
        lines: tuple[str, ...] = ()
        font = self._font(size, bold=True)
        while size >= 48:
            font = self._font(size, bold=True)
            lines = self._wrap(row.text, font, max_w, 2)
            tall = len(lines) * font.get_height() + (len(lines) - 1) * int(2 * s)
            wide = max((font.size(line)[0] for line in lines), default=0)
            if tall <= budget and wide <= max_w:
                break
            size -= 2
        for n, line in enumerate(lines):
            self.screen.blit(self._shadowed(line, font, TEXT), (ar.x + pad_x, y))
            y += font.get_height() + (int(2 * s) if n + 1 < len(lines) else 0)
        self.screen.blit(count, (ar.x + pad_x, y + int(12 * s)))

    # ---------- actions ----------

    def _notify(self, text: str, color=TEXT) -> None:
        self.toast = Toast(text, color, time.monotonic())

    def _on_action(self, action: Action, now: float, *, repeat: bool = False) -> None:
        if self.quit_at is not None:
            return
        if self.mode == "menu":
            self._on_menu_action(action, repeat=repeat)
            return
        if self.mode == "browse":
            if action == Action.MENU:
                self.file_browser = None
                self.mode = "launcher"
                self._sound("close")
            else:
                self._browser_action(action, wrap=not repeat)
            return
        if self.mode == "launcher":
            self._on_picker_action(Action.BACK if action == Action.MENU else action, repeat=repeat)
            return
        if self.mode == "whatsnew":
            if action in (Action.CONFIRM, Action.BACK, Action.MENU):
                self._close_whats_new()
            return
        if self.mode == "update":
            self._on_update_action(Action.BACK if action == Action.MENU else action)
            return
        if self.mode == "help":
            self._on_help_action(Action.BACK if action == Action.MENU else action)
            return
        if action == Action.MENU:
            if self.mode == "list" and not self.blocked:
                self.menu_sel = 0
                self.menu_opened = now
                self.mode = "menu"
                self._sound("open")
            elif self.blocked:
                self.running = False
            else:
                self._on_action(Action.BACK, now, repeat=repeat)
            return
        if action == Action.HELP:
            self.mode = "help"
            self.help_scroll = self.help_view = 0.0
            self.info_opened = now
            self._sound("open")
            return
        if self.blocked:
            if action == Action.CONFIRM:
                if self.launchers and self.launchers.must_pick:
                    self._open_picker()  # several launchers found and none picked yet: reloading can't help
                else:
                    self._reload()
            elif action == Action.BACK:
                self.running = False  # nothing to lose here, so no press-twice guard
            return
        if action == Action.FAVORITE:
            if self.mode == "list" and self.rows and self.rows[self._sel_row()].kind == "preset":
                self._toggle_favorite()
            return
        if self.mode == "search":
            self._on_search_action(Action.BACK if action == Action.MENU else action, now)
            return
        if self.mode == "info":
            self._on_info_action(Action.BACK if action == Action.MENU else action, now)
            return
        if action == Action.UP:
            self._move(-1, wrap=not repeat)
        elif action == Action.DOWN:
            self._move(1, wrap=not repeat)
        elif action == Action.DELETE:
            self._set_filter(self.filter[:-1])
        elif action == Action.PAGE_UP:
            self._move(-8, wrap=not repeat)
        elif action == Action.PAGE_DOWN:
            self._move(8, wrap=not repeat)
        elif action == Action.HOME:
            self._move(-self._sel_row(), wrap=False)
        elif action == Action.END:
            self._move(len(self.rows), wrap=False)
        elif action == Action.LEFT:
            selected = self._sel_row()
            if self.rows and self.rows[selected].kind != "header":
                header = max((i for i in range(selected, -1, -1) if self.rows[i].kind == "header"), default=None)
                if header is not None:
                    self._select_row(header)
                else:
                    self._jump_section(-1)
            else:
                self._jump_section(-1)
        elif action == Action.PREV_SECTION:
            self._jump_section(-1)
        elif action in (Action.RIGHT, Action.NEXT_SECTION):
            self._jump_section(1)
        elif action == Action.CONFIRM:
            row = self._sel_row()
            if self.rows and self.rows[row].kind == "header":
                self._toggle_section(row)
            else:
                self._launch_selected()
        elif action == Action.ALT:
            row = self._sel_row()
            if self.rows and self.rows[row].kind == "header":
                self._bulk_fold_from_alt()
            elif self.rows and self.rows[row].kind == "preset":
                self._open_info(now)
        elif action == Action.SEARCH:
            self._open_search(now)
        elif action == Action.BACK:
            if self.filter:
                self._set_filter("")
            else:
                self._jump_to_last_played()  # B, or a bare Ctrl. Escape opens the menu instead.
            return

    def _on_menu_action(self, action: Action, *, repeat: bool = False) -> None:
        if action in (Action.MENU, Action.BACK):
            self._close_overlay()
        elif action == Action.UP:
            self._move_menu(-1, repeat=repeat)
        elif action == Action.DOWN:
            self._move_menu(1, repeat=repeat)
        elif action == Action.LEFT:
            self._set_menu_option(-1)
        elif action == Action.RIGHT:
            self._set_menu_option(1)
        elif action == Action.HELP:
            self.mode = "help"
            self.help_scroll = self.help_view = 0.0
            self.info_opened = time.monotonic()
            self._sound("open")
        elif action == Action.CONFIRM:
            self._menu_pick(self.menu_sel)

    def _move_menu(self, delta: int, *, repeat: bool = False) -> None:
        selected = self._step_index(self.menu_sel, len(self._menu_items()), delta, wrap=not repeat)
        if selected != self.menu_sel:
            self.menu_sel = selected
            self._sound("move")

    def _menu_items(self) -> list[tuple[str, str]]:
        items = [
            ("back", tr("menu.back")),
            ("refresh", tr("menu.refresh")),
            ("music", tr("menu.music")),
            ("sounds", tr("menu.sounds")),
            ("recent", tr("menu.recent")),
        ]
        items.append(("colors", tr("menu.colors")))
        items.append(("language", tr("menu.language")))
        if self.launchers:
            items.append(("launcher", tr("menu.launcher")))
        items.extend((("help", tr("menu.help")), ("quit", tr("menu.quit"))))
        return items

    def _cycle_color_palette(self, delta: int) -> None:
        keys = [key for key, _ in PALETTES]
        current = self._current_palette_key()
        index = keys.index(current) if current in keys else 0
        self._apply_palette(keys[(index + delta) % len(keys)])
        self._sound("open")

    def _cycle_language(self, delta: int) -> None:
        codes = [code for code, _ in LANGUAGES]
        cur = current_language()
        i = codes.index(cur) if cur in codes else 0
        code = codes[(i + delta) % len(codes)]
        self.state.set_language(code)
        set_language(code)
        self._rebuild_rows()
        self._sound("open")

    def _set_menu_option(self, delta: int = 1) -> None:
        key = self._menu_items()[self.menu_sel][0]
        if key == "music":
            self._set_music(not self.state.music)
        elif key == "sounds":
            self.state.set_menu_sounds(not self.state.menu_sounds)
            self._sound("open")
        elif key == "recent":
            self.state.set_recent_group(not self.state.recent_group)
            self._rebuild_rows()
            self._sound("open")
        elif key == "colors":
            self._cycle_color_palette(delta)
        elif key == "language":
            self._cycle_language(delta)

    def _menu_pick(self, index: int) -> None:
        key = self._menu_items()[index][0]
        if key == "back":
            self._close_overlay()
        elif key == "refresh":
            if not self.reload:
                return
            self.menu_status = ""
            self._reload()
        elif key == "music":
            self._set_music(not self.state.music)
        elif key == "sounds":
            self.state.set_menu_sounds(not self.state.menu_sounds)
            self._sound("open")
        elif key == "recent":
            self.state.set_recent_group(not self.state.recent_group)
            self._rebuild_rows()
            self._sound("open")
        elif key == "colors":
            self._cycle_color_palette(1)
        elif key == "language":
            self._cycle_language(1)
        elif key == "launcher":
            self._open_picker()
        elif key == "help":
            self.mode = "help"
            self.help_scroll = self.help_view = 0.0
            self.info_opened = time.monotonic()
            self._sound("open")
        elif key == "quit":
            if self._sound("quit"):
                self.quit_at = time.monotonic() + 0.7
            else:
                self.running = False

    def _button_name(self, button: str) -> str:
        return BUTTON_NAMES[self.input.family].get(button, button)

    def _open_search(self, now: float) -> None:
        self.mode = "search"
        self.osk = [1, 0]
        self.osk_moved = now
        self._sound("open")

    def _open_info(self, now: float) -> None:
        self.mode = "info"
        self.info_scroll = self.info_view = 0.0
        self.info_scrolls = [0.0] * INFO_TAB_COUNT
        self.info_tab = 0
        self.info_opened = now
        self._sound("open")

    def _on_help_action(self, action: Action) -> None:
        if action in (Action.UP, Action.DOWN) and self.input.left_y:
            return  # analog scrolling is handled smoothly in tick()
        if action in (Action.UP, Action.DOWN):
            step = self._help_line_h() * (-3 if action == Action.UP else 3)
            self.help_scroll = max(0, min(self._help_max_scroll(), self.help_scroll + step))
        elif action in (Action.PAGE_UP, Action.PAGE_DOWN):
            _, body, _, _, _ = self._help_metrics()
            page = max(self._help_line_h(), body.height - 2 * self._help_line_h())
            self.help_scroll = max(0, min(self._help_max_scroll(), self.help_scroll + (-page if action == Action.PAGE_UP else page)))
        elif action in (Action.SEARCH, Action.ISSUES):
            webbrowser.open(ISSUE_URL)
        elif action in (Action.BACK, Action.ALT, Action.HELP):
            self._close_overlay()

    def _close_overlay(self) -> None:
        self.mode = "list"
        self._sound("close")

    def _arm_quit(self, now: float, button: str) -> None:
        if now < self.quit_armed_until:
            self.running = False
        else:
            self.quit_armed_until = now + QUIT_CONFIRM_SECONDS
            self._notify(tr("toast.quit_again", button=button), self.theme.label)
            self._sound("open")

    def _on_info_action(self, action: Action, now: float) -> None:
        page = max(1, self._info_visible_lines() - 2)
        steps = {Action.UP: -3, Action.DOWN: 3, Action.PAGE_UP: -page, Action.PAGE_DOWN: page}
        if action in (Action.UP, Action.DOWN) and self.input.left_y:
            return  # the left stick scrolls analog in tick(); its stepped UP/DOWN would stutter on top
        if action in steps:
            self.info_scroll = max(0.0, min(self._info_max_scroll(), self.info_scroll + steps[action]))
        elif action in (Action.LEFT, Action.RIGHT, Action.PREV_SECTION, Action.NEXT_SECTION):
            step = -1 if action in (Action.LEFT, Action.PREV_SECTION) else 1
            tabs = self._info_tabs()
            self._set_info_tab(tabs[(tabs.index(self.info_tab) + step) % len(tabs)])
        elif action == Action.CONFIRM:
            self.mode = "list"
            self._launch_selected()
        elif action in (Action.BACK, Action.ALT):
            self._close_overlay()

    def _set_info_tab(self, tab: int) -> None:
        if tab == self.info_tab:
            return
        self.info_scrolls[self.info_tab] = self.info_scroll
        self.info_tab = tab
        self.info_scroll = self.info_view = self.info_scrolls[tab]
        self._sound("move")

    # ---------- mouse ----------

    def _mouse_on(self) -> None:
        if not self.mouse_on:
            self.mouse_on = True
            pygame.mouse.set_visible(True)

    def _mouse_off(self) -> None:
        """The pad or keyboard took over: a pointer parked over the art is just clutter."""
        self.mouse_on = False
        self.mouse_travel = 0
        pygame.mouse.set_visible(False)

    def _hit_at(self, pos: tuple[int, int]) -> Hit | None:
        return next((h for h in reversed(self.hits) if h.rect.collidepoint(pos)), None)

    def _act(self, action: Action) -> Callable[[], None]:
        return lambda: self._on_action(action, time.monotonic())

    def _on_mouse(self, event: pygame.event.Event, now: float) -> None:
        t = event.type
        if self.dpi != 1.0:
            if hasattr(event, "pos"):
                event.pos = (int(event.pos[0] * self.dpi), int(event.pos[1] * self.dpi))
            if hasattr(event, "rel"):
                event.rel = (event.rel[0] * self.dpi, event.rel[1] * self.dpi)
        if hasattr(event, "pos"):
            self.mouse_pos = event.pos
        if t == pygame.MOUSEMOTION:
            if not self.mouse_on:
                # Windows nudges the pointer on focus changes; only a deliberate move brings it back.
                self.mouse_travel += abs(event.rel[0]) + abs(event.rel[1])
                if self.mouse_travel < 12 * self.s:
                    return
                self._mouse_on()
            if self.drag and not event.buttons[0]:
                self.drag = None  # the release happened outside the window or while it lost focus
            if self.drag:
                self._drag_to(event.pos[1])
                return
            hit = self._hit_at(event.pos)
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_HAND if hit else pygame.SYSTEM_CURSOR_ARROW)
            if hit and hit.hover:
                hit.hover()
        elif t == pygame.MOUSEWHEEL:
            self._mouse_on()
            notches = event.y if event.flipped else -event.y
            if self.blocked or not notches:
                return
            if self.mode == "list" and self.rows:
                self.free_scroll = self._target_scroll() + notches * 3 * self.preset_h
                self.free_scroll = self._target_scroll()  # clamped, so scrolling back from an end responds at once
            elif self.mode == "info":
                self.info_scroll = max(0.0, min(self._info_max_scroll(), self.info_scroll + 3 * notches))
            elif self.mode == "help":
                self.help_scroll = max(0, min(self._help_max_scroll(), self.help_scroll + 3 * self._help_line_h() * notches))
            elif self.mode == "browse" and self.file_browser:
                self._browser_action(Action.UP if notches < 0 else Action.DOWN, wrap=False)
        elif t == pygame.MOUSEBUTTONDOWN:
            self._mouse_on()
            if event.button == pygame.BUTTON_LEFT:
                if hit := self._hit_at(event.pos):
                    hit.click()
            elif event.button in (pygame.BUTTON_RIGHT, pygame.BUTTON_X1):
                self._on_action(Action.BACK, now)
        elif t == pygame.MOUSEBUTTONUP and event.button == pygame.BUTTON_LEFT:
            self.drag = None

    def _scrollbar(self, kind: str, track: pygame.Rect, thumb_h: int, max_scroll: float) -> None:
        self.scrollbars[kind] = (track, thumb_h, max_scroll)
        # The bar is a few pixels wide; give the pointer a fair target, mostly outward so rows keep their clicks.
        area = pygame.Rect(track.x - int(6 * self.s), track.y, track.width + int(22 * self.s), track.height)
        self.hits.append(Hit(area, lambda: self._start_drag(kind)))

    def _scroll_value(self, kind: str) -> float:
        if kind == "list":
            return self.scroll
        if kind == "browser":
            return float(self.browser_scroll)
        return self.help_view if kind == "help" else self.info_view

    def _start_drag(self, kind: str) -> None:
        track, thumb_h, max_scroll = self.scrollbars[kind]
        y = self.mouse_pos[1]
        thumb_y = track.y + (track.height - thumb_h) * min(1.0, self._scroll_value(kind) / max_scroll)
        # On the thumb: keep the grab point. On the track: jump so the thumb centres under the pointer.
        grab = int(y - thumb_y) if thumb_y <= y <= thumb_y + thumb_h else thumb_h // 2
        self.drag = (kind, grab)
        self._drag_to(y)

    def _drag_to(self, y: int) -> None:
        kind, grab = self.drag
        if kind not in self.scrollbars:  # the sheet closed or the list emptied mid-drag
            self.drag = None
            return
        track, thumb_h, max_scroll = self.scrollbars[kind]
        frac = (y - grab - track.y) / max(1, track.height - thumb_h)
        value = max(0.0, min(1.0, frac)) * max_scroll
        if kind == "list":
            self.free_scroll = self.scroll = value
        elif kind == "browser":
            self.browser_scroll = int(round(value))
        elif kind == "help":
            self.help_scroll = self.help_view = value
        else:
            self.info_scroll = self.info_view = value

    def _click_row(self, row: int) -> None:
        """First click selects (title art and music follow), a click on the selected preset plays it."""
        if self.rows[row].kind == "header":
            if row == self._sel_row():
                self._toggle_section(row)
            else:
                self._select_row(row)
            return
        if row == self._sel_row():
            self._launch_selected()
        else:
            self._select_row(row)

    def _osk_hover(self, r: int, c: int) -> None:
        if self.osk != [r, c]:
            self.osk = [r, c]
            self.osk_moved = time.monotonic()
            self._sound("move")

    def _osk_click(self, r: int, c: int) -> None:
        self.osk = [r, c]
        self._osk_press(OSK_ROWS[r][c])

    def _on_search_action(self, action: Action, now: float) -> None:
        r, c = self.osk
        if not self.input.pad_mode and action in (Action.UP, Action.DOWN, Action.PAGE_UP, Action.PAGE_DOWN):
            step = {Action.UP: -1, Action.DOWN: 1, Action.PAGE_UP: -8, Action.PAGE_DOWN: 8}[action]
            self._move(step, wrap=abs(step) == 1)
            return
        if action in (Action.UP, Action.DOWN, Action.LEFT, Action.RIGHT):
            if action in (Action.UP, Action.DOWN):
                nr = (r + (-1 if action == Action.UP else 1)) % len(OSK_ROWS)
                c = round(c * (len(OSK_ROWS[nr]) - 1) / max(1, len(OSK_ROWS[r]) - 1))
                r = nr
            else:
                c = (c + (-1 if action == Action.LEFT else 1)) % len(OSK_ROWS[r])
            self.osk = [r, min(c, len(OSK_ROWS[r]) - 1)]
            self.osk_moved = now
            self._sound("move")
        elif action == Action.CONFIRM:
            self._osk_press(OSK_ROWS[r][c])
        elif action in (Action.ALT, Action.PREV_SECTION):
            self._set_filter(self.filter[:-1])
        elif action == Action.NEXT_SECTION:
            self._set_filter(self.filter + " ")
        elif action == Action.SEARCH:
            self._close_overlay()
        elif action == Action.BACK:
            self._set_filter("")
            self._close_overlay()
        elif action == Action.DELETE:
            self._set_filter(self.filter[:-1])

    def _osk_press(self, key: str) -> None:
        if key == "SPACE":
            self._set_filter(self.filter + " ")
        elif key == "DELETE":
            self._set_filter(self.filter[:-1])
        elif key == "CLEAR":
            self._set_filter("")
        elif key == "DONE":
            self._close_overlay()
            return
        else:
            self._set_filter(self.filter + key.lower())
        self._sound("move")

    def _ctrl_keys(self) -> set[int]:
        held = getattr(self, "_ctrl_held", None)
        if held is None:
            held = self._ctrl_held = set()
            self._ctrl_tap = False
        return held

    def _release_ctrl(self, key: int, *, jump: bool = True) -> None:
        """A bare Ctrl jumps to the last game. Ctrl+Backspace is a chord, so it does not."""
        held = self._ctrl_keys()
        held.discard(key)
        tap = jump and getattr(self, "_ctrl_tap", False) and not held and self.mode == "list" and not self.blocked
        if not held:
            self._ctrl_tap = False
        if not tap:
            return
        name = getattr(self.state, "last_played", None)
        if self.filter and name:
            idx = next((i for i, preset in enumerate(self.opts.presets) if preset.name == name), None)
            visible = any(row.kind == "preset" and row.preset == idx for row in self.rows)
            if idx is not None and not visible:
                self._set_filter("")
        self._jump_to_last_played()

    def _on_key(self, event: pygame.event.Event) -> bool:
        """Keyboard-only behaviour that does not map onto pad actions. Returns True if consumed."""
        if event.key in (pygame.K_LCTRL, pygame.K_RCTRL):
            held = self._ctrl_keys()
            if not held:
                self._ctrl_tap = self.mode == "list" and not self.blocked
            held.add(event.key)
            return True
        self._ctrl_tap = False
        if event.key == pygame.K_ESCAPE and self.mode == "list" and self.filter and not self.blocked:
            self._set_filter("")  # Escape clears the search before it reaches the menu.
            return True
        if event.key == pygame.K_BACKSPACE and getattr(event, "mod", 0) & pygame.KMOD_CTRL:
            if self.mode in ("list", "search") and not self.blocked:
                self._delete_filter_word()
                return True
        if event.key == pygame.K_BACKSPACE:
            return self.mode not in ("list", "search", "info", "help")
        if self.mode == "search" and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._close_overlay()
            return True
        return False

    def _on_text(self, text: str, now: float) -> None:
        if self.mode not in ("list", "search"):
            return
        if not text.isprintable() or (not self.filter and text.isspace()):
            return
        self._set_filter(self.filter + text.lower())

    # ---------- launching ----------

    def _launch_selected(self) -> None:
        if not self.rows:
            return
        preset = self.opts.presets[self.current]
        cmd = self.commands[self.current]
        if not cmd.ok:
            self._notify(str(cmd.issues[0]), ERROR)
            self._sound("error")
            return
        if error := unpack(preset):
            self._notify(error, ERROR)
            self._sound("error")
            return

        self._sound("confirm")
        if self.music:
            self.music.stop(int(LAUNCH_WIPE_SECONDS * 1000))
        self._play_wipe(preset.name)
        self._warm_allowed.clear()
        try:
            proc = spawn(cmd.argv, cmd.cwd, cmd.env, preset.name, cmd.display())
        except OSError as exc:
            self._warm_allowed.set()
            self._notify(tr("toast.could_not_start", exc=exc), ERROR)
            self._sound("error")
            return
        self.state.record(preset.name)
        self._audio_down()
        self.input.suspend()
        # The engine inherits foreground rights from the spawn above. Keep our loading frame up until it has a
        # window of its own, or a large WAD would show the desktop for as long as it takes to load.
        self._hold_loading(preset.name, proc)
        self._close_window()
        code, elapsed = proc.wait()
        if needs_extract_retry(cmd.argv, cmd.env, proc.output, code, elapsed):
            # No FUSE on this system: run the AppImage by unpacking it instead, and say so in the log.
            retry = {**cmd.env, "APPIMAGE_EXTRACT_AND_RUN": "1"}
            try:
                proc = spawn(cmd.argv, cmd.cwd, retry, preset.name + " (retry without FUSE)", cmd.display())
                code, elapsed = proc.wait()
            except OSError:
                pass
        self._warm_allowed.set()

        # Recreate our window first: audio and pads can take a moment, and every one of those milliseconds is
        # desktop showing through after the engine has already torn its own window down.
        pygame.display.init()
        pygame.display.set_caption("CouchDoom")
        self._open_window()
        self.hidden = False  # a fresh window; any minimize event belonged to the old one
        self._audio_up()
        self.input.resume()
        pygame.event.clear()
        self.input.reset()
        self.ignore_until = time.monotonic() + INPUT_COOLDOWN
        self.scroll = self._target_scroll()
        self.bar_y = self.row_y[self._sel_row()]
        if closed_early(code, elapsed):
            why = last_line(proc.output)
            if why:
                why_low = why.lower()
                # Keep it short for the toast; full output is in couch-doom.log
                if why_low.startswith("[mvk-") or "vkinstance" in why_low or "destroying" in why_low and "vulkan" in why_low:
                    self._notify(tr("toast.closed_log", name=preset.name, code=code), ERROR)
                else:
                    if len(why) > 60:
                        why = why[:57] + "..."
                    self._notify(tr("toast.closed_why", name=preset.name, code=code, why=why), ERROR)
            else:
                self._notify(tr("toast.closed_log", name=preset.name, code=code), ERROR)
        else:
            self._notify(tr("toast.back_from", name=preset.name), MUTED)

    def _play_wipe(self, name: str) -> None:
        """The list sinks into shadow while the game's art zooms out of its panel to fill the window, then the
        loading text fades in. The zoom waits for the full-window art (a few frames, usually; the shadow starts
        at once) and begins exactly where the panel shows that art, so the two line up."""
        clock = pygame.time.Clock()
        start = time.monotonic()
        poll = self._start_loading_backdrop()
        self._draw(start)
        ui_shot = self.screen.copy()
        full = self.screen.get_rect()
        art = final = path = None
        art_at = dim = 0.0
        while True:
            now = time.monotonic()
            pygame.event.pump()
            if art is None and ((ready := poll()) is not None or now - start >= LAUNCH_ART_WAIT_SECONDS):
                backdrop, dims, soft = ready or (self._plain_backdrop(), None, None)
                # Zoom the feathered copy, so the art has no hard edge against the list; _loading_screen writes
                # its text onto `backdrop`.
                art, art_at = soft or backdrop.copy(), now
                final = self._loading_screen(name, backdrop)[0]
                path = self._zoom_path(dims)
            t = (now - art_at) / LAUNCH_WIPE_SECONDS if art is not None else 0.0
            if t >= 1:
                break
            # The art fades in over the panel first, holding still where the two line up: a push already under
            # way would show both. Then a quick push that settles long, like a camera, not a slide.
            grow = _ease_out_expo((t - 0.12) / 0.68)
            dim = max(dim, grow, 0.6 * _smoothstep((now - start) / LAUNCH_WIPE_SECONDS))
            self.screen.blit(ui_shot, (0, 0))
            k = 255 - int(215 * dim)
            self.screen.fill((k, k, k), special_flags=pygame.BLEND_MULT)
            if art is not None:
                # Without art there's nothing to zoom, so the plain backdrop opens out from the panel instead.
                a, b = self.art_rect, full
                clip = full if path else pygame.Rect(
                    round(_lerp(a.x, b.x, grow)), round(_lerp(a.y, b.y, grow)),
                    round(_lerp(a.w, b.w, grow)), round(_lerp(a.h, b.h, grow)))
                self._blit_zoomed(art, path, grow, clip, _smoothstep(t / 0.12))
            if final is not None and t > 0.7:
                final.set_alpha(int(255 * _smoothstep((t - 0.7) / 0.3)))
                self.screen.blit(final, (0, 0))
                _reset_alpha(final)
            self._flip()
            clock.tick(self._frame_cap())
        self.screen.blit(final, (0, 0))
        self._flip()

    def _zoom_path(self, dims: tuple | None) -> tuple | None:
        """The launch zoom's ends: art placed as in the panel, then as across the window, each as (scale, x, y);
        None for a backdrop without art, which just opens out from the panel."""
        if dims is None:
            return None
        s0, (px, py) = self._panel_fit(*dims)
        s1, (wx, wy) = self._window_cover(*dims)
        return (s0, self.art_rect.x + px, self.art_rect.y + py), (s1, wx, wy)

    def _blit_zoomed(self, art: pygame.Surface, path: tuple | None, grow: float, clip: pygame.Rect, alpha: float) -> None:
        """Draw the full-window backdrop `grow` of the way along the zoom, inside `clip`. Only the visible part
        is scaled, nearest-neighbour: this runs every frame."""
        if path is None:
            k, x, y = 1.0, 0.0, 0.0
        else:
            (s0, x0, y0), (s1, x1, y1) = path
            # A camera move, not two lerps: zoom about the one point the panel view and the window view share,
            # at a constant rate in scale (geometric), so nothing slides sideways and the push reads as even.
            ratio = s1 / s0
            s = s0 * ratio ** grow
            if abs(ratio - 1) < 1e-6:
                ox, oy = _lerp(x0, x1, grow), _lerp(y0, y1, grow)
            else:
                px, py = (x1 - ratio * x0) / (1 - ratio), (y1 - ratio * y0) / (1 - ratio)
                ox, oy = px + (x0 - px) * s / s0, py + (y0 - py) * s / s0
            k = s / s1
            x, y = ox - k * x1, oy - k * y1
        src = pygame.Rect(math.floor((clip.x - x) / k), math.floor((clip.y - y) / k),
                          math.ceil(clip.w / k) + 2, math.ceil(clip.h / k) + 2).clip(art.get_rect())
        if src.w <= 0 or src.h <= 0:
            return
        if isinstance(self.screen, canvas.Canvas):
            dest = pygame.Rect(round(x + src.x * k), round(y + src.y * k), max(1, round(src.w * k)), max(1, round(src.h * k)))
            self.screen.set_clip(clip)
            self.screen.blit_scaled(art, src, dest, alpha)
            self.screen.set_clip(None)
            return
        part = art.subsurface(src)
        if k != 1.0:
            part = pygame.transform.scale(part, (max(1, round(src.w * k)), max(1, round(src.h * k))))
        if alpha < 1:
            part.set_alpha(int(255 * alpha))
        self.screen.set_clip(clip)
        self.screen.blit(part, (round(x + src.x * k), round(y + src.y * k)))
        self.screen.set_clip(None)
        if part.get_parent() is art:
            _reset_alpha(part)

    def _hold_loading(self, name: str, launched: log.Launched) -> None:
        """Keep the LOADING screen up until the engine has a window, so a big WAD does not show the desktop.

        Windows, X11/XWayland and macOS. A native-Wayland game cannot be seen, so covering stops once the engine
        is known to be using Wayland; a pure Wayland session without XWayland releases the display immediately.
        """
        if not handover.available():
            return
        try:
            own = pygame.display.get_wm_info().get("window")
        except pygame.error:
            own = None
        started = time.monotonic()

        def ready() -> bool:
            if handover.engine_uses_wayland(launched.proc.pid):
                return True  # native Wayland hides other apps' windows: stop covering and let the compositor show it
            return handover.engine_window_visible(launched.proc.pid, own)

        def frame() -> None:
            pygame.event.pump()  # keep Windows from calling the window unresponsive during a long load
            self._draw_loading(name, time.monotonic() - started)

        hz = self.refresh_hz
        # The cover is a duration. A 144 Hz display paints more frames in that same span, it does not lift sooner.
        reason = handover.hold(launched.proc.poll, ready, frame, HANDOVER_TIMEOUT_SECONDS,
                               grace_frames=max(1, round(HANDOVER_GRACE_SECONDS * hz)),
                               frame_seconds=1 / hz)
        if reason == "timeout":
            log.write("handover timeout", f"{name}: no engine window after {HANDOVER_TIMEOUT_SECONDS:.0f} seconds")

    def _loading_backdrop(self, index: int, bg: pygame.Surface) -> tuple[pygame.Surface, tuple | None]:
        """The game's title art across the whole window, dissolving into the theme at the bottom, and the art's
        (width, height, aspect) for the launch transition (None without art). No text, so it can be built off
        the main thread while the transition starts: HD art takes tens of milliseconds."""
        size = (self.w, self.h)
        surf = bg.copy()
        try:
            art = _load_extras(self.opts.presets[index])[0]
        except Exception:
            art = None
        decoded = self._art_image(art) if art is not None else None
        if decoded is None:
            return surf, None
        img, aspect = decoded
        w, h = img.get_size()
        scale, at = self._window_cover(w, h, aspect)
        cover = (math.ceil(w * scale), math.ceil(h * aspect * scale))
        scaled = pygame.transform.scale(img, cover) if w <= 640 else pygame.transform.smoothscale(img, cover)
        surf.blit(scaled, at)

        def scrim(u: float, v: float) -> float:
            return max(0.15, 0.97 * _smoothstep((v - 0.42) / 0.5), 0.55 * (1 - _smoothstep(u / 0.6)) * _smoothstep((v - 0.25) / 0.5))

        surf.blit(self._bg_overlay(bg, pygame.Rect((0, 0), size), self._alpha_mask(size, scrim)), (0, 0))
        return surf, (w, h, aspect)

    def _plain_backdrop(self) -> pygame.Surface:
        return self._layers_for(self.theme)["bg"][0].copy()

    def _start_loading_backdrop(self) -> Callable[[], tuple[pygame.Surface, tuple | None, pygame.Surface | None] | None]:
        """Build the backdrop on a thread; the returned poll gives it, the art's dimensions and a copy feathered
        at the left and bottom for the launch zoom (both None without art), or None until they're ready."""
        bg = self._layers_for(self.theme)["bg"][0]
        index = self.current
        done: list[tuple[pygame.Surface, tuple | None, pygame.Surface | None]] = []

        def work() -> None:
            try:
                surf, dims = self._loading_backdrop(index, bg)
                soft = None
                if dims is not None:
                    soft = surf.convert_alpha()
                    feather = self._alpha_mask(soft.get_size(), lambda u, v: _smoothstep(u / 0.12) * _smoothstep((1 - v) / 0.15))
                    soft.blit(feather, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
                done.append((surf, dims, soft))
            except Exception:
                done.append((bg.copy(), None, None))

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        return lambda: done[0] if done else None

    def _loading_screen(self, name: str, backdrop: pygame.Surface | None = None) -> tuple[pygame.Surface, tuple[int, int]]:
        """The backdrop with the game's name over it, plus where the ticking dots go. Built once per launch:
        the handover redraws it every frame."""
        key = (self.current, name, self.w, self.h, self.theme.key)
        if self._loading_cache and self._loading_cache[0] == key:
            return self._loading_cache[1]
        s, m = self.s, self.margin
        surf = backdrop if backdrop is not None else self._loading_backdrop(self.current, self._layers_for(self.theme)["bg"][0])[0]
        room = self.w - 2 * m
        for pt in range(96, 39, -8):
            font = self._font(pt, bold=True)
            if font.size(name)[0] <= room:
                break
        title = self._shadowed(name, font, TEXT)
        word = self._tracked(tr("loading.label"), 22, self.theme.label, tracking=0.3)
        title_y = self.h - int(m * 1.4) - title.get_height()
        word_y = title_y - word.get_height() + int(4 * s)
        pygame.draw.rect(surf, self.theme.accent, (m, word_y - int(24 * s), int(56 * s), max(2, int(3 * s))))
        surf.blit(word, (m, word_y))
        surf.blit(title, (m - int(4 * s), title_y))
        result = surf, (m + word.get_width() + int(4 * s), word_y)
        self._loading_cache = (key, result)
        return result

    def _draw_loading(self, name: str, elapsed: float) -> None:
        """The wipe's end frame, kept alive with a ticking ellipsis while the engine starts."""
        surf, dots_at = self._loading_screen(name)
        self.screen.blit(surf, (0, 0))
        dots = "." * (int(elapsed * 2) % 4)
        if dots:
            self.screen.blit(self._tracked(dots, 22, self.theme.label, tracking=0.3), dots_at)
        self._flip()

    # ---------- text helpers ----------

    def _text(self, text: str, font: pygame.font.Font, color) -> pygame.Surface:
        key = (text, id(font), tuple(color))
        surf = self._text_cache.get(key)
        if surf is None:
            if len(self._text_cache) > 3000:
                self._text_cache.clear()
            surf = font.render(text, True, color)
            self._text_cache[key] = surf
        return surf

    def _star(self, color) -> pygame.Surface:
        key = ("star", tuple(color), self.s)
        surf = self._text_cache.get(key)
        if surf is None:
            d = max(8, int(18 * self.s))

            def p(big: pygame.Surface, k: int) -> None:
                c, r_out = d * k / 2, d * k / 2
                pts = [
                    (c + (r_out if j % 2 == 0 else r_out * 0.42) * math.sin(j * math.pi / 5),
                     c - (r_out if j % 2 == 0 else r_out * 0.42) * math.cos(j * math.pi / 5) + r_out * 0.08)
                    for j in range(10)
                ]
                pygame.draw.polygon(big, color, pts)

            surf = self._text_cache[key] = draw.paint(d, d, p)
        return surf

    def _browser_icon(self, kind: str, color) -> pygame.Surface:
        """Line icon for a browser row: "folder", "drive", "file", or "launcher" (a solid file)."""
        key = ("icon", kind, tuple(color), self.s)
        surf = self._text_cache.get(key)
        if surf is None:
            d = max(10, int(22 * self.s))
            stroke = max(1.0, 1.7 * self.s)

            def p(big: pygame.Surface, k: int) -> None:
                def pts(*uv: tuple[float, float]) -> list[tuple[float, float]]:
                    return [(u * d * k, v * d * k) for u, v in uv]
                w = max(1, int(stroke * k))
                if kind == "folder":
                    pygame.draw.lines(big, color, True, pts((.06, .86), (.06, .16), (.38, .16), (.48, .3), (.94, .3), (.94, .86)), w)
                elif kind == "drive":
                    draw.rr_on(big, pygame.Rect(*(int(c * d * k) for c in (.04, .28, .92, .5))), color, (3 * k,) * 4)
                    draw.rr_on(big, pygame.Rect(*(int(c * d * k) + w for c in (.04, .28)), *(int(c * d * k) - 2 * w for c in (.92, .5))),
                               (0, 0, 0, 0), (2 * k,) * 4)
                    pygame.draw.circle(big, color, (int(.76 * d * k), int(.53 * d * k)), max(1, int(.07 * d * k)))
                else:
                    page = pts((.2, .06), (.6, .06), (.82, .28), (.82, .94), (.2, .94))
                    if kind == "launcher":
                        pygame.draw.polygon(big, color, page)
                    else:
                        pygame.draw.lines(big, color, True, page, w)
                        pygame.draw.lines(big, color, False, pts((.6, .06), (.6, .28), (.82, .28)), w)

            surf = self._text_cache[key] = draw.paint(d, d, p)
        return surf

    def _tracked(self, text: str, size: float, color, bold: bool = True, tracking: float = 0.14) -> pygame.Surface:
        """Uppercase label with letter spacing."""
        key = ("trk", text, size, tuple(color), bold, tracking, self.s)
        surf = self._text_cache.get(key)
        if surf is None:
            font = self._font(size, bold=bold)
            chars = [font.render(ch, True, color) for ch in text.upper()]
            gap = size * self.s * tracking
            width = int(sum(c.get_width() for c in chars) + gap * max(0, len(chars) - 1)) + 1
            surf = pygame.Surface((max(1, width), font.get_height()), pygame.SRCALPHA)
            x = 0.0
            for c in chars:
                surf.blit(c, (int(x), 0))
                x += c.get_width() + gap
            self._text_cache[key] = surf
        return surf

    def _text_top(self, font: pygame.font.Font, cy: float) -> int:
        """Top y that puts the middle of the cap height on cy; the line box adds descender space below."""
        cap = font.metrics("H")[0][3]
        return round(cy - font.get_ascent() + cap / 2)

    def _shadowed(self, text: str, font: pygame.font.Font, color) -> pygame.Surface:
        key = ("shd", text, id(font), tuple(color))
        surf = self._text_cache.get(key)
        if surf is None:
            fg = font.render(text, True, color)
            sh = font.render(text, True, (0, 0, 0))
            sh.set_alpha(150)
            off = max(1, int(3 * self.s))
            surf = pygame.Surface((fg.get_width() + off, fg.get_height() + off), pygame.SRCALPHA)
            surf.blit(sh, (off, off))
            surf.blit(fg, (0, 0))
            self._text_cache[key] = surf
        return surf

    @staticmethod
    @lru_cache(maxsize=512)
    def _fit(text: str, font: pygame.font.Font, max_w: int) -> str:
        width = font.size(text)[0]
        if width <= max_w:
            return text
        length = min(len(text), max(0, int(len(text) * max_w / width)))
        while length:
            candidate = text[:length].rstrip() + "…"
            candidate_width = font.size(candidate)[0]
            if candidate_width <= max_w:
                return candidate
            shorter = int(length * max_w / candidate_width)
            length = min(length - 1, shorter)
        return "…"

    @staticmethod
    @lru_cache(maxsize=64)
    def _fit_start(text: str, font: pygame.font.Font, max_w: int) -> str:
        """Like _fit, but drops the start: a path's last folders are the ones that say where you are."""
        if font.size(text)[0] <= max_w:
            return text
        for start in range(1, len(text)):
            candidate = "…" + text[start:]
            if font.size(candidate)[0] <= max_w:
                return candidate
        return "…"

    @staticmethod
    @lru_cache(maxsize=512)
    def _wrap(text: str, font: pygame.font.Font, max_w: int, max_lines: int) -> tuple[str, ...]:
        # A tuple, because lru_cache hands every caller the same object.
        lines, line = [], ""
        for word in text.split():
            trial = f"{line} {word}".strip()
            if font.size(trial)[0] <= max_w:
                line = trial
            else:
                if line:
                    lines.append(line)
                    if len(lines) == max_lines:
                        lines[-1] = App._fit(lines[-1] + " …", font, max_w)
                        return tuple(lines)
                line = word
        if line:
            lines.append(line)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = App._fit(lines[-1] + " …", font, max_w)
        return tuple(lines)

    def _wrap_items(self, items: list[str], font: pygame.font.Font, max_w: int, max_lines: int) -> list[str]:
        """Join items with separators across lines; the last line reports what didn't fit."""
        sep = "   ·   "
        lines: list[str] = []
        line = ""
        for i, item in enumerate(items):
            trial = f"{line}{sep}{item}" if line else item
            if font.size(trial)[0] <= max_w:
                line = trial
                continue
            if len(lines) + 1 == max_lines:
                rest = len(items) - i
                more = sep + tr("tag.n_more", count=rest)
                while line and font.size(line + more)[0] > max_w:
                    line = line.rsplit(sep, 1)[0] if sep in line else ""
                    rest += 1
                    more = sep + tr("tag.n_more", count=rest)
                lines.append(line + more if line else tr("tag.n_more", count=rest))
                return lines
            lines.append(line)
            line = self._fit(item, font, max_w)
        if line:
            lines.append(line)
        return lines

    # ---------- drawing ----------

    def _draw(self, now: float) -> None:
        self.hits = []
        self.scrollbars = {}
        self.glyphs.family = self.input.family
        self._update_theme(now)
        self._blit_layer("bg")
        self._draw_art(now)
        self._draw_header()
        if self.blocked:
            self._draw_notice()
        else:
            self._draw_list(now)
            self._draw_detail(now)
        self._draw_footer()
        if self.mode == "search":
            if self.input.pad_mode:  # on a keyboard the header's filter field is all typing needs
                self._draw_osk(now)
        elif self.mode == "menu":
            self._draw_menu(now)
        elif self.mode == "info":
            self._draw_info(now)
        elif self.mode == "help":
            self._draw_help(now)
        elif self.mode == "launcher":
            self._draw_picker(now)
        elif self.mode == "browse":
            self._draw_browser(now)
        elif self.mode == "update":
            self._draw_update(now)
        elif self.mode == "whatsnew":
            self._draw_whats_new(now)
        self._draw_toast(now)
        self._draw_fps()

    def _draw_fps(self) -> None:
        """Presents per second, and the Hz the loop is capped at. Top-right, only for COUCHDOOM_SHOW_FPS=1."""
        clock = self._fps_clock
        if clock is None:
            return
        fps = clock.get_fps()
        path = "gpu" if isinstance(self.screen, canvas.Canvas) else "software"
        text = f"{'—' if fps <= 0 else round(fps):>3} fps · {self._fps_hz} Hz · {path}"
        surf = self._text(text, self._font(18, mono=True), TEXT)
        pad = max(6, int(8 * self.s))
        box = surf.get_rect(topright=(self.w - pad, pad))
        self.screen.fill((0, 0, 0), box.inflate(pad, pad // 2))
        self.screen.blit(surf, box)

    def _note_fps_target(self, rate: int) -> None:
        if self._fps_clock is None or rate == self._fps_hz:
            return
        self._fps_hz = rate
        log.write("fps", f"aiming at {rate} Hz")

    def _draw_header(self) -> None:
        s, m = self.s, self.margin
        brand_font = self._font(88, bold=True)
        brand = self._shadowed("COUCH DOOM", brand_font, TEXT)  # brand stays English
        brand_pos = (m - int(4 * s), m - int(18 * s))
        self.screen.blit(brand, brand_pos)
        ver = self._tracked(f"v{__version__}", 18, MUTED, tracking=0.16)
        baseline = brand_pos[1] + brand_font.get_ascent()
        self.screen.blit(ver, (brand_pos[0] + brand.get_width() + int(10 * s), baseline - self._font(18, bold=True).get_ascent()))
        stripe_y = m + brand.get_height() - int(14 * s)
        canvas.rect(self.screen, self.theme.accent, (m, stripe_y, int(150 * s), int(7 * s)))
        tag = self._tracked(
            tr("header.from_launcher", launcher=self.opts.launcher) if self.opts.launcher else tr("header.couch_launcher"),
            18, self.theme.accent, tracking=0.3)
        tag_pos = (m + int(168 * s), stripe_y + int(4 * s) - tag.get_height() // 2)
        self.screen.blit(tag, tag_pos)
        if self.launchers and self.mode == "list":
            self.hits.append(Hit(tag.get_rect(topleft=tag_pos).inflate(int(24 * s), int(20 * s)), self._open_picker))

        if self.blocked:
            return
        total = len(self.opts.presets)
        count = tr("picker.n_presets", count=total) if total == 1 else tr("picker.n_presets_plural", count=total)
        # Leading space and one tracking gap: the count reads as the same line, not a second label.
        self.screen.blit(self._tracked(f" · {count}", 18, MUTED, tracking=0.3),
                         (tag_pos[0] + tag.get_width() + round(18 * s * 0.3), tag_pos[1]))
        if self.filter or self.mode == "search":
            fy = self.list_rect.top - int(64 * s)
            lab = self._tracked(tr("header.filter"), 17, self.theme.label, tracking=0.3)
            self.screen.blit(lab, (m, fy + int(12 * s)))
            caret = "|" if int(time.monotonic() * 2) % 2 == 0 else ""
            value_font = self._font(32)
            value = self._text((self.filter + caret) or " ", value_font, TEXT)
            self.screen.blit(value, (m + lab.get_width() + int(20 * s), fy))
            shown = sum(1 for r in self.rows if r.kind == "preset" and not r.fav)
            count_font = self._font(22)
            count = self._text(tr("header.n_matching", shown=shown, total=len(self.opts.presets)), count_font, MUTED)
            cy = fy + value_font.get_ascent() - value_font.metrics("H")[0][3] / 2
            self.screen.blit(count, (self.list_rect.right - count.get_width(), self._text_top(count_font, cy)))

    def _draw_notice(self) -> None:
        """Stands in for list and details when there's nothing to pick: say what's wrong and how to fix it."""
        s, m = self.s, self.margin
        pick = "L3" if self.input.pad_mode else "F4"
        if self.problem:
            title, detail, paths = self.problem.title, self.problem.detail, self.problem.tried
            if self.problem.hint:
                hint = self.problem.hint.format(pick=pick)
            elif len(paths) > 1:
                hint = tr("empty.multi_hint", pick=pick)
            else:
                who = self.problem.launcher or tr("empty.the_launcher")
                hint = tr("empty.single_hint", who=who)
        else:
            # Cap form is nominative (detail); _in is for "in {who}" so German can use dem Launcher.
            named = self.opts.launcher
            who = named or tr("empty.the_launcher_cap")
            who_in = named or tr("empty.the_launcher_in")
            title, detail, paths = tr("empty.no_presets_title"), tr("empty.no_presets_detail", who=who), [self.opts.path]
            hint = tr("empty.no_presets_hint", who=who_in)
        width = self.w - 2 * m
        y = self.list_rect.top
        for line in self._wrap(title, self._font(56, bold=True), width, 2):
            surf = self._shadowed(line, self._font(56, bold=True), TEXT)
            self.screen.blit(surf, (m, y))
            y += surf.get_height() - int(8 * s)
        y += int(26 * s)
        for line in self._wrap(detail, self._font(27), width, 3):
            self.screen.blit(self._text(line, self._font(27), MUTED), (m, y))
            y += int(38 * s)
        y += int(10 * s)
        mono = self._font(22, mono=True)
        for p in paths:
            self.screen.blit(self._text(self._fit(str(p), mono, width), mono, TEXT), (m + int(4 * s), y))
            y += int(34 * s)
        y += int(26 * s)
        canvas.rect(self.screen, self.theme.accent, (m, y, int(56 * s), max(2, int(3 * s))))
        y += int(22 * s)
        for line in self._wrap(hint, self._font(25), min(width, int(1100 * s)), 3):
            self.screen.blit(self._text(line, self._font(25), (206, 194, 178)), (m, y))
            y += int(36 * s)

    def _draw_list(self, now: float) -> None:
        lr, s = self.list_rect, self.s
        if not self.rows:
            msg = self._text(tr("empty.filter"), self._font(32), MUTED)
            self.screen.blit(msg, (lr.x, lr.y + int(20 * s)))
            return

        prev_clip = self.screen.get_clip()
        self.screen.set_clip(pygame.Rect(lr.x - int(28 * s), lr.y, self.list_edge - lr.x + int(28 * s), lr.height))
        bar_x = lr.x - int(28 * s)
        bar_top = lr.y + int(self.bar_y - self.scroll)
        pulse = 0.82 + 0.18 * math.sin(now * 3.2)
        stripe = tuple(int(c * pulse) for c in self.theme.accent)
        sel = self._sel_row()
        sel_row = self.rows[sel]
        # A heading's selection is the same bar as a game's, filling the bottom of its taller row.
        band_h = self.preset_h
        band_y = bar_top + self.header_h - band_h if sel_row.kind == "header" else bar_top
        glow = pygame.Rect(0, 0, self.bar_surface.get_width(), band_h)
        self.screen.blit(self.bar_surface, (bar_x, band_y), glow)

        name_font = self._font(33)
        sel_font = self._font(33, bold=True)
        for i, row in enumerate(self.rows):
            y = lr.y + self.row_y[i] - int(self.scroll)
            h = self.header_h if row.kind == "header" else self.preset_h
            if y + h < lr.y or y > lr.bottom:
                continue
            if row.kind == "preset":
                area = pygame.Rect(bar_x, y, self.list_edge - self.scroll_w - bar_x, h).clip(lr.x - int(28 * s), lr.y, self.w, lr.height)
                self.hits.append(Hit(area, lambda i=i: self._click_row(i)))
            if row.kind == "header":
                area = pygame.Rect(lr.x - int(28 * s), y, lr.width - self.scroll_w + int(28 * s), h).clip(lr.x - int(28 * s), lr.y, self.w, lr.height)
                self.hits.append(Hit(area, lambda i=i: self._click_row(i)))
                selected = i == sel
                t = self._tracked(row.text, 18, TEXT if selected else self.theme.label, tracking=0.22)
                ty = self._text_top(self._font(18, bold=True), y + h - self.preset_h / 2)
                self.screen.blit(t, (lr.x, ty))
                cnt = self._text(str(row.count), self._font(18, bold=True), MUTED)
                self.screen.blit(cnt, (lr.x + t.get_width() + int(14 * s), ty + (t.get_height() - cnt.get_height()) // 2))
                marker_size = max(4, int(4 * s))
                marker_x = lr.x - int(12 * s)
                marker_y = ty + t.get_height() // 2
                marker_rect = pygame.Rect(lr.x - int(20 * s), y, int(20 * s), h)
                self.hits.append(Hit(marker_rect, lambda i=i: self._toggle_section(i)))
                marker_color = self.theme.accent if selected else self.theme.label
                if row.collapsed:
                    points = [(marker_x - marker_size // 2, marker_y - marker_size),
                              (marker_x + marker_size // 2, marker_y),
                              (marker_x - marker_size // 2, marker_y + marker_size)]
                else:
                    points = [(marker_x - marker_size, marker_y - marker_size // 2),
                              (marker_x, marker_y + marker_size // 2),
                              (marker_x + marker_size, marker_y - marker_size // 2)]
                canvas.lines(self.screen, marker_color, False, points, max(1, int(1.5 * s)))
                continue

            selected = i == sel
            target = 16 * s if selected else 0.0
            key = (row.fav, row.preset)
            off = self.row_offset[key] = _approach(self.row_offset.get(key, 0.0), target, 16, self.dt)
            ok = self.commands[row.preset].ok
            color = TEXT if selected else (MUTED if ok else DIM)
            right_pad = 0
            if row.text == self.state.last_played:
                tag = self._tracked(tr("tag.last"), 18, self.theme.label if selected else MUTED, tracking=0.2)
                self.screen.blit(tag, (lr.right - tag.get_width(), self._text_top(self._font(18, bold=True), y + h / 2)))
                right_pad = tag.get_width() + int(16 * s)
            if not ok:
                warn = self._tracked(tr("tag.missing"), 18, ERROR, tracking=0.2)
                self.screen.blit(warn, (lr.right - right_pad - warn.get_width(), self._text_top(self._font(18, bold=True), y + h / 2)))
                right_pad += warn.get_width() + int(16 * s)
            font = sel_font if selected else name_font
            starred = not row.fav and row.text in self.state.favorites
            star = self._star(self.theme.label if selected else DIM) if starred else None
            star_w = star.get_width() + int(12 * s) if star else 0
            label = self._fit(row.text, font, lr.width - int(30 * s) - right_pad - star_w)
            t = self._text(label, font, color)
            tx = lr.x + int(10 * s + off)
            self.screen.blit(t, (tx, self._text_top(font, y + h / 2)))
            if star:
                self.screen.blit(star, (tx + t.get_width() + int(12 * s), int(y + (h - star.get_height()) / 2)))

        canvas.rect(self.screen, stripe, (bar_x, band_y, int(6 * s), band_h))
        self.screen.set_clip(prev_clip)
        if self.scroll > 1:
            self._blit_layer("top")
        max_scroll = self.content_h - lr.height
        if self.scroll < max_scroll - 1:
            self._blit_layer("bottom")

        if max_scroll > 0:
            tw = self.scroll_w
            track_x = self.list_edge - tw - int(12 * s)
            thumb_h = max(int(48 * s), int(lr.height * lr.height / self.content_h))
            thumb_y = lr.y + int((lr.height - thumb_h) * (self.scroll / max_scroll))
            grabbed = self.drag is not None and self.drag[0] == "list"
            if abs(self.scroll - self.thumb_scroll) > 0.5 or grabbed:
                self.thumb_scroll, self.thumb_moved = self.scroll, now
            # Quiet at rest, lit while the list moves. Alpha in steps so the cached surfaces stay few.
            lit = 1.0 - _ease_out(max(0.0, now - self.thumb_moved - 0.6) / 0.4)
            alpha = 95 + 32 * round(lit * 5)
            self.screen.blit(draw.rounded_rect(tw, lr.height, tw / 2, (255, 255, 255, 14)), (track_x, lr.y))
            self.screen.blit(draw.rounded_rect(tw, thumb_h, tw / 2, TEXT if grabbed else (*MUTED, alpha)), (track_x, thumb_y))
            self._scrollbar("list", pygame.Rect(track_x, lr.y, tw, lr.height), thumb_h, max_scroll)

    def _draw_detail(self, now: float) -> None:
        if not self.rows:
            return
        selected = self._sel_row()
        if self.rows[selected].kind == "header":
            self._draw_category_detail(now, self.rows[selected])
            return
        preset = self.opts.presets[self.current]
        cmd = self.commands[self.current]
        engine = self.opts.engine_for(preset)
        readme = self.readmes.get(self.current)
        logo = self.logos.get(self.current)
        show_title = not logo and self._should_show_title_text(self.current)
        # The list's group header beside it already names the section, unless it's Favorites or Recently played.
        header = next((self.rows[i] for i in range(selected, -1, -1) if self.rows[i].kind == "header"), None)
        show_section = header is None or header.group_id in (FAVORITES_ID, RECENT_ID)
        panel = self._cached_detail_panel(
            (preset, cmd, engine, readme, logo),
            (show_title, show_section, self.theme.label, self.detail_rect.size, self.s, current_language()),
            lambda: self._build_detail_panel(preset, cmd, engine, readme, logo, show_title, show_section),
        )
        self._blit_detail_panel(now, panel)

    def _cached_detail_panel(self, objects: tuple, values: tuple, build: Callable[[], pygame.Surface]) -> pygame.Surface:
        """The composed detail panel, rebuilt only when what it shows changes. Objects match by
        identity (a reload replaces them wholesale); holding them keeps their ids from being reused."""
        cached = self._detail_panel
        if cached is None or cached[1] != values or any(a is not b for a, b in zip(cached[0], objects, strict=True)):
            cached = self._detail_panel = (objects, values, build())
        return cached[2]

    def _blit_detail_panel(self, now: float, panel: pygame.Surface) -> None:
        """`panel` may be the inked part of a full-size panel (a subsurface); its offset puts it back in place."""
        dr, s = self.detail_rect, self.s
        t = _ease_out((now - self.detail_changed) / 0.3)
        ox, oy = panel.get_offset()
        panel.set_alpha(int(255 * t))
        self.screen.blit(panel, (dr.x + ox + int(32 * s * (1 - t)), dr.y + oy))

    def _build_detail_panel(self, preset: Preset, cmd, engine, readme, logo: pygame.Surface | None, show_title: bool,
                            show_section: bool = False) -> pygame.Surface:
        dr, s = self.detail_rect, self.s
        w = dr.width
        blocks: list[tuple[pygame.Surface, int]] = []  # (surface, gap after)

        if show_section:
            blocks.append((self._tracked(preset.section, 18, self.theme.label, tracking=0.22), int(10 * s)))
        title_font = self._font(64, bold=True)
        lines = self._wrap(preset.name, title_font, w, 3)
        byline = " · ".join(x for x in ((tr("tag.by", author=readme.author) if readme.author else ""), readme.year) if x) if readme else ""
        blurb = readme.blurb if readme else ""
        title_gap = int(8 * s) if byline or blurb else int(26 * s)
        if logo:
            blocks.append((logo, title_gap + int(10 * s)))
        elif show_title:
            for n, line in enumerate(lines):
                blocks.append((self._shadowed(line, title_font, TEXT), title_gap if n == len(lines) - 1 else -int(8 * s)))
        if byline:
            font = self._font(25)
            blocks.append((self._text(self._fit(byline, font, w), font, self.theme.label), int(12 * s) if blurb else int(26 * s)))
        if blurb:
            font = self._font(25)
            line_h = int(34 * s)
            blurb_lines = self._wrap(blurb, font, w, 6)
            surf = pygame.Surface((w, len(blurb_lines) * line_h), pygame.SRCALPHA)
            for n, line in enumerate(blurb_lines):
                surf.blit(self._text(line, font, (206, 194, 178)), (0, n * line_h))
            blocks.append((surf, int(28 * s)))

        # Setup details matter less to the player than the blurb: one small, dim run of
        # engine · IWAD · files. Full detail lives in the info sheet's Command tab.
        items = [engine.name if engine else preset.engine_id or "—", preset.iwad.name if preset.iwad else "—"]
        items += [p.name for p in preset.mappacks] + [p.name for p in preset.mods]
        if preset.additional_args:
            items.append(_pretty_args(preset.additional_args))
        font = self._font(20)
        row_h = int(28 * s)
        meta_lines = self._wrap_items(items, font, w, 2)
        meta = pygame.Surface((w, len(meta_lines) * row_h), pygame.SRCALPHA)
        for n, line in enumerate(meta_lines):
            meta.blit(self._text(line, font, MUTED), (0, n * row_h))
        blocks.append((meta, int(22 * s)))
        label_gap = int(30 * s)

        if cmd.issues:
            font = self._font(24)
            issues = cmd.issues[:3]
            surf = pygame.Surface((w, label_gap + len(issues) * int(32 * s)), pygame.SRCALPHA)
            surf.blit(self._tracked(tr("tag.problems"), 16, ERROR, tracking=0.25), (0, 0))
            for n, issue in enumerate(issues):
                surf.blit(self._text(self._fit(str(issue), font, w), font, ERROR), (0, label_gap + n * int(32 * s)))
            blocks.append((surf, int(26 * s)))

        total = sum(b.get_height() + gap for b, gap in blocks) - blocks[-1][1]
        panel = pygame.Surface(dr.size, pygame.SRCALPHA)
        top = y = max(0, dr.height - total)
        for surf, gap in blocks:
            panel.blit(surf, (0, y))
            y += surf.get_height() + gap
        # Only the inked rows: the empty top would be uploaded to the GPU on every selection change.
        return panel.subsurface(pygame.Rect(0, top, dr.width, max(1, min(total, dr.height - top))))

    def _draw_category_detail(self, now: float, row: Row) -> None:
        presets = self._category_presets(row)
        panel = self._cached_detail_panel(
            (self.opts,),
            (row.group_id, row.text, row.count, row.collapsed, bool(self.filter), tuple(presets),
             self.theme.label, self.detail_rect.size, self.s, current_language()),
            lambda: self._build_category_panel(row, presets),
        )
        self._blit_detail_panel(now, panel)

    def _build_category_panel(self, row: Row, presets: list[int]) -> pygame.Surface:
        """Roster under the mural; open/collapse hint stays at the bottom of the card."""
        dr, s = self.detail_rect, self.s
        w = dr.width
        preview_label = self._tracked(tr("group.in_this"), 15, self.theme.label, tracking=0.25)
        preview_font = self._font(23)
        if self.filter:
            state_text = tr("group.search_keeps")
        else:
            state_text = tr("group.state_collapsed") if row.collapsed else tr("group.state_open")
        state = self._text(state_text, self._font(20), MUTED)
        top = int(24 * s)
        bottom_pad = int(24 * s)
        row_h = preview_font.get_linesize() + int(9 * s)
        fixed_h = preview_label.get_height() + int(12 * s) + state.get_height() + bottom_pad
        available_h = max(0, dr.height - top - fixed_h)
        columns, visible, more = self._category_preview_capacity(len(presets), w, available_h, row_h)
        col_gap = int(28 * s)
        col_w = max(1, (w - col_gap * (columns - 1)) // columns)
        preview_rows = math.ceil(visible / columns) if visible else 0
        preview = pygame.Surface((w, preview_rows * row_h), pygame.SRCALPHA)
        for n, idx in enumerate(presets[:visible]):
            col, line = n % columns, n // columns
            title = self._fit(self.opts.presets[idx].name, preview_font, col_w - int(12 * s))
            ink = self._text(f"•  {title}", preview_font, (206, 194, 178))
            preview.blit(ink, (col * (col_w + col_gap), line * row_h))

        blocks: list[tuple[pygame.Surface, int]] = [(preview_label, int(12 * s))]
        if visible:
            blocks.append((preview, int(8 * s)))
        if more:
            blocks.append((self._text(tr("group.and_more", count=more), self._font(20), MUTED), int(8 * s)))
        panel = pygame.Surface(dr.size, pygame.SRCALPHA)
        y = top
        for surf, gap in blocks:
            panel.blit(surf, (0, y))
            y += surf.get_height() + gap
        panel.blit(state, (0, dr.height - state.get_height() - bottom_pad))
        return panel

    def _footer_hints(self) -> list[tuple[tuple[str, ...], str, tuple[Action, ...]]]:
        """(glyphs, label, actions): one action for the whole hint, or one per glyph (LB = previous, RB = next)."""
        pad = self.input.pad_mode
        A = Action
        if self.mode == "browse":
            browser = self.file_browser
            label = tr("hint.doom_files") if browser and browser.show_all else tr("hint.all_files")
            toggle = [] if browser is None or browser.selecting_root else [(("X",) if pad else ("KEY:TAB",), label, (A.ALT,))]
            pages = browser is not None and len(browser.entries) > self._browser_page_size()
            page = [(("LT", "RT") if pad else ("KEY:LEFT", "KEY:RIGHT"), tr("hint.page"), (A.PAGE_UP, A.PAGE_DOWN))] if pages else []
            return [(("A",) if pad else ("KEY:ENTER",), tr("hint.open"), (A.CONFIRM,)), *page,
                    (("B",) if pad else ("KEY:ESC",), tr("hint.back"), (A.BACK,)), *toggle]
        if self.mode == "launcher":
            return [(("A",) if pad else ("KEY:ENTER",), tr("hint.choose"), (A.CONFIRM,)), (("B",) if pad else ("KEY:ESC",), tr("hint.close"), (A.BACK,))]
        if self.mode == "whatsnew":
            return [(("A",) if pad else ("KEY:ENTER",), tr("hint.continue"), (A.CONFIRM,))]
        if self.mode == "update":
            if self.update_install_job is not None:
                return [(("B",) if pad else ("KEY:ESC",), tr("hint.cancel"), (A.BACK,))] if self._update_cancellable() else []
            return [(("A",) if pad else ("KEY:ENTER",), tr("hint.choose"), (A.CONFIRM,)), (("B",) if pad else ("KEY:ESC",), tr("hint.later"), (A.BACK,))]
        if self.mode == "menu":
            return [(("A",) if pad else ("KEY:ENTER",), tr("hint.choose"), (A.CONFIRM,)),
                    (("B",) if pad else ("KEY:ESC",), tr("hint.close"), (A.BACK,))]
        if self.mode == "help":
            if pad:
                return [(("RS",), tr("hint.scroll"), ()), (("Y",), tr("hint.help_feedback"), (A.SEARCH,)), (("B",), tr("hint.close"), (A.BACK,))]
            return [(("KEY:UP", "KEY:DOWN"), tr("hint.scroll"), (A.UP, A.DOWN)), (("KEY:F5",), tr("hint.help_feedback"), (A.ISSUES,)), (("KEY:ESC",), tr("hint.close"), (A.BACK,))]
        if self.blocked:
            picking = self.launchers is not None and self.launchers.must_pick
            reload = [(("A",) if pad else ("KEY:ENTER",), tr("hint.choose") if picking else tr("hint.reload"), (A.CONFIRM,))]
            return [*(reload if self.reload else []), (("B",) if pad else ("KEY:ESC",), tr("hint.quit"), (A.BACK,))]
        if self.mode == "search":
            if pad:
                return [(("A",), tr("hint.type"), (A.CONFIRM,)), (("X",), tr("hint.delete"), (A.ALT,)), (("Y",), tr("hint.done"), (A.SEARCH,)), (("B",), tr("hint.cancel"), (A.BACK,))]
            return [(("KEY:A-Z",), tr("hint.type"), ()), (("KEY:BKSP",), tr("hint.delete"), (A.ALT,)), (("KEY:ENTER",), tr("hint.done"), (A.SEARCH,)),
                    (("KEY:ESC",), tr("hint.cancel"), (A.BACK,))]
        # A prompt shown elsewhere on screen (the sheet's tab glyphs) is not repeated here.
        if self.mode == "info":
            scrolls = self._info_max_scroll() > 0
            if pad:
                scroll = [(("RS",), tr("hint.scroll"), ()), (("LT", "RT"), tr("hint.page"), (A.PAGE_UP, A.PAGE_DOWN))] if scrolls else []
                return [(("A",), tr("hint.play"), (A.CONFIRM,)), *scroll, (("B",), tr("hint.close"), (A.BACK,))]
            scroll = [(("KEY:UP", "KEY:DOWN"), tr("hint.scroll"), (A.UP, A.DOWN))] if scrolls else []
            return [(("KEY:ENTER",), tr("hint.play"), (A.CONFIRM,)), *scroll, (("KEY:ESC",), tr("hint.close"), (A.BACK,))]
        category_selected = self._category_selected()
        fav = tr("hint.unfavorite") if self.rows and self.opts.presets[self.current].name in self.state.favorites else tr("hint.favorite")
        section = (A.PREV_SECTION, A.NEXT_SECTION)
        primary = tr("hint.open_close") if category_selected else tr("hint.play")
        if category_selected:
            info_hint = [(('X',) if pad else ('KEY:TAB',), self._bulk_fold_label(), (A.ALT,))]
        else:
            info_hint = [(('X',) if pad else ('KEY:TAB',), tr("hint.info"), (A.ALT,))]
        favorite_hint = [] if category_selected else [(('R3',) if pad else ('KEY:F3',), fav, (A.FAVORITE,))]
        if pad:
            if self.filter:
                last_hint = [(("B",), tr("hint.clear"), (A.BACK,))]
            elif getattr(self.state, "last_played", None):
                last_hint = [(("B",), tr("hint.last"), (A.BACK,))]
            else:
                last_hint = []
            return [(("START",), tr("hint.menu"), (A.MENU,)), (("A",), primary, (A.CONFIRM,)), *last_hint,
                    (("BACK",), tr("hint.help"), (A.HELP,)), *info_hint, (("Y",), tr("hint.search"), (A.SEARCH,)),
                    (("LB", "RB"), tr("hint.section"), section),
                    *favorite_hint]
        clear = (("KEY:ESC",), tr("hint.clear"), (A.BACK,)) if self.filter else (("KEY:ESC",), tr("hint.menu"), (A.MENU,))
        if not self.filter and getattr(self.state, "last_played", None):
            last_hint = [(("KEY:CTRL",), tr("hint.last"), (A.BACK,))]
        else:
            last_hint = []
        return [clear, (("KEY:ENTER",), primary, (A.CONFIRM,)), (("KEY:F1",), tr("hint.help"), (A.HELP,)), *info_hint,
                *last_hint, (("KEY:LEFT", "KEY:RIGHT"), tr("hint.section"), section),
                *([] if category_selected else [(("KEY:F3",), fav, (A.FAVORITE,))])]

    def _dim_backdrop(self, alpha: int) -> pygame.Rect:
        """Darken everything above the footer as black at `alpha` would, in place.

        Multiplying by (255 - alpha) gives the same pixels as blending a black overlay, without allocating
        and blending a full-screen alpha surface every frame (about 8 ms per frame at 4K).
        """
        area = pygame.Rect(0, 0, self.w, self.h - self.footer_h)
        k = 255 - max(0, min(255, alpha))
        self.screen.fill((k, k, k), area, special_flags=pygame.BLEND_MULT)
        return area

    def _draw_footer(self) -> None:
        s = self.s
        top = self.h - self.footer_h
        band = self._footer_band
        if band is None or band.get_size() != (self.w, self.footer_h):
            band = self._footer_band = pygame.Surface((self.w, self.footer_h), pygame.SRCALPHA)
            band.fill((8, 6, 5, 150))
            pygame.draw.line(band, (255, 255, 255, 14), (0, 0), (self.w, 0))
        self.screen.blit(band, (0, top))

        cy = top + self.footer_h // 2
        hints = self._footer_hints()
        available = self.w - 2 * self.margin
        font_size = 23
        prepared = []
        while True:
            font = self._font(font_size)
            prepared = [(specs, label, actions, self.glyphs.row(specs), self._text(label, font, MUTED))
                        for specs, label, actions in hints]
            inner_gap = int(12 * s)
            widths = [g.get_width() + inner_gap + label_surf.get_width() for _, _, _, g, label_surf in prepared]
            gap = max(int(8 * s), min(int(26 * s), (available - sum(widths)) // max(1, len(widths) - 1)))
            if sum(widths) + gap * max(0, len(widths) - 1) <= available or font_size <= 15:
                break
            font_size -= 1
        x = self.margin
        for specs, label, actions, g, t in prepared:
            start = x
            self.screen.blit(g, (x, cy - g.get_height() // 2))
            x += g.get_width() + inner_gap
            self.screen.blit(t, (x, self._text_top(font, cy)))
            x += t.get_width()
            whole = pygame.Rect(start - gap // 2, top, x - start + gap, self.footer_h)
            if len(actions) > 1:
                # Each glyph is its own button; the label repeats the last one (RB, RT: next).
                part = g.get_width() // len(actions)
                self.hits.append(Hit(whole, self._act(actions[-1])))
                for n, action in enumerate(actions):
                    self.hits.append(Hit(pygame.Rect(start + n * part, top, part, self.footer_h), self._act(action)))
            elif actions:
                self.hits.append(Hit(whole, self._act(actions[0])))
            x += gap

    def _menu_hover(self, index: int) -> None:
        if index != self.menu_sel:
            self.menu_sel = index
            self._sound("move")

    def _draw_menu(self, now: float) -> None:
        s = self.s
        t = _ease_out((now - self.menu_opened) / 0.2)
        items = self._menu_items()
        pad, row_h, head_h = int(30 * s), int(68 * s), int(72 * s)
        width = min(self.w - 2 * self.margin, int(760 * s))
        height = 2 * pad + head_h + len(items) * row_h
        box = pygame.Rect(0, 0, width, height)
        box.center = (self.w // 2, (self.h - self.footer_h) // 2 + int(18 * s * (1 - t)))

        shade = self._dim_backdrop(int(155 * t))
        self.screen.blit(draw.rounded_rect(box.width, box.height, 18 * s, (*PANEL, 250), (78, 62, 55), 1.5 * s), box)
        self.hits.append(Hit(shade, self._act(Action.BACK)))
        self.hits.append(Hit(box, lambda: None))

        x, y = box.x + pad, box.y + pad
        self.screen.blit(self._text(tr("menu.title"), self._font(36, bold=True), TEXT), (x + int(12 * s), y))
        y += head_h
        font = self._font(27)
        selected_font = self._font(27, bold=True)
        for index, (key, name) in enumerate(items):
            rect = pygame.Rect(box.x + int(12 * s), y, box.width - int(24 * s), row_h)
            selected = index == self.menu_sel
            enabled = key != "refresh" or self.reload is not None
            if selected:
                self.screen.blit(draw.rounded_rect(rect.width, rect.height - int(5 * s), 9 * s, (255, 255, 255, 16)), rect)
                canvas.rect(self.screen, self.theme.accent,
                                 (rect.x, rect.y + int(12 * s), int(5 * s), rect.height - int(29 * s)))
            self.hits.append(Hit(rect, lambda i=index: self._menu_pick(i), lambda i=index: self._menu_hover(i)))
            ink = TEXT if selected and enabled else MUTED if enabled else DIM
            row_font = selected_font if selected else font
            self.screen.blit(self._text(name, row_font, ink),
                             (x + int(12 * s), self._text_top(row_font, rect.centery)))
            if key == "refresh" and self.menu_status and now - self.menu_status_at < 2.0:
                age = max(0.0, now - self.menu_status_at)
                status = self._text(self.menu_status, self._font(16), self.theme.label)
                status.set_alpha(int(255 * max(0.0, 1.0 - age / 2.0)))
                self.screen.blit(status, (rect.right - status.get_width() - int(22 * s), rect.centery - status.get_height() // 2))
            value, on = None, False
            if key in ("music", "sounds", "recent"):
                on = {"music": self.state.music, "sounds": self.state.menu_sounds, "recent": self.state.recent_group}[key]
                value = tr("menu.on") if on else tr("menu.off")
            elif key == "colors":
                palette = self._current_palette_key()
                value = tr(f"palette.{palette}") if palette else tr("palette.auto")
            elif key == "language":
                value = tr(f"lang.{current_language()}")
            if value:
                value_font = self._font(22)
                badge = self._text(value, value_font, self.theme.label if on else TEXT if selected else MUTED)
                self.screen.blit(badge, (rect.right - badge.get_width() - int(22 * s), self._text_top(value_font, rect.centery)))
            y += row_h

    def _draw_picker(self, now: float) -> None:
        s = self.s
        t = _ease_out((now - self.picker_opened) / 0.25)
        pad, row_h, head_h, note_h = int(34 * s), int(84 * s), int(76 * s), int(58 * s)
        width = min(self.w - 2 * self.margin, int(1040 * s))
        box = pygame.Rect(0, 0, width, 2 * pad + head_h + len(self.picker) * row_h + note_h)
        box.center = (self.w // 2, (self.h - self.footer_h) // 2 + int(24 * s * (1 - t)))

        shade = self._dim_backdrop(int(150 * t))
        self.screen.blit(draw.rounded_rect(box.width, box.height, 18 * s, (*PANEL, 248), (78, 62, 55), 1.5 * s), box)
        self.hits.append(Hit(shade, self._act(Action.BACK)))
        self.hits.append(Hit(box, lambda: None))

        x, y = box.x + pad, box.y + pad
        inner = box.width - 2 * pad
        title_font = self._font(40, bold=True)
        self.screen.blit(self._text(tr("picker.title"), title_font, TEXT), (x, y))
        y += head_h

        current = self.launchers.current if self.launchers else None
        name_font, sel_font, side_font, mono = self._font(31), self._font(31, bold=True), self._font(21), self._font(17, mono=True)
        for i, choice in enumerate(self.picker):
            rect = pygame.Rect(box.x + int(12 * s), y, box.width - int(24 * s), row_h - int(6 * s))
            selected = i == self.picker_sel
            if selected:
                self.screen.blit(draw.rounded_rect(rect.width, rect.height, 10 * s, (255, 255, 255, 16)), rect)
                canvas.rect(self.screen, self.theme.accent, (rect.x, rect.y + int(10 * s), int(5 * s), rect.height - int(20 * s)))
            self.hits.append(Hit(rect, lambda i=i: self._picker_pick(i), lambda i=i: self._picker_hover(i)))
            if choice is None:
                name, sub, side, side_color = tr("picker.find_myself"), tr("picker.find_sub", program=PROGRAM), "", MUTED
            else:
                result = self.launchers.cached_preview(choice)
                name, sub = choice.name, str(choice.path)
                if result is None:
                    side, side_color = "", DIM
                elif isinstance(result, OptionsError):
                    side, side_color = tr("picker.cant_read"), ERROR
                else:
                    n = len(result.presets)
                    if not n:
                        side = tr("picker.no_presets")
                    elif n == 1:
                        side = tr("picker.n_presets", count=n)
                    else:
                        side = tr("picker.n_presets_plural", count=n)
                    side_color = MUTED if n else DIM
            side_surf = self._text(side, side_font, side_color) if side else None
            right = rect.right - int(22 * s)
            if side_surf:
                self.screen.blit(side_surf, (right - side_surf.get_width(), self._text_top(side_font, rect.y + int(30 * s))))
                right -= side_surf.get_width() + int(18 * s)
            if current and choice is not None and choice.id == current.id:
                tag = self._tracked(tr("picker.current"), 15, self.theme.label, tracking=0.25)
                self.screen.blit(tag, (right - tag.get_width(), self._text_top(self._font(15, bold=True), rect.y + int(30 * s))))
            font = sel_font if selected else name_font
            self.screen.blit(self._text(name, font, TEXT if selected else MUTED), (x, self._text_top(font, rect.y + int(30 * s))))
            self.screen.blit(self._text(self._fit(sub, mono, inner), mono, MUTED), (x, rect.y + int(52 * s)))
            y += row_h

        note = tr("picker.not_listed", program=PROGRAM)
        note_font = self._font(21)
        self.screen.blit(self._text(self._fit(note, note_font, inner), note_font, MUTED), (x, y + int(18 * s)))

    def _browser_pick(self, index: int) -> None:
        if not self.file_browser or not 0 <= index < len(self.file_browser.entries):
            return
        self.file_browser.selected = index
        self._browser_action(Action.CONFIRM)

    def _draw_browser(self, now: float) -> None:
        browser = self.file_browser
        if browser is None:
            return
        s = self.s
        page = self._browser_page_size()
        shown = browser.entries[self.browser_scroll:self.browser_scroll + page]
        pad, row_h, head_h = int(28 * s), int(54 * s), self._browser_head_h()
        width = min(self.w - 2 * self.margin, int(1120 * s))
        rows = max(1, len(shown)) + (1 if browser.empty else 0)
        height = min(self.h - self.footer_h - int(32 * s), 2 * pad + head_h + rows * row_h)
        box = pygame.Rect(0, 0, width, height)
        box.center = (self.w // 2, (self.h - self.footer_h) // 2)
        shade = self._dim_backdrop(155)
        self.screen.blit(draw.rounded_rect(box.width, box.height, 18 * s, (*PANEL, 250), (78, 62, 55), 1.5 * s), box)
        self.hits.append(Hit(shade, self._act(Action.BACK)))
        self.hits.append(Hit(box, lambda: None))

        x, y = box.x + pad, box.y + pad
        inner = box.width - 2 * pad
        title = tr("browser.choose_root") if browser.selecting_root else tr("picker.find_sub", program=PROGRAM)
        title_font = self._font(35, bold=True)
        self.screen.blit(self._text(self._fit(title, title_font, inner), title_font, TEXT), (x, y))
        if not browser.selecting_root:
            path_font = self._font(17, mono=True)
            path = self._fit_start(str(browser.directory), path_font, inner)
            self.screen.blit(self._text(path, path_font, MUTED), (x, y + int(48 * s)))
        y += head_h

        if not shown:
            self.screen.blit(self._text(tr("browser.empty"), self._font(24), MUTED), (x, y + int(12 * s)))
        for offset, entry in enumerate(shown):
            index = self.browser_scroll + offset
            scrollbar = len(browser.entries) > page
            right_reserve = int(16 * s) if scrollbar else 0
            rect = pygame.Rect(box.x + int(12 * s), y, box.width - int(24 * s) - right_reserve, row_h - int(4 * s))
            selected = index == browser.selected
            if selected:
                self.screen.blit(draw.rounded_rect(rect.width, rect.height, 9 * s, (255, 255, 255, 18)), rect)
                canvas.rect(self.screen, self.theme.accent, (rect.x, rect.y + int(8 * s), int(5 * s), rect.height - int(16 * s)))
            self.hits.append(Hit(rect, lambda i=index: self._browser_pick(i)))
            if offset and shown[offset - 1].launcher and not entry.launcher:
                canvas.line(self.screen, (44, 37, 34), (x, y - int(2 * s)), (rect.right - int(16 * s), y - int(2 * s)), max(1, int(s)))
            label = entry.display_name
            font = self._font(25, bold=selected and not entry.parent_selector)
            chevron = int(6 * s)
            icon_d = max(10, int(22 * s))
            name_x = x + icon_d + int(14 * s)
            # Folders and drives open into more rows; the way back up points the other way.
            enters = entry.is_dir and not entry.parent_selector
            room = rect.right - name_x - int(16 * s) - (3 * chevron if enters else 0)
            detail_font = self._font(20)
            detail_color = self.theme.label if entry.launcher else MUTED
            detail = self._text(self._fit(entry.detail, detail_font, room // 2), detail_font, detail_color) if entry.detail else None
            gap = int(18 * s)
            name_room = room - (detail.get_width() + gap if detail else 0)
            other = browser.show_all and not entry.is_dir and not entry.launcher
            color = TEXT if selected else self.theme.label if entry.launcher else DIM if other else MUTED
            name = self._text(self._fit(label, font, name_room), font, color)
            self.screen.blit(name, (name_x, self._text_top(font, rect.centery)))
            if detail:
                self.screen.blit(detail, (name_x + name.get_width() + gap, self._text_top(detail_font, rect.centery)))
            if not entry.parent_selector:
                kind = "drive" if entry.root_selector and entry.path != Path.home() else "folder" if entry.is_dir else "launcher" if entry.launcher else "file"
                icon = self._browser_icon(kind, color)
                self.screen.blit(icon, (x, rect.centery - icon.get_height() // 2))
            if entry.parent_selector or enters:
                mark = TEXT if selected else MUTED
                cx = x + icon_d // 2 if entry.parent_selector else rect.right - int(16 * s) - chevron
                d = -1 if entry.parent_selector else 1
                points = [(cx - d * chevron // 2, rect.centery - chevron), (cx + d * chevron // 2, rect.centery),
                          (cx - d * chevron // 2, rect.centery + chevron)]
                canvas.lines(self.screen, mark, False, points, max(1, int(2 * s)))
            y += row_h
        if browser.empty:
            self.screen.blit(self._text(tr("browser.empty"), self._font(22), MUTED), (x, self._text_top(self._font(22), y + row_h // 2)))

        if len(browser.entries) > page:
            track_w = self.scroll_w
            track = pygame.Rect(box.right - pad - track_w, box.y + pad + head_h,
                                track_w, max(1, len(shown) * row_h - int(4 * s)))
            thumb_h = min(track.height, max(int(48 * s), int(track.height * page / len(browser.entries))))
            max_scroll = max(1, len(browser.entries) - page)
            thumb_y = track.y + int((track.height - thumb_h) * self.browser_scroll / max_scroll)
            grabbed = self.drag is not None and self.drag[0] == "browser"
            self.screen.blit(draw.rounded_rect(track.width, track.height, track.width / 2,
                                               (255, 255, 255, 18)), track)
            self.screen.blit(draw.rounded_rect(track.width, thumb_h, track.width / 2,
                                               TEXT if grabbed else MUTED), (track.x, thumb_y))
            self._scrollbar("browser", track, thumb_h, max_scroll)

    def _update_status(self) -> tuple[str, float | None]:
        """The install's current step, and how far along it is when that's known."""
        phase, done, total = self.update_progress
        if phase == "downloading":
            if total:
                return tr("update.downloading_mb_of", done=_mb(done), total=_mb(total)), done / total
            return tr("update.downloading_mb", done=_mb(done)), None
        if phase == "unpacking" and total:
            return tr("update.unpacking", done=done, total=total), done / total
        return tr({"verifying": "update.verifying", "preparing": "update.preparing"}.get(phase, "update.checking")), None

    def _draw_update(self, now: float) -> None:
        s = self.s
        info = self.update or {}
        choices = update_choices(info, bool(getattr(sys, "frozen", False)))
        t = _ease_out((now - self.update_opened) / 0.25)
        pad, row_h, head_h = int(34 * s), int(84 * s), int(112 * s)
        width = min(self.w - 2 * self.margin, int(980 * s))
        inner = width - 2 * pad
        notes_font = self._font(23)
        notes: list[str] = []
        for item in info.get("notes", [])[:updates.MAX_NOTES]:
            wrapped = self._wrap(item, notes_font, inner - int(26 * s), 2)
            notes += [(("•  " if i == 0 else "    ") + line) for i, line in enumerate(wrapped)]
        notes_h = (int(34 * s) + len(notes) * int(32 * s) + int(18 * s)) if notes else 0
        if info.get("more_notes"):
            notes_h += int(28 * s)
        downloading = self.update_install_job is not None
        cancellable = self._update_cancellable()
        status, fraction = self._update_status() if downloading else ("", None)
        status_h = int(28 * s) if self.update_error else int(48 * s) if downloading else 0
        if downloading and fraction is not None:
            status_h += int(20 * s)
        box = pygame.Rect(0, 0, width, 2 * pad + head_h + notes_h + status_h + len(choices) * row_h)
        box.center = (self.w // 2, (self.h - self.footer_h) // 2 + int(24 * s * (1 - t)))

        shade = self._dim_backdrop(int(150 * t))
        self.screen.blit(draw.rounded_rect(box.width, box.height, 18 * s, (*PANEL, 248), (78, 62, 55), 1.5 * s), box)
        later = next(i for i, item in enumerate(choices) if item[0] == "later")
        self.hits.append(Hit(shade, lambda: self._update_pick(later)))
        self.hits.append(Hit(box, lambda: None))

        x, y = box.x + pad, box.y + pad
        if info.get("arch_switch"):
            title = tr("update.native", kind=info.get("native_label", ""))
            subtitle = tr("update.native_sub", other=info.get("running_label", ""))
        else:
            title = tr("update.out", version=info.get("version", ""))
            subtitle = tr("update.youre_on", current=info.get("current", __version__))
        title_font = self._font(40, bold=True)
        self.screen.blit(self._text(self._fit(title, title_font, inner), title_font, TEXT), (x, y))
        self.screen.blit(self._text(self._fit(subtitle, self._font(22), inner), self._font(22), MUTED), (x, y + int(52 * s)))
        y += head_h

        if notes:
            self.screen.blit(self._tracked(tr("update.whats_new"), 15, self.theme.label, tracking=0.25), (x, y))
            y += int(34 * s)
            for line in notes:
                self.screen.blit(self._text(line, notes_font, MUTED), (x, y))
                y += int(32 * s)
            if info.get("more_notes"):
                more_font = self._font(18)
                self.screen.blit(self._text(tr("update.more_notes"), more_font, self.theme.label), (x, y))
                y += int(28 * s)
            y += int(18 * s)

        name_font, sel_font, sub_font = self._font(31), self._font(31, bold=True), self._font(21)
        if self.update_error:
            self.screen.blit(self._text(self._fit(self.update_error, sub_font := self._font(20), inner), sub_font, ERROR), (x, y))
            y += int(28 * s)
        elif downloading:
            y += int(14 * s)
            status_font = self._font(22)
            self.screen.blit(self._text(self._fit(status, status_font, inner), status_font, MUTED), (x, y))
            y += int(34 * s)
            if fraction is not None:
                bar_h = max(2, int(6 * s))
                canvas.rect(self.screen, KEY_IDLE, (x, y, inner, bar_h), border_radius=bar_h // 2)
                if fill := int(inner * max(0.0, min(1.0, fraction))):
                    canvas.rect(self.screen, self.theme.accent, (x, y, fill, bar_h), border_radius=bar_h // 2)
                y += int(20 * s)
        for i, (_, name, sub) in enumerate(choices):
            rect = pygame.Rect(box.x + int(12 * s), y, box.width - int(24 * s), row_h - int(6 * s))
            selected = i == self.update_sel
            installing_row = downloading and choices[i][0] == "install"
            if selected and (cancellable or not installing_row):
                self.screen.blit(draw.rounded_rect(rect.width, rect.height, 10 * s, (255, 255, 255, 16)), rect)
                canvas.rect(self.screen, self.theme.accent, (rect.x, rect.y + int(10 * s), int(5 * s), rect.height - int(20 * s)))
            if not downloading or installing_row and cancellable:
                self.hits.append(Hit(rect, lambda i=i: self._update_pick(i), lambda i=i: self._update_hover(i)))
            font = sel_font if selected else name_font
            label = tr("update.cancel") if installing_row else name
            color = DIM if installing_row and not cancellable else TEXT if selected else MUTED
            self.screen.blit(self._text(label, font, color), (x, self._text_top(font, rect.y + int(26 * s))))
            sub = sub.replace("{v}", str(info.get("version", "")))
            self.screen.blit(self._text(self._fit(sub, sub_font, inner), sub_font, MUTED), (x, rect.y + int(52 * s)))
            y += row_h

    def _draw_whats_new(self, now: float) -> None:
        s = self.s
        info = self.whats_new or {}
        sections = info.get("sections", [])
        t = _ease_out((now - self.whats_new_opened) / 0.25)
        pad, head_h, row_h = int(34 * s), int(112 * s), int(84 * s)
        label_h, line_h, gap_h, more_h = int(34 * s), int(32 * s), int(14 * s), int(28 * s)
        width = min(self.w - 2 * self.margin, int(980 * s))
        inner = width - 2 * pad
        notes_font = self._font(23)

        # Newest release first; whatever doesn't fit the screen is left to CHANGELOG.txt rather than scrolled.
        room = self.h - self.footer_h - 2 * self.margin - 2 * pad - head_h - row_h - more_h
        labelled = len(sections) > 1
        rows: list[tuple[str, str]] = []  # ("label" | "note" | "gap", text)
        used = hidden = 0
        for version, notes in sections:
            block: list[tuple[str, str]] = [("label", tr("whats_new.version", version=version))] if labelled else []
            block_h = label_h if labelled else 0
            for note in notes:
                wrapped = self._wrap(note, notes_font, inner - int(26 * s), 2)
                lines = [("note", ("•  " if i == 0 else "    ") + line) for i, line in enumerate(wrapped)]
                if hidden or used + block_h + len(lines) * line_h > room:
                    hidden += 1
                    continue
                block += lines
                block_h += len(lines) * line_h
            if any(kind == "note" for kind, _ in block):
                rows += [*block, ("gap", "")]
                used += block_h + gap_h
        if rows and rows[-1][0] == "gap":
            rows.pop()
            used -= gap_h

        box_h = 2 * pad + head_h + used + (more_h if hidden else 0) + gap_h + row_h
        box = pygame.Rect(0, 0, width, box_h)
        box.center = (self.w // 2, (self.h - self.footer_h) // 2 + int(24 * s * (1 - t)))
        shade = self._dim_backdrop(int(150 * t))
        self.screen.blit(draw.rounded_rect(box.width, box.height, 18 * s, (*PANEL, 248), (78, 62, 55), 1.5 * s), box)
        self.hits.append(Hit(shade, self._close_whats_new))
        self.hits.append(Hit(box, lambda: None))

        x, y = box.x + pad, box.y + pad
        self.screen.blit(self._text(tr("whats_new.title", version=info.get("version", "")), self._font(40, bold=True), TEXT), (x, y))
        previous = info.get("previous")
        sub = tr("whats_new.from", previous=previous) if previous else tr("whats_new.updated")
        self.screen.blit(self._text(sub, self._font(22), MUTED), (x, y + int(52 * s)))
        y += head_h

        for kind, text in rows:
            if kind == "label":
                self.screen.blit(self._tracked(text, 15, self.theme.label, tracking=0.25), (x, y))
                y += label_h
            elif kind == "note":
                self.screen.blit(self._text(text, notes_font, MUTED), (x, y))
                y += line_h
            else:
                y += gap_h
        if hidden:
            more_font = self._font(18)
            self.screen.blit(self._text(tr("whats_new.more"), more_font, self.theme.label), (x, y + int(8 * s)))
            y += more_h
        y += gap_h

        rect = pygame.Rect(box.x + int(12 * s), y, box.width - int(24 * s), row_h - int(6 * s))
        self.screen.blit(draw.rounded_rect(rect.width, rect.height, 10 * s, (255, 255, 255, 16)), rect)
        canvas.rect(self.screen, self.theme.accent, (rect.x, rect.y + int(10 * s), int(5 * s), rect.height - int(20 * s)))
        self.hits.append(Hit(rect, self._close_whats_new))
        font = self._font(31, bold=True)
        self.screen.blit(self._text(tr("whats_new.continue"), font, TEXT), (x, self._text_top(font, rect.centery)))

    def _help_rows(self, width: int) -> list[tuple[str, bool]]:
        body_font = self._font(21)
        rows: list[tuple[str, bool]] = []
        for heading, paragraph in help_sections():
            rows.append((heading, True))
            rows.extend((line, False) for line in self._wrap(paragraph, body_font, width, 100))
            rows.append(("", False))
        return rows

    def _help_metrics(self) -> tuple[pygame.Rect, pygame.Rect, list[tuple[str, bool]], list[int], int]:
        s = self.s
        width = min(self.w - 2 * self.margin, int(1040 * s))
        height = min(self.h - self.footer_h - int(2 * self.margin), int(720 * s))
        box = pygame.Rect(0, 0, width, height)
        box.center = (self.w // 2, (self.h - self.footer_h) // 2)
        pad = int(38 * s)
        head_h = int(112 * s)
        body = pygame.Rect(box.x + pad, box.y + head_h, box.width - 2 * pad, box.height - head_h - pad)
        rows = self._help_rows(body.width)
        heights = [int((26 if is_head else 28 if text else 24) * s) for text, is_head in rows]
        return box, body, rows, heights, sum(heights)

    def _help_max_scroll(self) -> int:
        if not hasattr(self, "s"):
            return 0
        _, body, _, _, total = self._help_metrics()
        return max(0, total - body.height)

    def _help_line_h(self) -> int:
        return max(1, int(28 * self.s))

    def _draw_help(self, now: float) -> None:
        s = self.s
        box, body, rows, heights, total = self._help_metrics()
        t = _ease_out((now - self.info_opened) / 0.25) if self.info_opened else 1.0
        shade = self._dim_backdrop(int(155 * t))
        panel = draw.rounded_rect(box.width, box.height, 18 * s, (*PANEL, 250), (78, 62, 55), 1.5 * s)
        self.screen.blit(panel, box)
        self.hits.append(Hit(shade, self._close_overlay))
        self.hits.append(Hit(box, lambda: None))

        x, y = box.x + int(38 * s), box.y + int(34 * s)
        title_font = self._font(40, bold=True)
        self.screen.blit(self._text(tr("help.how_to"), title_font, TEXT), (x, y))
        report = self._tracked(tr("help.feedback"), 15, TEXT, tracking=0.2)
        report_rect = pygame.Rect(0, 0, report.get_width() + int(26 * s), int(38 * s))
        report_rect.midright = (box.right - int(38 * s), y + title_font.get_height() // 2)
        canvas.rect(self.screen, self.theme.accent, report_rect, border_radius=int(8 * s))
        self.screen.blit(report, (report_rect.centerx - report.get_width() // 2, report_rect.centery - report.get_height() // 2))
        self.hits.append(Hit(report_rect, lambda: webbrowser.open(ISSUE_URL)))

        old_clip = self.screen.get_clip()
        self.screen.set_clip(body)
        line_y = body.y - int(self.help_view)
        for (text, is_head), row_h in zip(rows, heights):
            if line_y + row_h >= body.y and line_y <= body.bottom:
                if is_head:
                    self.screen.blit(self._tracked(text, 15, self.theme.label, tracking=0.25), (body.x, line_y))
                elif text:
                    self.screen.blit(self._text(text, self._font(21), (206, 194, 178)), (body.x, line_y))
            line_y += row_h
        self.screen.set_clip(old_clip)
        if total > body.height:
            track_x = body.right + int(12 * s)
            thumb_h = max(int(40 * s), int(body.height * body.height / total))
            max_scroll = max(1, total - body.height)
            thumb_y = body.y + int((body.height - thumb_h) * min(1.0, self.help_view / max_scroll))
            self.screen.blit(draw.rounded_rect(max(2, int(4 * s)), body.height, 2 * s, (255, 255, 255, 18)), (track_x, body.y))
            self.screen.blit(draw.rounded_rect(max(2, int(4 * s)), thumb_h, 2 * s, MUTED), (track_x, thumb_y))
            self._scrollbar("help", pygame.Rect(track_x, body.y, max(2, int(4 * s)), body.height), thumb_h, max_scroll)

    def _draw_osk(self, now: float) -> None:
        s = self.s
        gap, pad = int(8 * s), int(30 * s)
        cols = max(len(r) for r in OSK_ROWS)
        # Docked over the details column so the list, and what matches, stays in view while typing.
        column = pygame.Rect(self.list_edge, 0, self.w - self.list_edge, self.h - self.footer_h)
        cell_w = min(int(76 * s), (column.width - 2 * self.margin - 2 * pad - (cols - 1) * gap) // cols)
        cell_h = min(int(64 * s), int(cell_w * 0.85))
        grid_w = cols * cell_w + (cols - 1) * gap
        grid_h = len(OSK_ROWS) * cell_h + (len(OSK_ROWS) - 1) * gap
        field_h = int(78 * s)
        box = pygame.Rect(0, 0, grid_w + 2 * pad, field_h + grid_h + 2 * pad)
        box.midbottom = (column.centerx, column.bottom - int(24 * s))

        self.screen.fill((125, 125, 125), column, special_flags=pygame.BLEND_MULT)
        shade = pygame.Rect(0, 0, self.w, self.h - self.footer_h)
        self.screen.blit(draw.rounded_rect(box.width, box.height, 18 * s, (*PANEL, 248), (78, 62, 55), 1.5 * s), box)
        self.hits.append(Hit(shade, self._act(Action.SEARCH)))  # click outside: done, keep the filter
        self.hits.append(Hit(box, lambda: None))

        fx, fy = box.x + pad, box.y + pad
        self.screen.blit(self._tracked(tr("hint.search"), 16, self.theme.label, tracking=0.3), (fx, fy))
        caret = "|" if int(now * 2) % 2 == 0 else " "
        field = self._text(self._fit(self.filter + caret, self._font(34), grid_w), self._font(34), TEXT)
        self.screen.blit(field, (fx, fy + int(22 * s)))
        canvas.rect(self.screen, self.theme.accent, (fx, fy + field_h - int(12 * s), grid_w, max(2, int(3 * s))))

        gy = fy + field_h
        pop = 1 + 0.07 * _ease_out((now - self.osk_moved) / 0.14)
        for r, row in enumerate(OSK_ROWS):
            row_cell_w = (grid_w - (len(row) - 1) * gap) // len(row)
            for c, key in enumerate(row):
                rect = pygame.Rect(fx + c * (row_cell_w + gap), gy + r * (cell_h + gap), row_cell_w, cell_h)
                self.hits.append(Hit(rect.inflate(gap, gap), lambda r=r, c=c: self._osk_click(r, c), lambda r=r, c=c: self._osk_hover(r, c)))
                selected = [r, c] == self.osk
                if selected:
                    big = rect.inflate(int(rect.width * (pop - 1)), int(rect.height * (pop - 1)))
                    self.screen.blit(draw.rounded_rect(big.width, big.height, 9 * s, self.theme.accent), big)
                else:
                    self.screen.blit(draw.rounded_rect(rect.width, rect.height, 9 * s, KEY_IDLE), rect)
                if len(key) == 1:
                    t = self._text(key, self._font(30, bold=True), TEXT if selected else MUTED)
                else:
                    t = self._tracked(tr(OSK_LABELS[key]), 15, TEXT if selected else (self.theme.label if key == "DONE" else MUTED), tracking=0.2)
                ink = t.get_bounding_rect()
                self.screen.blit(t, (rect.centerx - ink.centerx, rect.centery - ink.centery))

    # ---------- info sheet ----------

    def _info_tabs(self) -> list[int]:
        """The ENDOOM tab only exists for presets whose own files ship one."""
        return [0, ENDOOM_TAB] if self.endooms.get(self.current) else [0]

    def _endoom_surface(self, endoom: Endoom, max_w: int, max_h: int) -> pygame.Surface:
        key = (id(endoom), max_w, max_h)
        surf = self.endoom_cache.get(key)
        if surf is not None:
            return surf
        font = self._font(8, mono=True)
        for size in range(30, 7, -1):
            f = self._font(size, mono=True)
            if f.size("M")[0] * COLS <= max_w and f.get_linesize() * ROWS <= max_h:
                font = f
                break
        cw, ch = font.size("M")[0], font.get_linesize()
        surf = pygame.Surface((cw * COLS, ch * ROWS)).convert(_OPAQUE)
        glyphs: dict[tuple, pygame.Surface] = {}
        # Block and shade characters are ANSI art's pixels; as font glyphs they leave gaps between rows.
        blocks = {"█": (0, 0, 1, 1), "▀": (0, 0, 1, 0.5), "▄": (0, 0.5, 1, 0.5), "▌": (0, 0, 0.5, 1), "▐": (0.5, 0, 0.5, 1)}
        shades = {"░": 0.25, "▒": 0.5, "▓": 0.75}
        for col, row, c, fg, bg in endoom.cells():
            cell = pygame.Rect(col * cw, row * ch, cw, ch)
            if c in shades:
                k = shades[c]
                surf.fill(tuple(int(_lerp(bg[i], fg[i], k)) for i in range(3)), cell)
                continue
            surf.fill(bg, cell)
            if c in blocks:
                x, y, w, h = blocks[c]
                surf.fill(fg, (cell.x + round(x * cw), cell.y + round(y * ch), round(w * cw), round(h * ch)))
            elif c.strip():
                g = glyphs.get((c, fg))
                if g is None:
                    g = glyphs[(c, fg)] = font.render(c, True, fg)
                surf.blit(g, (cell.x + (cw - g.get_width()) // 2, cell.y))
        self.endoom_cache[key] = surf
        return surf

    def _info_layout(self) -> tuple[pygame.Rect, pygame.Rect]:
        """Sheet rect in screen space, body rect relative to the sheet."""
        s = self.s
        x = int(self.w * 0.5)
        sheet = pygame.Rect(x, self.margin, self.w - self.margin - x, self.h - self.footer_h - int(24 * s) - self.margin)
        pad, header_h = int(36 * s), int(92 * s)
        body = pygame.Rect(pad, header_h + int(18 * s), sheet.width - 2 * pad - int(18 * s), sheet.height - header_h - int(18 * s) - pad)
        return sheet, body

    def _info_font(self) -> pygame.font.Font:
        """Largest mono size that fits the readme's own width (80-100 columns), so its layout survives."""
        cols = 80
        readme = self.readmes.get(self.current) if self.info_tab == 0 else None
        if readme:
            if readme.width is None:
                # A couple of runaway lines shouldn't shrink the whole text; let those wrap.
                lengths = sorted(len(line) for line in readme.text.split("\n"))
                readme.width = lengths[int(len(lengths) * 0.98)] if lengths else 0
            cols = min(100, max(cols, readme.width))
        width = self._info_layout()[1].width
        for size in range(19, 13, -1):
            font = self._font(size, mono=True)
            if font.size("M")[0] * cols <= width:
                return font
        return self._font(14, mono=True)

    def _info_line_h(self) -> int:
        return int(self._info_font().get_linesize() * 1.12)

    def _info_visible_lines(self) -> int:
        return max(1, self._info_layout()[1].height // self._info_line_h())

    def _info_content(self) -> list[str]:
        mono = self._info_font()
        body = self._info_layout()[1]
        per_line = max(20, body.width // max(1, mono.size("M")[0]))
        key = (self.current, self.info_tab, per_line, self.current in self.readmes)
        if self.info_lines[0] == key:
            return self.info_lines[1]
        if self.info_tab == 0:
            readme = self.readmes.get(self.current)
            lines = _wrap_mono(readme.text, per_line) if readme else []
        else:
            lines = []  # ENDOOM is drawn as a picture and never scrolls
        self.info_lines = (key, lines)
        return lines

    def _info_max_scroll(self) -> float:
        return float(max(0, len(self._info_content()) - self._info_visible_lines()))

    def _draw_info(self, now: float) -> None:
        s = self.s
        rect, body = self._info_layout()
        t = _ease_out((now - self.info_opened) / INFO_SLIDE_SECONDS)

        shade = self._dim_backdrop(int(150 * t))

        sheet = draw.rounded_rect(rect.width, rect.height, 18 * s, (*PANEL, 250), (78, 62, 55), 1.5 * s).copy()
        pad = int(36 * s)
        tab_cy = int(48 * s)
        pad_mode = self.input.pad_mode
        left = self.glyphs.get("LB" if pad_mode else "KEY:LEFT")
        right = self.glyphs.get("RB" if pad_mode else "KEY:RIGHT")
        self.hits.append(Hit(shade, self._close_overlay))  # click outside the sheet closes it
        self.hits.append(Hit(rect, lambda: None))
        band = int(36 * s)

        def tab_hit(x0: int, width: int, click: Callable[[], None]) -> None:
            self.hits.append(Hit(pygame.Rect(rect.x + x0 - int(10 * s), rect.y + tab_cy - band, width + int(20 * s), 2 * band), click))

        x = pad
        tabs = self._info_tabs()
        if len(tabs) > 1:
            sheet.blit(left, (x, tab_cy - left.get_height() // 2))
            tab_hit(x, left.get_width(), self._act(Action.PREV_SECTION))
            x += left.get_width() + int(22 * s)
        tab_font = self._font(20, bold=True)
        for i in tabs:
            name = info_tabs()[i]
            active = i == self.info_tab
            label = self._tracked(name, 20, TEXT if active else DIM, tracking=0.22)
            sheet.blit(label, (x, self._text_top(tab_font, tab_cy)))
            tab_hit(x, label.get_width(), lambda i=i: self._set_info_tab(i))
            if active:
                pygame.draw.rect(sheet, self.theme.accent, (x, tab_cy + int(22 * s), label.get_width(), max(2, int(3 * s))))
            x += label.get_width() + int(34 * s)
        x -= int(12 * s)
        if len(tabs) > 1:
            sheet.blit(right, (x, tab_cy - right.get_height() // 2))
            tab_hit(x, right.get_width(), self._act(Action.NEXT_SECTION))

        endoom = self.endooms.get(self.current)
        # Opaque: draw.line on an alpha surface replaces pixels instead of blending, which would punch a see-through stripe.
        pygame.draw.line(sheet, (44, 37, 34), (pad, int(92 * s)), (rect.width - pad, int(92 * s)), max(1, int(s)))

        lines = self._info_content()
        if self.info_tab == ENDOOM_TAB and endoom:
            pic = self._endoom_surface(endoom, body.width, body.height)
            top = body.y + max(0, (body.height - pic.get_height()) * 2 // 5)
            sheet.blit(pic, (body.x + (body.width - pic.get_width()) // 2, top))
        elif not lines:
            msg = tr("info.looking") if self.info_tab == 0 and self.current not in self.readmes else tr("info.no_readme")
            sheet.blit(self._text(msg, self._font(24), MUTED), body.topleft)
        else:
            mono = self._info_font()
            line_h = self._info_line_h()
            first = int(self.info_view)
            frac = self.info_view - first
            sheet.set_clip(body)
            color = (214, 204, 190)
            for n in range(first, min(len(lines), first + self._info_visible_lines() + 2)):
                if lines[n].strip():
                    y = body.y + int((n - first - frac) * line_h)
                    sheet.blit(self._text(lines[n], mono, color), (body.x, y))
            sheet.set_clip(None)
            max_scroll = self._info_max_scroll()
            if max_scroll > 0:
                track_x = body.right + int(12 * s)
                tw = max(2, int(4 * s))
                thumb_h = max(int(40 * s), int(body.height * self._info_visible_lines() / len(lines)))
                thumb_y = body.y + int((body.height - thumb_h) * min(1.0, self.info_view / max_scroll))
                grabbed = self.drag is not None and self.drag[0] == "info"
                sheet.blit(draw.rounded_rect(tw, body.height, tw / 2, (255, 255, 255, 18)), (track_x, body.y))
                sheet.blit(draw.rounded_rect(tw, thumb_h, tw / 2, TEXT if grabbed else MUTED), (track_x, thumb_y))
                self._scrollbar("info", pygame.Rect(rect.x + track_x, rect.y + body.y, tw, body.height), thumb_h, max_scroll)

        sheet.set_alpha(int(255 * t))
        self.screen.blit(sheet, (rect.x + int(60 * s * (1 - t)), rect.y))

    def _draw_toast(self, now: float) -> None:
        if not self.toast:
            return
        age = now - self.toast.born
        if age > self.toast.ttl:
            self.toast = None
            return
        s = self.s
        alpha = min(1.0, age / 0.15) * min(1.0, (self.toast.ttl - age) / 0.6)
        t = self._text(self.toast.text, self._font(26), TEXT)
        dot = draw.disc(max(4, int(10 * s)), self.toast.color)
        pad_x, pad_y = int(24 * s), int(16 * s)
        w = dot.get_width() + int(14 * s) + t.get_width() + 2 * pad_x
        h = t.get_height() + 2 * pad_y
        surf = draw.rounded_rect(w, h, 12 * s, (*PANEL, 240), (70, 56, 50), 1.2 * s).copy()
        surf.blit(dot, (pad_x, (h - dot.get_height()) // 2))
        surf.blit(t, (pad_x + dot.get_width() + int(14 * s), self._text_top(self._font(26), h / 2)))
        surf.set_alpha(int(255 * alpha))
        slide = int(14 * s * (1 - _ease_out(age / 0.25)))
        self.screen.blit(surf, (self.w - self.margin - w, self.margin - slide))

    # ---------- loop ----------

    def run(self) -> int:
        clock = pygame.time.Clock()
        self._fps_clock = clock if show_fps() else None
        self._fps_hz = 0
        last = time.monotonic()
        try:
            while self.running:
                now = time.monotonic()
                if self.quit_at is not None and now >= self.quit_at:
                    self.running = False
                    break
                dt = now - last
                last = now

                for event in pygame.event.get():
                    if self._on_window_event(event):
                        continue
                    if event.type == pygame.DROPFILE:
                        self._on_drop(Path(event.file))
                        continue
                    actions = self.input.handle(event, now)
                    if event.type == pygame.KEYUP and event.key in (pygame.K_LCTRL, pygame.K_RCTRL):
                        self._release_ctrl(event.key, jump=now >= self.ignore_until)
                        continue
                    if now < self.ignore_until:
                        continue
                    if event.type in MOUSE_EVENTS:
                        self._on_mouse(event, now)
                        continue
                    if self.mouse_on and (actions or event.type == pygame.KEYDOWN):
                        self._mouse_off()
                    if event.type == pygame.KEYDOWN and self._on_key(event):
                        continue
                    if event.type == pygame.TEXTINPUT:
                        self._on_text(event.text, now)
                        continue
                    for action in actions:
                        self._on_action(action, now)
                        if not self.running:
                            break
                if now >= self.ignore_until:
                    for action in self.input.update(now):
                        if self.mouse_on:
                            self._mouse_off()
                        self._on_action(action, now, repeat=True)

                self.tick(now, dt)
                if self.hidden:
                    clock.tick(HIDDEN_FPS)  # minimized: keep music, art and update checks moving without painting
                    continue
                self._note_fps_target(self.refresh_hz)  # as many presents as the display takes; motion is in dt
                self._draw(now)
                self._flip()
                clock.tick(self._frame_cap())
        finally:
            self.art_pool.shutdown(wait=False, cancel_futures=True)
            if self.update_pool:
                self.update_pool.shutdown(wait=False, cancel_futures=True)
            if self.music:
                self.music.shutdown()
            self._close_window()
            pygame.quit()
            if self.update_handoff:
                os._exit(0)  # Py_Finalize is where the Intel quit abort happens; the helper only needs us gone
        return 0

    def tick(self, now: float, dt: float) -> None:
        self.dt = dt  # draws read this; the present rate never feeds a motion
        self._poll_whats_new(now)
        self._poll_update(now)
        self._update_art(now)
        self._update_music(now)
        if self.mode == "info":
            stick = max(self.input.right_y, self.input.left_y, key=abs) if now >= self.ignore_until else 0.0
            if stick:
                # Squared response: small tilts read line by line, full tilt flies.
                self.info_scroll += stick * abs(stick) * INFO_STICK_LINES_PER_SEC * dt
            self.info_scroll = max(0.0, min(self.info_scroll, self._info_max_scroll()))
            if stick:
                self.info_view = self.info_scroll
            else:
                self.info_view = _approach(self.info_view, self.info_scroll, 18, dt)
        elif self.mode == "help":
            stick = max(self.input.right_y, self.input.left_y, key=abs) if now >= self.ignore_until else 0.0
            if stick:
                self.help_scroll += stick * abs(stick) * INFO_STICK_LINES_PER_SEC * self._help_line_h() * dt
            self.help_scroll = max(0.0, min(self._help_max_scroll(), self.help_scroll))
            if stick:
                self.help_view = self.help_scroll
            else:
                self.help_view = _approach(self.help_view, self.help_scroll, 18, dt)
        if self.rows:
            self.scroll = _approach(self.scroll, self._target_scroll(), 14, dt)
            self.bar_y = _approach(self.bar_y, self.row_y[self._sel_row()], 20, dt)
