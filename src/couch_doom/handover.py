"""Keep the loading screen up until the engine has a window of its own.

Windows, X11 (including XWayland) and macOS can tell us about other applications' windows. Native Wayland does
not expose them: once the engine is seen loading libwayland-client without X11, we stop covering and let the
compositor show the game; without XWayland at all the display is released immediately, as before.
"""
from __future__ import annotations

import ctypes
import functools
import os
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Iterable

WINDOWS = sys.platform == "win32"
LINUX = sys.platform.startswith("linux")
MACOS = sys.platform == "darwin"

DEFAULT_TIMEOUT = 45.0
POLL_SECONDS = 0.1  # enumerating windows is not free; four looks a second is plenty
FRAME_SECONDS = 1 / 60
PROCESS_CACHE_SECONDS = 0.5

MIN_WINDOW_W, MIN_WINDOW_H = 160, 120


@dataclass(frozen=True)
class Window:
    """The bits of a top-level window this test needs; separate from the native calls so it can be tested anywhere."""

    handle: int
    pid: int
    visible: bool
    class_name: str
    width: int
    height: int
    owner: int
    tool: bool


def hold(poll: Callable[[], int | None], ready: Callable[[], bool], frame: Callable[[], None],
         timeout: float = DEFAULT_TIMEOUT, clock: Callable[[], float] = time.monotonic,
         sleep: Callable[[float], None] = time.sleep, *, grace_frames: int = 0) -> str:
    """Draw the loading screen until the engine window is ready, the engine exits, or timeout.

    Returns "window", "exited" or "timeout". `poll` is the engine's Popen.poll, and the clock and sleep are
    parameters so the loop can be tested without waiting in real time. `grace_frames` keeps covering the screen
    for a moment after the window appears, so the first painted frame does not reveal the desktop.
    """
    started = clock()
    next_check = started
    while True:
        if poll() is not None:
            return "exited"
        now = clock()
        if now >= next_check:
            if ready():
                for _ in range(grace_frames):
                    if poll() is not None:
                        return "exited"
                    frame()
                    sleep(FRAME_SECONDS)
                return "window"
            next_check = now + POLL_SECONDS
        if now - started >= timeout:
            return "timeout"
        frame()
        sleep(FRAME_SECONDS)


def available() -> bool:
    """Whether this session lets us see the engine's windows at all."""
    try:
        if WINDOWS:
            return True
        if LINUX:
            return _x11() is not None
        if MACOS:
            _quartz()
            return True
    except (OSError, AttributeError, ValueError):
        return False  # no X11/XWayland (a pure Wayland session), or no Quartz: keep the old launch path
    return False


def _descendants(root: int, pairs: Iterable[tuple[int, int]]) -> set[int]:
    """The root process and every process below it, from (pid, parent_pid) pairs."""
    children: dict[int, list[int]] = {}
    for pid, parent in pairs:
        children.setdefault(parent, []).append(pid)
    found = {root}
    pending = [root]
    while pending:
        for child in children.get(pending.pop(), ()):
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def _usable(win: Window, pids: set[int], own_handle: int | None) -> bool:
    """A real game window: the engine's, visible, unowned, and large enough not to be a splash or a prompt."""
    return (
        win.visible
        and win.pid in pids
        and (own_handle is None or win.handle != own_handle)
        and win.owner == 0
        and not win.tool
        and win.class_name != "ConsoleWindowClass"
        and win.width >= MIN_WINDOW_W
        and win.height >= MIN_WINDOW_H
    )


# ---------- process trees ----------

_pairs_cache: tuple[float, list[tuple[int, int]]] | None = None


def _process_pairs() -> list[tuple[int, int]]:
    """Every (pid, parent_pid) on the machine, cached briefly: it is only used to recognise child processes."""
    global _pairs_cache
    now = time.monotonic()
    if _pairs_cache is not None and now - _pairs_cache[0] < PROCESS_CACHE_SECONDS:
        return _pairs_cache[1]
    pairs = _windows_process_pairs() if WINDOWS else _linux_process_pairs() if LINUX else \
        _macos_process_pairs() if MACOS else []
    _pairs_cache = (now, pairs)
    return pairs


