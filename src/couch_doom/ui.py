"""Fullscreen couch UI."""
from __future__ import annotations

import ctypes
import ctypes.util
import io
import math
import os
import sys
import time
import webbrowser
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pygame

from . import __version__, draw
from . import update as updates
from .config import ASSET_DIR
from . import filedialog
from .filedialog import open_file
from .gamepad import Action, Input
from .glyphs import BUTTON_NAMES, Glyphs
from .launch import LaunchCommand, build_command, load_order, presented_files, split_args
from . import log
from .log import closed_early, last_line, needs_extract_retry, spawn
from .launchers import Launchers
from .music import DWELL_SECONDS, MusicPlayer, find_soundfont
from .options import Options, OptionsError, Preset, unpack
from .endoom import COLS, ROWS, Endoom, find_endoom
from .readme import Readme, find_readme
from .sfx import Sfx
from .sources import SOURCES, Choice
from .state import State
from .theme import HOUSE, Theme, from_art
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

QUIT_CONFIRM_SECONDS = 2.0
LAUNCH_WIPE_SECONDS = 0.38
WINDOW_RETRIES = 20  # half a second apart
INPUT_COOLDOWN = 0.45
ART_FADE_SECONDS = 0.45
ART_CACHE_SIZE = 24
ART_MIN_FILL = 0.62  # of the art panel's height
ART_MAX_ZOOM = 1.25
FAVORITES = "Favorites"
INFO_TABS = ("Readme", "ENDOOM")
UPDATE_DELAY_SECONDS = 3.0  # let the list settle before a notice appears over it
# (key, label, caption) for the update notice; "later" is index 1 because B and a click outside both mean it.
UPDATE_CHOICES = (
    ("open", "Open release page", "Opens GitHub in your browser"),
    ("later", "Remind me later", "Ask again the next time CouchDoom starts"),
    ("skip", "Don't remind me again", "Stay quiet about {v}; a newer release will still show"),
)
ENDOOM_TAB = 1
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


def _ease_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


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


def _load_extras(preset: Preset) -> tuple[Art | None, Readme | None, Endoom | None, Art | None]:
    unpack(preset)
    files = load_order(preset)
    iwad, shown = presented_files(preset)
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
    try:
        endoom = find_endoom(files)
    except Exception:
        endoom = None
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


def _set_window_icon() -> None:
    """The exe's embedded icon only covers Explorer; the taskbar shows the window's own, which pygame
    leaves as its default. Windows also groups taskbar buttons by app ID, which would otherwise be python's."""
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("com.krisenigma.couchdoom")
        except (AttributeError, OSError):
            pass
    try:
        pygame.display.set_icon(pygame.image.load(str(ASSET_DIR / "icon.png")))
    except (pygame.error, FileNotFoundError):
        pass