def _stat_ppid(data: bytes) -> int:
    """The parent pid field of /proc/<pid>/stat, after the command name (which may itself contain spaces or ')' )"""
    return int(data.rsplit(b")", 1)[1].split()[1])


def _loads_library(maps: bytes, name: bytes) -> bool:
    """Whether a /proc/<pid>/maps image includes a shared library whose path contains `name`."""
    return name in maps


def engine_uses_wayland(pid: int) -> bool:
    """Whether the engine tree has Wayland loaded and X11 has not.

    Wayland does not let one application see another's windows, so this is the signal to stop holding the splash
    screen: otherwise a native-Wayland game would stay hidden behind it until the timeout. SDL loads only the
    video backend it chose, so its process maps say which one that is. A wrapper that has both loaded is treated
    as X11, where the window scan still works.
    """
    if not LINUX or pid <= 0 or not os.environ.get("WAYLAND_DISPLAY"):
        return False
    wayland = x11 = False
    for child in _descendants(pid, _process_pairs()):
        try:
            with open(f"/proc/{child}/maps", "rb") as f:
                maps = f.read()
        except OSError:
            continue
        wayland = wayland or _loads_library(maps, b"libwayland-client")
        x11 = x11 or _loads_library(maps, b"libX11.so")
    return wayland and not x11


def _linux_process_pairs() -> list[tuple[int, int]]:
    """Every (pid, parent_pid) from /proc; empty if /proc is unavailable (some sandboxes)."""
    try:
        names = os.listdir("/proc")
    except OSError:
        return []
    pairs: list[tuple[int, int]] = []
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", "rb") as f:
                pairs.append((int(name), _stat_ppid(f.read())))
        except (OSError, IndexError, ValueError):
            continue
    return pairs


PROC_PIDTBSDINFO = 3


class _ProcBsdInfo(ctypes.Structure):
    """Darwin's struct proc_bsdinfo; only the leading pid/parent fields are read here."""

    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


@functools.cache
def _libproc():
    api = ctypes.CDLL("/usr/lib/libproc.dylib")
    api.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
    api.proc_listallpids.restype = ctypes.c_int
    api.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    api.proc_pidinfo.restype = ctypes.c_int
    return api


def _macos_process_pairs() -> list[tuple[int, int]]:
    """Every (pid, parent_pid) via libproc; empty if Darwin will not list processes."""
    try:
        api = _libproc()
    except OSError:
        return []
    capacity = 4096
    buffer = (ctypes.c_int * capacity)()
    count = api.proc_listallpids(buffer, ctypes.sizeof(buffer))
    if count <= 0:
        return []
    info = _ProcBsdInfo()
    size = ctypes.sizeof(info)
    pairs: list[tuple[int, int]] = []
    for pid in buffer[:min(count, capacity)]:
        if pid <= 0:
            continue
        if api.proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, ctypes.byref(info), size) == size:
            pairs.append((info.pbi_pid, info.pbi_ppid))
    return pairs


# ---------- Windows ----------

TH32CS_SNAPPROCESS = 0x00000002
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


@functools.cache
def _kernel32():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    api.Process32FirstW.restype = wintypes.BOOL
    api.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    api.Process32NextW.restype = wintypes.BOOL
    api.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    api.CloseHandle.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    return api


def _windows_process_pairs() -> list[tuple[int, int]]:
    """Every (pid, parent_pid) on the machine; empty if Windows will not tell us."""
    api = _kernel32()
    snapshot = api.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return []
    entry = _PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
    pairs: list[tuple[int, int]] = []
    try:
        if not api.Process32FirstW(snapshot, ctypes.byref(entry)):
            return []
        while True:
            pairs.append((entry.th32ProcessID, entry.th32ParentProcessID))
            if not api.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        api.CloseHandle(snapshot)
    return pairs


@functools.cache
def _user32():
    api = ctypes.WinDLL("user32", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    api.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
    api.EnumWindows.restype = wintypes.BOOL
    api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    api.GetWindowThreadProcessId.restype = wintypes.DWORD
    api.IsWindowVisible.argtypes = [wintypes.HWND]
    api.IsWindowVisible.restype = wintypes.BOOL
    api.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    api.GetClassNameW.restype = ctypes.c_int
    api.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
    api.GetWindowRect.restype = wintypes.BOOL
    api.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    api.GetWindow.restype = wintypes.HWND
    api.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    api.GetWindowLongW.restype = wintypes.LONG
    return api, enum_proc


def _windows_describe(api, hwnd: int) -> Window:
    pid = wintypes.DWORD()
    if not api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
        return Window(int(hwnd or 0), 0, False, "", 0, 0, 0, False)
    name = ctypes.create_unicode_buffer(256)
    api.GetClassNameW(hwnd, name, len(name))
    rect = _RECT()
    api.GetWindowRect(hwnd, ctypes.byref(rect))
    owner = api.GetWindow(hwnd, GW_OWNER)
    tool = bool(api.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW)
    return Window(int(hwnd or 0), int(pid.value), bool(api.IsWindowVisible(hwnd)), name.value,
                  rect.right - rect.left, rect.bottom - rect.top, int(owner or 0), tool)


def _windows_find(pids: set[int], own_handle: int | None) -> Window | None:
    api, enum_proc = _user32()
    found: Window | None = None

    @enum_proc
    def visit(hwnd, _lparam):
        nonlocal found
        try:
            win = _windows_describe(api, hwnd)
        except (OSError, ValueError):
            return True
        if _usable(win, pids, own_handle):
            found = win
            return False  # stop enumerating: the first usable window is enough
        return True

    api.EnumWindows(visit, 0)
    return found


# ---------- X11 ----------

XA_ATOM = 4
XA_WINDOW = 33
ANY_PROPERTY_TYPE = 0
IS_VIEWABLE = 2

_X11_TOOL_TYPES = (
    "_NET_WM_WINDOW_TYPE_UTILITY",
    "_NET_WM_WINDOW_TYPE_TOOLBAR",
    "_NET_WM_WINDOW_TYPE_MENU",
    "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU",
    "_NET_WM_WINDOW_TYPE_POPUP_MENU",
    "_NET_WM_WINDOW_TYPE_TOOLTIP",
    "_NET_WM_WINDOW_TYPE_NOTIFICATION",
    "_NET_WM_WINDOW_TYPE_COMBO",
    "_NET_WM_WINDOW_TYPE_DND",
    "_NET_WM_WINDOW_TYPE_SPLASH",
    "_NET_WM_WINDOW_TYPE_DESKTOP",
    "_NET_WM_WINDOW_TYPE_DOCK",
)
_X11_ATOMS = ("_NET_CLIENT_LIST", "_NET_WM_PID", "WM_TRANSIENT_FOR", "WM_CLASS", "_NET_WM_WINDOW_TYPE",
               *_X11_TOOL_TYPES)


class _XWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("border_width", ctypes.c_int),
        ("depth", ctypes.c_int),
        ("visual", ctypes.c_void_p),
        ("root", ctypes.c_ulong),
        ("class_", ctypes.c_int),
        ("bit_gravity", ctypes.c_int),
        ("win_gravity", ctypes.c_int),
        ("backing_store", ctypes.c_int),
        ("backing_planes", ctypes.c_ulong),
        ("backing_pixel", ctypes.c_ulong),
        ("save_under", ctypes.c_int),
        ("colormap", ctypes.c_ulong),
        ("map_installed", ctypes.c_int),
        ("map_state", ctypes.c_int),
        ("all_event_masks", ctypes.c_long),
        ("your_event_mask", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", ctypes.c_int),
        ("screen", ctypes.c_void_p),
    ]


_X11_ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


@_X11_ERROR_HANDLER
def _ignore_x11_error(_display, _event):
    return 0  # windows come and go between enumeration and inspection; that must not be fatal


class _X11:
    def __init__(self, api, display: int, atoms: dict[str, int]):
        self.api = api
        self.display = display
        self.atoms = atoms
        self.tool_types = {atoms[name] for name in _X11_TOOL_TYPES}


@functools.cache
def _x11() -> _X11 | None:
    try:
        api = ctypes.CDLL("libX11.so.6")
    except OSError:
        return None
    api.XOpenDisplay.argtypes = [ctypes.c_char_p]
    api.XOpenDisplay.restype = ctypes.c_void_p
    display = api.XOpenDisplay(None)
    if not display:
        return None
    api.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    api.XInternAtom.restype = ctypes.c_ulong
    api.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    api.XDefaultRootWindow.restype = ctypes.c_ulong
    api.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_XWindowAttributes)]
    api.XGetWindowAttributes.restype = ctypes.c_int
    api.XGetWindowProperty.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long, ctypes.c_int,
        ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p),
    ]
    api.XGetWindowProperty.restype = ctypes.c_int
    api.XQueryTree.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)), ctypes.POINTER(ctypes.c_uint),
    ]
    api.XQueryTree.restype = ctypes.c_int
    api.XFree.argtypes = [ctypes.c_void_p]
    api.XFree.restype = ctypes.c_int
    api.XSetErrorHandler.argtypes = [ctypes.c_void_p]
    api.XSetErrorHandler.restype = ctypes.c_void_p
    atoms = {name: int(api.XInternAtom(display, name.encode(), False)) for name in _X11_ATOMS}
    return _X11(api, display, atoms)