def _wrap_mono(text: str, per_line: int) -> list[str]:
    """Hard-wrap preformatted text, breaking at a space when one is reasonably close."""
    out: list[str] = []
    for raw in text.split("\n"):
        raw = raw.rstrip()
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
        self.windowed = windowed
        self.problem = problem  # options.json missing/unreadable: the notice screen replaces the list
        self.launchers = launchers
        self.reload = reload or (launchers.load if launchers else None)
        self.picker: list[Choice | None] = []  # None is the "find it myself" row
        self.picker_sel = 0
        self.picker_opened = 0.0
        # A newer release, shown once as a notice: {"version", "current", "notes": [str], "url"}.
        self.update: dict | None = None
        self.update_sel = 1
        self.update_opened = 0.0
        self.update_choice: str | None = None
        self.update_job: Future | None = None
        self.update_pool: ThreadPoolExecutor | None = None
        self.update_started = 0.0
        self.soundfont_choice = soundfont

        _set_dpi_aware()
        if not windowed:
            os.environ.setdefault("SDL_VIDEO_WINDOW_POS", "0,0")
            # Stay on the current Space, like GZDoom's default fullscreen, so launching a game doesn't swipe between Spaces.
            os.environ.setdefault("SDL_VIDEO_MAC_FULLSCREEN_SPACES", "0")
        pygame.mixer.pre_init(44100, 32, 2, 1024)
        pygame.init()
        pygame.display.set_caption("CouchDoom")
        self.input = Input()

        self.soundfont = find_soundfont(opts, soundfont)
        self.music: MusicPlayer | None = None
        self.sfx: Sfx | None = None
        self._music_sel: int | None = None
        self._music_since = 0.0
        self._audio_up()

        self.commands: list[LaunchCommand] = [build_command(opts, p) for p in opts.presets]
        self.filter = ""
        self.mode = "list"  # "list" | "search" | "info"
        self.info_tab = 0
        self.info_scrolls = [0.0] * len(INFO_TABS)  # per-tab position, kept while the sheet is open
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
        self.row_offset: dict[tuple[bool, int], float] = {}

        self.art_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="titleart")
        self.art_jobs: dict[int, Future] = {}
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
        self._theme_bgs: dict[int, pygame.Surface] = {}
        self._theme_bars: dict[int, pygame.Surface] = {}
        self._theme_layers: dict[int, dict] = {}

        self.rows: list[Row] = []
        self.current = 0
        self.cur_row = -1  # a preset can appear twice (Favorites + its section); this says which copy
        self._pick_start()
        self._rebuild_rows()

        self._open_window()
        self.scroll = self._target_scroll()
        self.bar_y = self.row_y[self._sel_row()] if self.rows else 0
        self.detail_changed = time.monotonic()
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
            self._notify(f"Still the same: {exc.title[0].lower()}{exc.title[1:]}", ERROR)
            return
        self._apply(opts)

    def _apply(self, opts: Options) -> None:
        """Show a freshly loaded set of presets: a reload, or another launcher picked."""
        for job in self.art_jobs.values():
            job.cancel()
        for cache in (self.art_jobs, self.art_cache, self.readmes, self.endooms, self.logos, self.themes, self.row_offset):
            cache.clear()
        self.art_layers.clear()
        self.opts, self.problem = opts, None
        self.commands = [build_command(opts, p) for p in opts.presets]
        self._audio_down()  # sounds and SoundFont come from the engines and IWADs in the new settings
        self.soundfont = find_soundfont(opts, self.soundfont_choice)
        self._audio_up()
        self.filter = ""
        self._pick_start()
        self._rebuild_rows()
        self.scroll = self._target_scroll()
        self.bar_y = self.row_y[self._sel_row()] if self.rows else 0
        self.detail_changed = time.monotonic()
        if opts.presets:
            self._sound("open")
            source = f" from {opts.launcher}" if opts.launcher else ""
            self._notify(f"Loaded {len(opts.presets)} presets{source}", MUTED)
        else:
            self._sound("error")

    # ---------- launcher picker ----------

    def _open_picker(self) -> None:
        if not self.launchers:
            return
        choices = self.launchers.refresh()
        for c in choices:
            self.launchers.preview(c)  # the counts shown; loading here keeps the stall on the button press
        self.picker = [*choices, None] if filedialog.available() else list(choices)
        current = self.launchers.current
        self.picker_sel = next((i for i, c in enumerate(choices) if current and c.id == current.id), 0)
        self.picker_opened = time.monotonic()
        self.mode = "launcher"
        self._sound("open")

    def _on_picker_action(self, action: Action) -> None:
        if action in (Action.UP, Action.DOWN):
            step = -1 if action == Action.UP else 1
            sel = max(0, min(len(self.picker) - 1, self.picker_sel + step))
            if sel != self.picker_sel:
                self.picker_sel = sel
                self._sound("move")
        elif action in (Action.CONFIRM, Action.MENU):
            self._picker_pick(self.picker_sel)
        elif action in (Action.BACK, Action.LAUNCHER):
            self._close_overlay()

    def _picker_hover(self, i: int) -> None:
        if i != self.picker_sel:
            self.picker_sel = i
            self._sound("move")

    def _picker_pick(self, i: int) -> None:
        self.picker_sel = i
        choice = self.picker[i]
        if choice is None:
            self._browse()
            return
        current = self.launchers.current
        if current and choice.id == current.id and not self.problem:
            self._close_overlay()
            return
        self._choose(choice)

    # ---------- update notice ----------

    def _open_update(self, info: dict) -> None:
        self.update = info
        self.update_sel = 1  # "Remind me later": the safe default, and what B does
        self.update_choice = None
        self.update_opened = time.monotonic()
        self.mode = "update"
        self._sound("open")

    def _on_update_action(self, action: Action) -> None:
        if action in (Action.UP, Action.DOWN):
            sel = max(0, min(len(UPDATE_CHOICES) - 1, self.update_sel + (-1 if action == Action.UP else 1)))
            if sel != self.update_sel:
                self.update_sel = sel
                self._sound("move")
        elif action in (Action.CONFIRM, Action.MENU):
            self._update_pick(self.update_sel)
        elif action == Action.BACK:
            self._update_pick(1)

    def _update_hover(self, i: int) -> None:
        if i != self.update_sel:
            self.update_sel = i
            self._sound("move")

    def _update_pick(self, i: int) -> None:
        self.update_sel = i
        self.update_choice = UPDATE_CHOICES[i][0]
        info = self.update or {}
        if self.update_choice == "open" and info.get("url"):
            try:
                webbrowser.open(info["url"])
            except webbrowser.Error:
                pass
            # Counts as "later": if they don't update, the notice returns next launch.
        elif self.update_choice == "skip" and info.get("version"):
            self.state.skip_update(info["version"])
        self._close_overlay()

    def _start_update_check(self, now: float) -> None:
        if not self.state.update_check or updates.disabled():
            return
        self.update_started = now
        self.update_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="update")  # apart from the art pool: a slow network must not stall title art
        self.update_job = self.update_pool.submit(updates.check, __version__, self.state.update_skip)

    def _poll_update(self, now: float) -> None:
        """Show the notice once, a few seconds in, and only from the plain list so it never interrupts anything."""
        job = self.update_job
        if job is None or not job.done() or now - self.update_started < UPDATE_DELAY_SECONDS:
            return
        if self.mode != "list" or self.blocked or now < self.ignore_until:
            return
        self.update_job = None
        try:
            info = job.result()
        except Exception:
            info = None
        if info:
            self._open_update(info)

    def _choose(self, choice: Choice, added: bool = False) -> None:
        try:
            opts = self.launchers.choose(choice, added)
        except OptionsError as exc:
            self._notify(exc.title, ERROR)
            self._sound("error")
            return
        self.mode = "list"
        self._apply(opts)

    def _browse(self) -> None:
        patterns = ";".join([*(e for s in SOURCES for e in s.module.EXES), *(n for s in SOURCES for n in s.module.SETTINGS_NAMES), "*.zdl"])
        owner = pygame.display.get_wm_info().get("window")
        args = ("Find your Doom launcher", [("Doom launchers and their settings", patterns), ("All files", "*.*")], owner)
        if sys.platform == "darwin":
            # The dialog is another process; keep frames (and music) going or macOS shows this window as not responding.
            self._mouse_on()
            levels = _macos_window_levels()
            with ThreadPoolExecutor(1) as pool:
                job = pool.submit(open_file, *args)
                last = time.monotonic()
                while not job.done():
                    pygame.event.get()
                    now = time.monotonic()
                    self.tick(now, now - last)
                    self._draw(now)
                    self._flip()
                    last = now
                    time.sleep(1 / 60)
            path = job.result()
            if any(levels):
                _macos_window_levels(levels)
            self._mouse_off()
        else:
            path = open_file(*args)
        # The dialog swallowed the presses that closed it; don't let their releases act on the list.
        pygame.event.clear()
        self.input.reset()
        self.ignore_until = time.monotonic() + INPUT_COOLDOWN
        _force_foreground()
        if path:
            self._on_drop(path)

    def _on_drop(self, path: Path) -> None:
        """A file or folder dropped on the window, or picked in the dialog: use the launcher it belongs to."""
        if not self.launchers:
            return
        choice = self.launchers.add(path)
        if choice is None:
            exe = next((s for s in SOURCES if path.name.lower() in s.module.EXES), None)
            if exe:
                self._notify(f"{exe.name} hasn't saved any settings yet. Set up a game in it first.", ERROR)
            else:
                self._notify(f"{path.name} isn't a Doom launcher, its settings, or GZDoom/UZDoom/VKDoom", ERROR)
            self._sound("error")
            return
        self._choose(choice, added=True)

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

    def _sound(self, name: str) -> None:
        if self.sfx:
            self.sfx.play(name)

    def _update_music(self, now: float) -> None:
        if not self.music:
            return
        self.music.update()
        if self.current != self._music_sel:
            self._music_sel, self._music_since = self.current, now
        if not self.state.music or not self.rows:
            self.music.request(None)
        elif self.music.want == self.current:
            pass  # playing, loading, or finished; title tracks play once, like on the engine's title screen
        elif now - self._music_since >= DWELL_SECONDS:
            p = self.opts.presets[self.current]
            self.music.request(self.current, *presented_files(p))
        # While the selection is still moving, the current track plays on: the next preset may share it.

    def _toggle_music(self) -> None:
        on = not self.state.music
        self.state.set_music(on)
        self._music_sel = None
        self._sound("open" if on else "close")
        self._notify("Title music on" if on else "Title music off", MUTED)

    def _toggle_favorite(self) -> None:
        if not self.rows:
            return
        sel = self._sel_row()
        was_fav, old_y = self.rows[sel].fav, self.row_y[sel]
        on = self.state.toggle_favorite(self.opts.presets[self.current].name)
        self._rebuild_rows()
        copies = [i for i, r in enumerate(self.rows) if r.kind == "preset" and r.preset == self.current]
        if copies:
            self.cur_row = next((i for i in copies if self.rows[i].fav == was_fav), copies[0])
            # Rows above may have appeared or vanished; shift the view with them so the cursor stays put.
            shift = self.row_y[self.cur_row] - old_y
            self.scroll += shift
            self.bar_y += shift
        self._sound("open" if on else "close")
        self._notify("Added to Favorites" if on else "Removed from Favorites", self.theme.label if on else MUTED)

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
                pygame.display.quit()
                pygame.display.init()
                pygame.display.set_caption("CouchDoom")

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
            self.screen = self.window.get_surface()
            self.dpi = self.screen.get_width() / self.window.size[0]
        elif self.windowed:
            self.screen = pygame.display.set_mode(size)
        else:
            self.screen = pygame.display.set_mode(size, pygame.NOFRAME)
        self._mouse_off()
        pygame.key.start_text_input()
        self._layout()
        _force_foreground()

    def _flip(self) -> None:
        if self.window is not None:
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
            self.art_cache.clear()
            self.art_layers.clear()
            self.logos.clear()

    def _background_for(self, theme: Theme) -> pygame.Surface:
        bg = self._theme_bgs.get(theme.key)
        if bg is None:
            bg = self._theme_bgs[theme.key] = self._make_background(theme)
        return bg

    def _bar_for(self, theme: Theme) -> pygame.Surface:
        bar = self._theme_bars.get(theme.key)
        if bar is None:
            w = self.list_rect.width + int(28 * self.s)
            left, right = theme.bar
            bar = self._theme_bars[theme.key] = draw.horizontal_ramp(w, self.preset_h, (*left, 240), (*right, 0), curve=1.3)
        return bar

    def _make_background(self, theme: Theme) -> pygame.Surface:
        bg = pygame.Surface((self.w, self.h)).convert(_OPAQUE)
        top, bottom = theme.bg_top, theme.bg_bottom
        for y in range(self.h):
            t = (y / max(1, self.h - 1)) ** 1.6
            pygame.draw.line(bg, [int(_lerp(top[i], bottom[i], t)) for i in range(3)], (0, y), (self.w, y))
        lines = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        step = max(3, int(4 * self.s))
        for y in range(0, self.h, step):
            pygame.draw.line(lines, (0, 0, 0, 30), (0, y), (self.w, y))
        bg.blit(lines, (0, 0))
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
        layers = self._theme_layers.get(theme.key)
        if layers is None:
            bg = self._background_for(theme)
            layers = {"bg": (bg, (0, 0))}
            for name, (rect, mask) in self._masks.items():
                layers[name] = (self._bg_overlay(bg, rect, mask), rect.topleft)
            self._theme_layers[theme.key] = layers
        return layers

    def _blit_layer(self, name: str) -> None:
        """Mid-change, the old theme's layer goes down first and the new one fades in over it."""
        surf, pos = self._layers_for(self.theme)[name]
        if self.theme_from is None:
            self.screen.blit(surf, pos)
            return
        self.screen.blit(self._layers_for(self.theme_from)[name][0], pos)
        surf.set_alpha(int(255 * self.theme_t))
        self.screen.blit(surf, pos)
        _reset_alpha(surf)

    def _update_theme(self, now: float) -> None:
        """Follow the title art on screen; the background crossfades in step with the art itself."""
        if not self.art_layers:
            return
        idx, surf, born = self.art_layers[-1]
        target = self.themes.get(idx, HOUSE) if surf is not None else HOUSE
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
            rows.append(Row("header", FAVORITES, count=len(favs)))
            rows += [Row("preset", self.opts.presets[i].name, i, fav=True) for i in favs]
        for section in self.opts.sections:
            hits = [i for i, p in enumerate(self.opts.presets) if p.section == section and self._matches(i, terms)]
            if hits:
                rows.append(Row("header", section, count=len(hits)))
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

    def _sel_row(self) -> int:
        if 0 <= self.cur_row < len(self.rows) and self.rows[self.cur_row].preset == self.current:
            return self.cur_row
        for i, r in enumerate(self.rows):
            if r.kind == "preset" and r.preset == self.current:
                return i
        return 0

    def _select_row(self, row: int) -> None:
        if 0 <= row < len(self.rows) and self.rows[row].kind == "preset":
            self.cur_row = row
            if self.rows[row].preset != self.current:
                self.current = self.rows[row].preset
                self.detail_changed = time.monotonic()
                self._sound("move")

    def _move(self, delta: int) -> None:
        rows = self._preset_rows()
        if not rows:
            return
        self.free_scroll = None
        sel = self._sel_row()
        pos = rows.index(sel) if sel in rows else 0
        self._select_row(rows[max(0, min(len(rows) - 1, pos + delta))])

    def _jump_section(self, direction: int) -> None:
        headers = [i for i, r in enumerate(self.rows) if r.kind == "header"]
        if not headers:
            return
        self.free_scroll = None
        sel = self._sel_row()
        current_header = max((h for h in headers if h < sel), default=headers[0])
        if direction < 0:
            if sel > current_header + 1:
                self._select_row(current_header + 1)
                return
            prev = [h for h in headers if h < current_header]
            target = prev[-1] if prev else current_header
        else:
            nxt = [h for h in headers if h > current_header]
            if not nxt:
                return
            target = nxt[0]
        self._select_row(target + 1)

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

    def _set_filter(self, text: str) -> None:
        self.filter = text
        self._rebuild_rows()
        self.detail_changed = time.monotonic()

    # ---------- title art ----------

    def _request_art(self, idx: int) -> None:
        if idx in self.art_cache or idx in self.art_jobs or not (0 <= idx < len(self.opts.presets)):
            return
        self.art_jobs[idx] = self.art_pool.submit(_load_extras, self.opts.presets[idx])

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

    def _art_surface(self, idx: int, art: Art | None) -> pygame.Surface | None:
        if art is None:
            return None
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
        doom_lines = h in (200, 400)
        aspect = 1.2 if doom_lines else 1.0
        # Ultrawide title art (KEX's 560x200, Axolotl's 854x200) pads its sides for wider-than-16:9
        # displays; the 16:9 centre is what authors compose for. A 4:3 crop would go too far: Master
        # Levels, MyHouse and Technicolor put their logos out past it.
        width_169 = round(h * aspect * 16 / 9)
        if w > width_169:
            img = img.subsurface(pygame.Rect((w - width_169) // 2, 0, width_169, h)).copy()
            w = width_169
        if idx not in self.themes:
            self.themes[idx] = from_art(img)
        tw, th = self.art_rect.size
        # Fit the width; art that's still short after that may zoom up to 25% so it isn't a thin strip.
        # Short art dissolves at the bottom.
        scale = tw / w
        if h * aspect * scale < th * ART_MIN_FILL:
            scale = min(th * ART_MIN_FILL / (h * aspect), scale * ART_MAX_ZOOM)
        size = (int(w * scale) + 1, int(h * aspect * scale) + 1)
        scaled = pygame.transform.scale(img, size) if w <= 640 else pygame.transform.smoothscale(img, size)
        out = pygame.Surface((tw, th)).convert(_OPAQUE)
        out.blit(self._background_for(self.themes[idx]), (0, 0), self.art_rect)  # its own theme, for short art
        crop = scaled.subsurface(pygame.Rect((size[0] - tw) // 2, max(0, (size[1] - th) // 3), tw, min(th, size[1])))
        if crop.get_height() < th:
            # Art shorter than the panel: dissolve its bottom edge instead of leaving a hard line.
            crop = crop.convert_alpha()
            crop.blit(self._alpha_mask(crop.get_size(), lambda u, v: 1 - _smoothstep((v - 0.55) / 0.45)), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        out.blit(crop, (0, 0))
        return out

    def _update_art(self, now: float) -> None:
        near = {self.current, *self._neighbors()}
        for idx, job in list(self.art_jobs.items()):
            if job.done():
                try:
                    art, readme, endoom, logo = job.result()
                except Exception:
                    art, readme, endoom, logo = None, None, None, None
                self.art_cache[idx] = self._art_surface(idx, art)
                self.logos[idx] = self._logo_surface(logo)
                self.readmes[idx] = readme
                self.endooms[idx] = endoom
                while len(self.art_cache) > ART_CACHE_SIZE:
                    self.art_cache.popitem(last=False)
                del self.art_jobs[idx]
            elif idx not in near and job.cancel():
                del self.art_jobs[idx]
        self._request_art(self.current)
        for idx in self._neighbors():
            self._request_art(idx)

        if self.current in self.art_cache and (not self.art_layers or self.art_layers[-1][0] != self.current):
            self.art_cache.move_to_end(self.current)
            self.art_layers.append((self.current, self.art_cache[self.current], now))
            self.art_layers = self.art_layers[-2:]

    def _neighbors(self) -> list[int]:
        rows = self._preset_rows()
        sel = self._sel_row()
        if sel not in rows:
            return []
        pos = rows.index(sel)
        return [self.rows[rows[p]].preset for p in (pos - 1, pos + 1) if 0 <= p < len(rows)]

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

    # ---------- actions ----------

    def _notify(self, text: str, color=TEXT) -> None:
        self.toast = Toast(text, color, time.monotonic())

    def _on_action(self, action: Action, now: float) -> None:
        if self.mode == "launcher":
            self._on_picker_action(action)
            return
        if self.mode == "update":
            self._on_update_action(action)
            return
        if action == Action.LAUNCHER:
            if self.mode == "list":
                self._open_picker()
            return
        if self.blocked:
            if action in (Action.CONFIRM, Action.MENU):
                if self.launchers and self.launchers.must_pick:
                    self._open_picker()  # several launchers found and none picked yet: reloading can't help
                else:
                    self._reload()
            elif action == Action.BACK:
                self.running = False  # nothing to lose here, so no press-twice guard
            return
        if action == Action.MUSIC:
            self._toggle_music()
            return
        if action == Action.FAVORITE:
            if self.mode == "list":  # not in the info sheet: R3 is a click of the stick that scrolls it
                self._toggle_favorite()
            return
        if self.mode == "search":
            self._on_search_action(action, now)
            return
        if self.mode == "info":
            self._on_info_action(action, now)
            return
        if action == Action.UP:
            self._move(-1)
        elif action == Action.DOWN:
            self._move(1)
        elif action == Action.PAGE_UP:
            self._move(-8)
        elif action == Action.PAGE_DOWN:
            self._move(8)
        elif action in (Action.LEFT, Action.PREV_SECTION):
            self._jump_section(-1)
        elif action in (Action.RIGHT, Action.NEXT_SECTION):
            self._jump_section(1)
        elif action in (Action.CONFIRM, Action.MENU):
            self._launch_selected()
        elif action == Action.ALT:
            if self.rows:
                self.mode = "info"
                self.info_scroll = self.info_view = 0.0
                self.info_scrolls = [0.0] * len(INFO_TABS)
                self.info_tab = 0
                self.info_opened = now
                self._sound("open")
        elif action == Action.SEARCH:
            self._open_search(now)
        elif action == Action.BACK:
            if self.filter:
                self._set_filter("")
                self._sound("close")
            else:
                self._arm_quit(now, self._button_name("B") if self.input.pad_mode else "Esc")

    def _button_name(self, button: str) -> str:
        return BUTTON_NAMES[self.input.family].get(button, button)

    def _open_search(self, now: float) -> None:
        self.mode = "search"
        self.osk = [1, 0]
        self.osk_moved = now
        self._sound("open")

    def _close_overlay(self) -> None:
        self.mode = "list"
        self._sound("close")

    def _arm_quit(self, now: float, button: str) -> None:
        if now < self.quit_armed_until:
            self.running = False
        else:
            self.quit_armed_until = now + QUIT_CONFIRM_SECONDS
            self._notify(f"Press {button} again to quit", self.theme.label)
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
        elif action in (Action.CONFIRM, Action.MENU):
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
        return self.scroll if kind == "list" else self.info_view

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
        else:
            self.info_scroll = self.info_view = value

    def _click_row(self, row: int) -> None:
        """First click selects (title art and music follow), a click on the selected preset plays it."""
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
        elif action == Action.MENU:
            self.mode = "list"
            self._launch_selected()
        elif action == Action.BACK:
            self._set_filter("")
            self._close_overlay()

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

    def _on_key(self, event: pygame.event.Event) -> bool:
        """Keyboard-only behaviour that does not map onto pad actions. Returns True if consumed."""
        if self.mode == "info":
            return False
        if event.key == pygame.K_BACKSPACE:
            self._set_filter(self.filter[:-1])
            return True
        if self.mode == "search" and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._close_overlay()
            return True
        return False

    def _on_text(self, text: str, now: float) -> None:
        if self.mode == "info":
            return
        if text == "/" and self.mode == "list":
            self._open_search(now)
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
            self._notify(cmd.issues[0], ERROR)
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
        try:
            proc = spawn(cmd.argv, cmd.cwd, cmd.env, preset.name, cmd.display())
        except OSError as exc:
            self._notify(f"Could not start: {exc}", ERROR)
            self._sound("error")
            return
        self.state.record(preset.name)
        # Spawn before hiding so the engine inherits foreground rights.
        if self.window is not None:
            self.window.destroy()
            self.window = None
        pygame.display.quit()
        self._audio_down()
        self.input.suspend()
        code, elapsed = proc.wait()
        if needs_extract_retry(cmd.argv, cmd.env, proc.output, code, elapsed):
            # No FUSE on this system: run the AppImage by unpacking it instead, and say so in the log.
            retry = {**cmd.env, "APPIMAGE_EXTRACT_AND_RUN": "1"}
            try:
                proc = spawn(cmd.argv, cmd.cwd, retry, preset.name + " (retry without FUSE)", cmd.display())
                code, elapsed = proc.wait()
            except OSError:
                pass

        self._audio_up()
        self.input.resume()
        pygame.display.init()
        pygame.display.set_caption("CouchDoom")
        self._open_window()
        pygame.event.clear()
        self.input.reset()
        self.ignore_until = time.monotonic() + INPUT_COOLDOWN
        self.scroll = self._target_scroll()
        self.bar_y = self.row_y[self._sel_row()]
        if closed_early(code, elapsed):
            why = last_line(proc.output)
            self._notify(f"{preset.name} closed right away (exit {code})" + (f": {why}" if why else ". Details are in couch-doom.log"), ERROR)
        else:
            self._notify(f"Back from {preset.name}", MUTED)

    def _play_wipe(self, name: str) -> None:
        clock = pygame.time.Clock()
        start = time.monotonic()
        label = self._tracked(f"LOADING   {name}", 40, self.theme.bg_top, bold=True, tracking=0.08)
        while (t := (time.monotonic() - start) / LAUNCH_WIPE_SECONDS) < 1:
            pygame.event.pump()
            self._draw(time.monotonic())
            e = _ease_out(t)
            wipe_w = int(self.w * e)
            slant = int(160 * self.s)
            pygame.draw.polygon(self.screen, self.theme.accent, [(0, 0), (wipe_w + slant, 0), (wipe_w, self.h), (0, self.h)])
            visible = max(0, wipe_w - self.margin)
            self.screen.blit(label, (self.margin, self.h // 2 - label.get_height() // 2), pygame.Rect(0, 0, visible, label.get_height()))
            self._flip()
            clock.tick(60)
        self.screen.fill(self.theme.accent)
        self.screen.blit(label, (self.margin, self.h // 2 - label.get_height() // 2))
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
    def _fit(text: str, font: pygame.font.Font, max_w: int) -> str:
        if font.size(text)[0] <= max_w:
            return text
        while text and font.size(text + "…")[0] > max_w:
            text = text[:-1]
        return text.rstrip() + "…"

    @staticmethod
    def _wrap(text: str, font: pygame.font.Font, max_w: int, max_lines: int) -> list[str]:
        lines, line = [], ""
        for word in text.split():
            trial = f"{line} {word}".strip()
            if font.size(trial)[0] <= max_w:
                line = trial
            else:
                if line:
                    lines.append(line)
                line = word
        if line:
            lines.append(line)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = App._fit(lines[-1] + " …", font, max_w)
        return lines

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
                more = f"{sep}+{rest} more"
                while line and font.size(line + more)[0] > max_w:
                    line = line.rsplit(sep, 1)[0] if sep in line else ""
                    rest += 1
                    more = f"{sep}+{rest} more"
                lines.append(line + more if line else f"+{rest} more")
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
            self._draw_osk(now)
        elif self.mode == "info":
            self._draw_info(now)
        elif self.mode == "launcher":
            self._draw_picker(now)
        elif self.mode == "update":
            self._draw_update(now)
        self._draw_toast(now)

    def _draw_header(self) -> None:
        s, m = self.s, self.margin
        brand_font = self._font(88, bold=True)
        brand = self._shadowed("COUCH DOOM", brand_font, TEXT)
        brand_pos = (m - int(4 * s), m - int(18 * s))
        self.screen.blit(brand, brand_pos)
        ver = self._tracked(f"v{__version__}", 14, DIM, tracking=0.2)
        baseline = brand_pos[1] + brand_font.get_ascent()
        self.screen.blit(ver, (brand_pos[0] + brand.get_width() + int(10 * s), baseline - self._font(14, bold=True).get_ascent()))
        stripe_y = m + brand.get_height() - int(14 * s)
        pygame.draw.rect(self.screen, self.theme.accent, (m, stripe_y, int(150 * s), int(7 * s)))
        tag = self._tracked(f"From {self.opts.launcher}" if self.opts.launcher else "Couch launcher", 18, self.theme.accent, tracking=0.3)
        tag_pos = (m + int(168 * s), stripe_y + int(4 * s) - tag.get_height() // 2)
        self.screen.blit(tag, tag_pos)
        if self.launchers and self.mode == "list":
            self.hits.append(Hit(tag.get_rect(topleft=tag_pos).inflate(int(24 * s), int(20 * s)), self._open_picker))

        if self.blocked:
            return
        total = len(self.opts.presets)
        shown = sum(1 for r in self.rows if r.kind == "preset" and not r.fav)
        number = self._shadowed(str(shown) if not self.filter else f"{shown} / {total}", self._font(44, bold=True), TEXT)
        label = self._tracked("presets" if not self.filter else "matching", 17, MUTED, tracking=0.3)
        right = self.w - m
        self.screen.blit(number, (right - number.get_width(), m - int(10 * s)))
        self.screen.blit(label, (right - label.get_width(), m - int(10 * s) + number.get_height()))

        if self.filter or self.mode == "search":
            fy = self.list_rect.top - int(64 * s)
            lab = self._tracked("Filter", 17, self.theme.label, tracking=0.3)
            self.screen.blit(lab, (m, fy + int(12 * s)))
            caret = "_" if self.mode == "search" and int(time.monotonic() * 2) % 2 == 0 else ""
            value = self._text((self.filter + caret) or " ", self._font(32), TEXT)
            self.screen.blit(value, (m + lab.get_width() + int(20 * s), fy))

    def _draw_notice(self) -> None:
        """Stands in for list and details when there's nothing to pick: say what's wrong and how to fix it."""
        s, m = self.s, self.margin
        pick = "L3" if self.input.pad_mode else "F4"
        if self.problem:
            title, detail, paths = self.problem.title, self.problem.detail, self.problem.tried
            if self.problem.hint:
                hint = self.problem.hint.format(pick=pick)
            elif len(paths) > 1:
                hint = ("Set up a game in DoomRunner, ZDL or Doom Launcher so it saves its settings, or install GZDoom "
                        f"with an IWAD, then reload. Using a portable one that isn't listed? Press {pick} to point CouchDoom at it.")
            else:
                who = self.problem.launcher or "the launcher"
                hint = f"If {who} was saving, reload. Otherwise open {who} and check its settings."
        else:
            who = self.opts.launcher or "The launcher"
            title, detail, paths = "No presets yet", f"{who}'s settings have no presets in them:", [self.opts.path]
            hint = f"Create presets in {who}, then reload."
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
        pygame.draw.rect(self.screen, self.theme.accent, (m, y, int(56 * s), max(2, int(3 * s))))
        y += int(22 * s)
        for line in self._wrap(hint, self._font(25), min(width, int(1100 * s)), 3):
            self.screen.blit(self._text(line, self._font(25), (206, 194, 178)), (m, y))
            y += int(36 * s)

    def _draw_list(self, now: float) -> None:
        lr, s = self.list_rect, self.s
        if not self.rows:
            msg = self._text("No presets match that filter.", self._font(32), MUTED)
            self.screen.blit(msg, (lr.x, lr.y + int(20 * s)))
            return

        prev_clip = self.screen.get_clip()
        self.screen.set_clip(pygame.Rect(lr.x - int(28 * s), lr.y, self.list_edge - lr.x + int(28 * s), lr.height))
        bar_x = lr.x - int(28 * s)
        bar_top = lr.y + int(self.bar_y - self.scroll)
        self.screen.blit(self.bar_surface, (bar_x, bar_top))
        pulse = 0.82 + 0.18 * math.sin(now * 3.2)
        stripe = tuple(int(c * pulse) for c in self.theme.accent)
        pygame.draw.rect(self.screen, stripe, (bar_x, bar_top, int(6 * s), self.preset_h))

        name_font = self._font(33)
        sel_font = self._font(33, bold=True)
        sel = self._sel_row()
        k = min(1.0, (1 / 60) * 16)
        for i, row in enumerate(self.rows):
            y = lr.y + self.row_y[i] - int(self.scroll)
            h = self.header_h if row.kind == "header" else self.preset_h
            if y + h < lr.y or y > lr.bottom:
                continue
            if row.kind == "preset":
                area = pygame.Rect(bar_x, y, self.list_edge - self.scroll_w - bar_x, h).clip(lr.x - int(28 * s), lr.y, self.w, lr.height)
                self.hits.append(Hit(area, lambda i=i: self._click_row(i)))
            if row.kind == "header":
                t = self._tracked(row.text, 18, self.theme.label, tracking=0.22)
                ty = y + h - t.get_height() - int(12 * s)
                self.screen.blit(t, (lr.x, ty))
                cnt = self._text(str(row.count), self._font(18, bold=True), DIM)
                self.screen.blit(cnt, (lr.x + t.get_width() + int(14 * s), ty + (t.get_height() - cnt.get_height()) // 2))
                continue

            selected = i == sel
            target = 16 * s if selected else 0.0
            key = (row.fav, row.preset)
            off = self.row_offset[key] = _lerp(self.row_offset.get(key, 0.0), target, k)
            ok = self.commands[row.preset].ok
            color = TEXT if selected else (MUTED if ok else DIM)
            right_pad = 0
            if row.text == self.state.last_played:
                tag = self._tracked("Last", 15, self.theme.label if selected else DIM, tracking=0.25)
                self.screen.blit(tag, (lr.right - tag.get_width(), self._text_top(self._font(15, bold=True), y + h / 2)))
                right_pad = tag.get_width() + int(16 * s)
            if not ok:
                warn = self._tracked("Missing", 15, ERROR, tracking=0.25)
                self.screen.blit(warn, (lr.right - right_pad - warn.get_width(), self._text_top(self._font(15, bold=True), y + h / 2)))
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

        self.screen.set_clip(prev_clip)
        if self.scroll > 1:
            self._blit_layer("top")
        max_scroll = self.content_h - lr.height
        if self.scroll < max_scroll - 1:
            self._blit_layer("bottom")

        if max_scroll > 0:
            tw = self.scroll_w
            track_x = self.list_edge - tw
            thumb_h = max(int(48 * s), int(lr.height * lr.height / self.content_h))
            thumb_y = lr.y + int((lr.height - thumb_h) * (self.scroll / max_scroll))
            grabbed = self.drag is not None and self.drag[0] == "list"
            self.screen.blit(draw.rounded_rect(tw, lr.height, tw / 2, (255, 255, 255, 18)), (track_x, lr.y))
            self.screen.blit(draw.rounded_rect(tw, thumb_h, tw / 2, TEXT if grabbed else MUTED), (track_x, thumb_y))
            self._scrollbar("list", pygame.Rect(track_x, lr.y, tw, lr.height), thumb_h, max_scroll)

    def _draw_detail(self, now: float) -> None:
        if not self.rows:
            return
        dr, s = self.detail_rect, self.s
        w = dr.width
        preset = self.opts.presets[self.current]
        cmd = self.commands[self.current]
        engine = self.opts.engine_for(preset)
        blocks: list[tuple[pygame.Surface, int]] = []  # (surface, gap after)

        blocks.append((self._tracked(preset.section, 18, self.theme.label, tracking=0.22), int(10 * s)))
        title_font = self._font(64, bold=True)
        lines = self._wrap(preset.name, title_font, w, 3)
        readme = self.readmes.get(self.current)
        byline = " · ".join(x for x in ((f"by {readme.author}" if readme.author else ""), readme.year) if x) if readme else ""
        blurb = readme.blurb if readme else ""
        title_gap = int(8 * s) if byline or blurb else int(26 * s)
        logo = self.logos.get(self.current)
        if logo:
            blocks.append((logo, title_gap + int(10 * s)))
        else:
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
        font = self._font(17)
        row_h = int(24 * s)
        meta_lines = self._wrap_items(items, font, w, 2)
        meta = pygame.Surface((w, len(meta_lines) * row_h), pygame.SRCALPHA)
        for n, line in enumerate(meta_lines):
            meta.blit(self._text(line, font, DIM), (0, n * row_h))
        blocks.append((meta, int(22 * s)))
        label_gap = int(30 * s)

        if cmd.issues:
            font = self._font(24)
            issues = cmd.issues[:3]
            surf = pygame.Surface((w, label_gap + len(issues) * int(32 * s)), pygame.SRCALPHA)
            surf.blit(self._tracked("Problems", 16, ERROR, tracking=0.25), (0, 0))
            for n, issue in enumerate(issues):
                surf.blit(self._text(self._fit(issue, font, w), font, ERROR), (0, label_gap + n * int(32 * s)))
            blocks.append((surf, int(26 * s)))

        total = sum(b.get_height() + gap for b, gap in blocks) - blocks[-1][1]
        panel = pygame.Surface(dr.size, pygame.SRCALPHA)
        y = max(0, dr.height - total)
        for surf, gap in blocks:
            panel.blit(surf, (0, y))
            y += surf.get_height() + gap

        t = _ease_out((now - self.detail_changed) / 0.3)
        panel.set_alpha(int(255 * t))
        self.screen.blit(panel, (dr.x + int(32 * s * (1 - t)), dr.y))

    def _footer_hints(self) -> list[tuple[tuple[str, ...], str, tuple[Action, ...]]]:
        """(glyphs, label, actions): one action for the whole hint, or one per glyph (LB = previous, RB = next)."""
        pad = self.input.pad_mode
        A = Action
        launcher = [(("L3",) if pad else ("KEY:F4",), "Launcher", (A.LAUNCHER,))] if self.launchers else []
        if self.mode == "launcher":
            return [(("A",) if pad else ("KEY:ENTER",), "Choose", (A.CONFIRM,)), (("B",) if pad else ("KEY:ESC",), "Close", (A.BACK,))]
        if self.mode == "update":
            return [(("A",) if pad else ("KEY:ENTER",), "Choose", (A.CONFIRM,)), (("B",) if pad else ("KEY:ESC",), "Later", (A.BACK,))]
        if self.blocked:
            picking = self.launchers is not None and self.launchers.must_pick
            reload = [(("A",) if pad else ("KEY:ENTER",), "Choose" if picking else "Reload", (A.CONFIRM,))]
            return [*(reload if self.reload else []), *([] if picking else launcher), (("B",) if pad else ("KEY:ESC",), "Quit", (A.BACK,))]
        music = "Mute" if self.state.music else "Music"
        if self.mode == "search":
            if pad:
                return [(("A",), "Type", (A.CONFIRM,)), (("X",), "Delete", (A.ALT,)), (("Y",), "Done", (A.SEARCH,)), (("B",), "Cancel", (A.BACK,))]
            return [(("KEY:A-Z",), "Type", ()), (("KEY:BKSP",), "Delete", (A.ALT,)), (("KEY:ENTER",), "Done", (A.SEARCH,)),
                    (("KEY:ESC",), "Cancel", (A.BACK,))]
        # A prompt shown elsewhere on screen (the sheet's tab glyphs) is not repeated here.
        if self.mode == "info":
            scrolls = self._info_max_scroll() > 0
            if pad:
                scroll = [(("RS",), "Scroll", ()), (("LT", "RT"), "Page", (A.PAGE_UP, A.PAGE_DOWN))] if scrolls else []
                return [(("A",), "Play", (A.CONFIRM,)), *scroll, (("B",), "Close", (A.BACK,))]
            scroll = [(("KEY:UP", "KEY:DOWN"), "Scroll", (A.UP, A.DOWN))] if scrolls else []
            return [(("KEY:ENTER",), "Play", (A.CONFIRM,)), *scroll, (("KEY:ESC",), "Close", (A.BACK,))]
        fav = "Unfavorite" if self.rows and self.opts.presets[self.current].name in self.state.favorites else "Favorite"
        back = ("Clear filter" if self.filter else "Quit", (A.BACK,))
        section = (A.PREV_SECTION, A.NEXT_SECTION)
        if pad:
            return [(("A",), "Play", (A.CONFIRM,)), (("X",), "Info", (A.ALT,)), (("Y",), "Search", (A.SEARCH,)),
                    (("LB", "RB"), "Section", section), (("R3",), fav, (A.FAVORITE,)), (("BACK",), music, (A.MUSIC,)),
                    *launcher, (("B",), *back)]
        return [(("KEY:ENTER",), "Play", (A.CONFIRM,)), (("KEY:TAB",), "Info", (A.ALT,)), (("KEY:/",), "Search", (A.SEARCH,)),
                (("KEY:LEFT", "KEY:RIGHT"), "Section", section), (("KEY:F3",), fav, (A.FAVORITE,)),
                (("KEY:F2",), music, (A.MUSIC,)), *launcher, (("KEY:ESC",), *back)]

    def _draw_footer(self) -> None:
        s = self.s
        top = self.h - self.footer_h
        band = pygame.Surface((self.w, self.footer_h), pygame.SRCALPHA)
        band.fill((8, 6, 5, 150))
        pygame.draw.line(band, (255, 255, 255, 14), (0, 0), (self.w, 0))
        self.screen.blit(band, (0, top))

        cy = top + self.footer_h // 2
        x = self.margin
        font = self._font(23)
        gap = int(38 * s)
        for specs, label, actions in self._footer_hints():
            start = x
            g = self.glyphs.row(specs)
            self.screen.blit(g, (x, cy - g.get_height() // 2))
            x += g.get_width() + int(12 * s)
            t = self._text(label, font, MUTED)
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

    def _draw_picker(self, now: float) -> None:
        s = self.s
        t = _ease_out((now - self.picker_opened) / 0.25)
        pad, row_h, head_h, note_h = int(34 * s), int(84 * s), int(104 * s), int(58 * s)
        width = min(self.w - 2 * self.margin, int(1040 * s))
        box = pygame.Rect(0, 0, width, 2 * pad + head_h + len(self.picker) * row_h + note_h)
        box.center = (self.w // 2, (self.h - self.footer_h) // 2 + int(24 * s * (1 - t)))

        shade = pygame.Surface((self.w, self.h - self.footer_h), pygame.SRCALPHA)
        shade.fill((0, 0, 0, int(150 * t)))
        self.screen.blit(shade, (0, 0))
        self.screen.blit(draw.rounded_rect(box.width, box.height, 18 * s, (*PANEL, 248), (78, 62, 55), 1.5 * s), box)
        self.hits.append(Hit(shade.get_rect(), self._act(Action.BACK)))
        self.hits.append(Hit(box, lambda: None))

        x, y = box.x + pad, box.y + pad
        inner = box.width - 2 * pad
        self.screen.blit(self._tracked("Launcher", 16, self.theme.label, tracking=0.3), (x, y))
        title_font = self._font(40, bold=True)
        self.screen.blit(self._text("Where do your presets live?", title_font, TEXT), (x, y + int(28 * s)))
        y += head_h

        current = self.launchers.current if self.launchers else None
        name_font, sel_font, side_font, mono = self._font(31), self._font(31, bold=True), self._font(21), self._font(17, mono=True)
        for i, choice in enumerate(self.picker):
            rect = pygame.Rect(box.x + int(12 * s), y, box.width - int(24 * s), row_h - int(6 * s))
            selected = i == self.picker_sel
            if selected:
                self.screen.blit(draw.rounded_rect(rect.width, rect.height, 10 * s, (255, 255, 255, 16)), rect)
                pygame.draw.rect(self.screen, self.theme.accent, (rect.x, rect.y + int(10 * s), int(5 * s), rect.height - int(20 * s)))
            self.hits.append(Hit(rect, lambda i=i: self._picker_pick(i), lambda i=i: self._picker_hover(i)))
            if choice is None:
                name, sub, side, side_color = "Find it myself…", f"Pick a launcher's {PROGRAM} or its settings file", "", MUTED
            else:
                result = self.launchers.preview(choice)
                name, sub = choice.name, str(choice.path)
                if isinstance(result, OptionsError):
                    side, side_color = "Can't read", ERROR
                else:
                    n = len(result.presets)
                    side, side_color = (f"{n} preset{'s' if n != 1 else ''}" if n else "No presets"), (MUTED if n else DIM)
            side_surf = self._text(side, side_font, side_color) if side else None
            right = rect.right - int(22 * s)
            if side_surf:
                self.screen.blit(side_surf, (right - side_surf.get_width(), self._text_top(side_font, rect.y + int(30 * s))))
                right -= side_surf.get_width() + int(18 * s)
            if current and choice is not None and choice.id == current.id:
                tag = self._tracked("Current", 15, self.theme.label, tracking=0.25)
                self.screen.blit(tag, (right - tag.get_width(), self._text_top(self._font(15, bold=True), rect.y + int(30 * s))))
            font = sel_font if selected else name_font
            self.screen.blit(self._text(name, font, TEXT if selected else MUTED), (x, self._text_top(font, rect.y + int(30 * s))))
            self.screen.blit(self._text(self._fit(sub, mono, inner), mono, DIM), (x, rect.y + int(52 * s)))
            y += row_h

        note = f"Not listed? Drag its {PROGRAM} or settings file onto this window."
        note_font = self._font(21)
        self.screen.blit(self._text(self._fit(note, note_font, inner), note_font, DIM), (x, y + int(18 * s)))

    def _draw_update(self, now: float) -> None:
        s = self.s
        info = self.update or {}
        t = _ease_out((now - self.update_opened) / 0.25)
        pad, row_h, head_h = int(34 * s), int(84 * s), int(118 * s)
        width = min(self.w - 2 * self.margin, int(980 * s))
        inner = width - 2 * pad
        notes_font = self._font(23)
        notes: list[str] = []
        for item in info.get("notes", [])[:4]:
            wrapped = self._wrap(item, notes_font, inner - int(26 * s), 2)
            notes += [(("•  " if i == 0 else "    ") + line) for i, line in enumerate(wrapped)]
        notes_h = (int(34 * s) + len(notes) * int(32 * s)) if notes else 0
        box = pygame.Rect(0, 0, width, 2 * pad + head_h + notes_h + len(UPDATE_CHOICES) * row_h)
        box.center = (self.w // 2, (self.h - self.footer_h) // 2 + int(24 * s * (1 - t)))

        shade = pygame.Surface((self.w, self.h - self.footer_h), pygame.SRCALPHA)
        shade.fill((0, 0, 0, int(150 * t)))
        self.screen.blit(shade, (0, 0))
        self.screen.blit(draw.rounded_rect(box.width, box.height, 18 * s, (*PANEL, 248), (78, 62, 55), 1.5 * s), box)
        self.hits.append(Hit(shade.get_rect(), lambda: self._update_pick(1)))
        self.hits.append(Hit(box, lambda: None))

        x, y = box.x + pad, box.y + pad
        self.screen.blit(self._tracked("Update available", 16, self.theme.label, tracking=0.3), (x, y))
        self.screen.blit(self._text(f"CouchDoom {info.get('version', '')} is out", self._font(40, bold=True), TEXT), (x, y + int(28 * s)))
        self.screen.blit(self._text(f"You're on {info.get('current', __version__)}", self._font(22), MUTED), (x, y + int(80 * s)))
        y += head_h

        if notes:
            self.screen.blit(self._tracked("What's new", 15, self.theme.label, tracking=0.25), (x, y))
            y += int(34 * s)
            for line in notes:
                self.screen.blit(self._text(line, notes_font, MUTED), (x, y))
                y += int(32 * s)

        name_font, sel_font, sub_font = self._font(31), self._font(31, bold=True), self._font(21)
        for i, (_, name, sub) in enumerate(UPDATE_CHOICES):
            rect = pygame.Rect(box.x + int(12 * s), y, box.width - int(24 * s), row_h - int(6 * s))
            selected = i == self.update_sel
            if selected:
                self.screen.blit(draw.rounded_rect(rect.width, rect.height, 10 * s, (255, 255, 255, 16)), rect)
                pygame.draw.rect(self.screen, self.theme.accent, (rect.x, rect.y + int(10 * s), int(5 * s), rect.height - int(20 * s)))
            self.hits.append(Hit(rect, lambda i=i: self._update_pick(i), lambda i=i: self._update_hover(i)))
            font = sel_font if selected else name_font
            self.screen.blit(self._text(name, font, TEXT if selected else MUTED), (x, self._text_top(font, rect.y + int(26 * s))))
            sub = sub.replace("{v}", str(info.get("version", "")))
            self.screen.blit(self._text(self._fit(sub, sub_font, inner), sub_font, DIM), (x, rect.y + int(52 * s)))
            y += row_h

    def _draw_osk(self, now: float) -> None:
        s = self.s
        cell_h, gap = int(64 * s), int(8 * s)
        cols = max(len(r) for r in OSK_ROWS)
        cell_w = int(76 * s)
        grid_w = cols * cell_w + (cols - 1) * gap
        grid_h = len(OSK_ROWS) * cell_h + (len(OSK_ROWS) - 1) * gap
        pad = int(30 * s)
        field_h = int(78 * s)
        box = pygame.Rect(0, 0, grid_w + 2 * pad, field_h + grid_h + 2 * pad)
        box.midbottom = (self.w // 2, self.h - self.footer_h - int(24 * s))

        shade = pygame.Surface((self.w, self.h - self.footer_h), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 130))
        self.screen.blit(shade, (0, 0))
        self.screen.blit(draw.rounded_rect(box.width, box.height, 18 * s, (*PANEL, 248), (78, 62, 55), 1.5 * s), box)
        self.hits.append(Hit(shade.get_rect(), self._act(Action.SEARCH)))  # click outside: done, keep the filter
        self.hits.append(Hit(box, lambda: None))

        fx, fy = box.x + pad, box.y + pad
        self.screen.blit(self._tracked("Search", 16, self.theme.label, tracking=0.3), (fx, fy))
        caret = "_" if int(now * 2) % 2 == 0 else " "
        field = self._text(self._fit(self.filter + caret, self._font(34), grid_w - int(160 * s)), self._font(34), TEXT)
        self.screen.blit(field, (fx, fy + int(22 * s)))
        count = sum(1 for r in self.rows if r.kind == "preset" and not r.fav)
        cnt = self._tracked(f"{count} match{'es' if count != 1 else ''}", 16, MUTED, tracking=0.25)
        self.screen.blit(cnt, (fx + grid_w - cnt.get_width(), fy + int(34 * s)))
        pygame.draw.rect(self.screen, self.theme.accent, (fx, fy + field_h - int(12 * s), grid_w, max(2, int(3 * s))))

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
                    t = self._tracked(key, 15, TEXT if selected else (self.theme.label if key == "DONE" else MUTED), tracking=0.2)
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

        shade = pygame.Surface((self.w, self.h - self.footer_h), pygame.SRCALPHA)
        shade.fill((0, 0, 0, int(150 * t)))
        self.screen.blit(shade, (0, 0))

        sheet = draw.rounded_rect(rect.width, rect.height, 18 * s, (*PANEL, 250), (78, 62, 55), 1.5 * s).copy()
        pad = int(36 * s)
        tab_cy = int(48 * s)
        pad_mode = self.input.pad_mode
        left = self.glyphs.get("LB" if pad_mode else "KEY:LEFT")
        right = self.glyphs.get("RB" if pad_mode else "KEY:RIGHT")
        self.hits.append(Hit(shade.get_rect(), self._close_overlay))  # click outside the sheet closes it
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
            name = INFO_TABS[i]
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
            sheet.blit(pic, (body.x + (body.width - pic.get_width()) // 2, body.y))
        elif not lines:
            if self.info_tab == 0 and self.current not in self.readmes:
                msg = "Looking for a readme…"
            else:
                msg = "No readme beside or inside this preset's files."
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
        self.screen.blit(surf, (self.w - self.margin - w, self.margin + int(104 * s) - slide))

    # ---------- loop ----------

    def run(self) -> int:
        clock = pygame.time.Clock()
        last = time.monotonic()
        self._start_update_check(last)
        try:
            while self.running:
                now = time.monotonic()
                dt = now - last
                last = now

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False
                        continue
                    if event.type == pygame.DROPFILE:
                        self._on_drop(Path(event.file))
                        continue
                    actions = self.input.handle(event, now)
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
                        self._on_action(action, now)

                self.tick(now, dt)
                self._draw(now)
                self._flip()
                clock.tick(60)
        finally:
            self.art_pool.shutdown(wait=False, cancel_futures=True)
            if self.update_pool:
                self.update_pool.shutdown(wait=False, cancel_futures=True)
            if self.music:
                self.music.shutdown()
            pygame.quit()
        return 0

    def tick(self, now: float, dt: float) -> None:
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
                self.info_view = _lerp(self.info_view, self.info_scroll, min(1.0, dt * 18))
        if self.rows:
            self.scroll = _lerp(self.scroll, self._target_scroll(), min(1.0, dt * 14))
            self.bar_y = _lerp(self.bar_y, self.row_y[self._sel_row()], min(1.0, dt * 20))