def _x11_values(x: _X11, window: int, atom_name: str, req_type: int = ANY_PROPERTY_TYPE):
    """A property's 32-bit values, its 8-bit bytes, or None when the window does not have it."""
    atom = x.atoms.get(atom_name, 0)
    if not atom:
        return None
    actual_type = ctypes.c_ulong()
    actual_format = ctypes.c_int()
    count = ctypes.c_ulong()
    after = ctypes.c_ulong()
    data = ctypes.c_void_p()
    status = x.api.XGetWindowProperty(x.display, window, atom, 0, 1024, False, req_type,
                                      ctypes.byref(actual_type), ctypes.byref(actual_format),
                                      ctypes.byref(count), ctypes.byref(after), ctypes.byref(data))
    if status != 0 or not data.value or not count.value:
        if data.value:
            x.api.XFree(data)
        return None
    try:
        if actual_format.value == 32:
            # Xlib hands back format-32 properties as an array of longs, not ints.
            values = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))
            return tuple(int(values[i]) for i in range(count.value))
        return ctypes.string_at(data, count.value)
    finally:
        x.api.XFree(data)


def _x11_children(x: _X11, window: int) -> tuple[int, ...]:
    root_return, parent_return = ctypes.c_ulong(), ctypes.c_ulong()
    children = ctypes.POINTER(ctypes.c_ulong)()
    count = ctypes.c_uint()
    if not x.api.XQueryTree(x.display, window, ctypes.byref(root_return), ctypes.byref(parent_return),
                            ctypes.byref(children), ctypes.byref(count)):
        return ()
    try:
        return tuple(int(children[i]) for i in range(count.value))
    finally:
        if children:
            x.api.XFree(children)


def _x11_clients(x: _X11) -> tuple[int, ...]:
    """The window manager's client list, or the client windows nested under the root's children.

    Without an EWMH window manager (a bare X server, some XWayland sessions), top-level game windows are the
    children of frame/wrapper windows rather than direct children of the root, so look one level down too.
    """
    root = x.api.XDefaultRootWindow(x.display)
    clients = _x11_values(x, root, "_NET_CLIENT_LIST")
    if clients:
        return tuple(int(w) for w in clients)
    found: list[int] = []
    for child in _x11_children(x, root):
        found.append(child)
        found.extend(_x11_children(x, child))
    return tuple(found)


def _x11_describe(x: _X11, window: int) -> Window | None:
    attrs = _XWindowAttributes()
    if not x.api.XGetWindowAttributes(x.display, window, ctypes.byref(attrs)):
        return None
    pids = _x11_values(x, window, "_NET_WM_PID")
    if not pids:
        return None
    transient = _x11_values(x, window, "WM_TRANSIENT_FOR", XA_WINDOW) or ()
    types = _x11_values(x, window, "_NET_WM_WINDOW_TYPE", XA_ATOM) or ()
    classes = _x11_values(x, window, "WM_CLASS")
    class_name = classes.rstrip(b"\0").split(b"\0")[-1].decode("latin-1", "replace") \
        if isinstance(classes, bytes) else ""
    tool = bool(attrs.override_redirect or any(t in x.tool_types for t in types))
    return Window(int(window), int(pids[0]), attrs.map_state == IS_VIEWABLE, class_name, attrs.width,
                  attrs.height, int(transient[0]) if transient else 0, tool)


def _x11_find(pids: set[int], own_handle: int | None) -> Window | None:
    x = _x11()
    if x is None:
        return None
    previous = x.api.XSetErrorHandler(ctypes.cast(_ignore_x11_error, ctypes.c_void_p))
    try:
        for window in _x11_clients(x):
            win = _x11_describe(x, window)
            if win is not None and _usable(win, pids, own_handle):
                return win
    finally:
        x.api.XSetErrorHandler(previous)
    return None


# ---------- macOS ----------

class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


class _Quartz:
    def __init__(self, cg, cf, keys: dict[str, int]):
        self.cg = cg
        self.cf = cf
        self.keys = keys


@functools.cache
def _quartz() -> _Quartz:
    cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
    cg.CGRectMakeWithDictionaryRepresentation.argtypes = [ctypes.c_void_p, ctypes.POINTER(_CGRect)]
    cg.CGRectMakeWithDictionaryRepresentation.restype = ctypes.c_bool
    cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
    cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
    cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    cf.CFDictionaryGetValue.restype = ctypes.c_void_p
    cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    cf.CFNumberGetValue.restype = ctypes.c_bool
    cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    cf.CFRelease.restype = None
    names = ("kCGWindowNumber", "kCGWindowOwnerPID", "kCGWindowBounds", "kCGWindowAlpha", "kCGWindowLayer")
    keys = {}
    for name in names:
        key = cf.CFStringCreateWithCString(None, name.encode(), 0x08000100)  # kCFStringEncodingUTF8
        if not key:
            raise OSError(f"CoreFoundation could not create {name}")
        keys[name] = key
    return _Quartz(cg, cf, keys)


def _cf_number(cf, value) -> float | None:
    if not value:
        return None
    out = ctypes.c_double()
    if not cf.CFNumberGetValue(value, 6, ctypes.byref(out)):  # kCFNumberFloat64Type
        return None
    return out.value


def _quartz_find(pids: set[int]) -> Window | None:
    q = _quartz()
    # On-screen normal windows only; desktop elements (wallpaper, Dock) are excluded.
    array = q.cg.CGWindowListCopyWindowInfo(1 | 16, 0)  # OnScreenOnly | ExcludeDesktopElements
    if not array:
        return None
    try:
        count = q.cf.CFArrayGetCount(array)
        for i in range(count):
            info = q.cf.CFArrayGetValueAtIndex(array, i)
            if not info:
                continue
            pid = _cf_number(q.cf, q.cf.CFDictionaryGetValue(info, q.keys["kCGWindowOwnerPID"]))
            if pid is None or int(pid) not in pids:
                continue
            alpha = _cf_number(q.cf, q.cf.CFDictionaryGetValue(info, q.keys["kCGWindowAlpha"]))
            if alpha is not None and alpha <= 0:
                continue
            layer = _cf_number(q.cf, q.cf.CFDictionaryGetValue(info, q.keys["kCGWindowLayer"])) or 0
            number = _cf_number(q.cf, q.cf.CFDictionaryGetValue(info, q.keys["kCGWindowNumber"])) or 0
            rect = _CGRect()
            bounds = q.cf.CFDictionaryGetValue(info, q.keys["kCGWindowBounds"])
            width = height = 0
            if bounds and q.cg.CGRectMakeWithDictionaryRepresentation(bounds, ctypes.byref(rect)):
                width, height = int(rect.size.width), int(rect.size.height)
            win = Window(int(number), int(pid), True, "", width, height, 0, layer != 0)
            if _usable(win, pids, None):
                return win
    finally:
        q.cf.CFRelease(array)
    return None


# ---------- public entry point ----------


def engine_window_visible(pid: int, own_handle: int | None) -> bool:
    """Whether a process in `pid`'s tree (the engine, even behind a wrapper) has a real window on screen."""
    if pid <= 0 or not available():
        return False
    try:
        pids = _descendants(pid, _process_pairs())
        if WINDOWS:
            return _windows_find(pids, own_handle) is not None
        if LINUX:
            return _x11_find(pids, own_handle) is not None
        if MACOS:
            return _quartz_find(pids) is not None
    except Exception:  # failing to look must never keep the player on the splash or crash the app
        return False
    return False
