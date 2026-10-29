"""Keep the loading screen up until the engine has a window of its own.

Windows only for now: there is no portable way to see another process's windows, and that is where the desktop
flash is worst. Other platforms keep the old behaviour: the display is released as soon as the engine is spawned.
"""
from __future__ import annotations

import ctypes
import functools
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Iterable

WINDOWS = sys.platform == "win32"

DEFAULT_TIMEOUT = 45.0
POLL_SECONDS = 0.1  # enumerating windows is not free; four looks a second is plenty
FRAME_SECONDS = 1 / 60

TH32CS_SNAPPROCESS = 0x00000002
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
MIN_WINDOW_W, MIN_WINDOW_H = 160, 120
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


@dataclass(frozen=True)
class Window:
    """The bits of a top-level window this test needs; separate from the Win32 calls so it can be tested anywhere."""

    hwnd: int
    pid: int
    visible: bool
    class_name: str
    width: int
    height: int
    owner: int
    tool: bool


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


def _usable(win: Window, pids: set[int], own_hwnd: int | None) -> bool:
    """A real game window: the engine's, visible, unowned, and large enough not to be a splash or a prompt."""
    return (
        win.visible
        and win.pid in pids
        and (own_hwnd is None or win.hwnd != own_hwnd)
        and win.owner == 0
        and not win.tool
        and win.class_name != "ConsoleWindowClass"
        and win.width >= MIN_WINDOW_W
        and win.height >= MIN_WINDOW_H
    )


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


def _process_pairs() -> list[tuple[int, int]]:
    """Every (pid, parent_pid) on the machine; empty if Windows will not tell us."""
    if not WINDOWS:
        return []
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


def _describe(api, hwnd: int) -> Window:
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


def _find_window(pids: set[int], own_hwnd: int | None) -> Window | None:
    api, enum_proc = _user32()
    found: Window | None = None

    @enum_proc
    def visit(hwnd, _lparam):
        nonlocal found
        try:
            win = _describe(api, hwnd)
        except (OSError, ValueError):
            return True
        if _usable(win, pids, own_hwnd):
            found = win
            return False  # stop enumerating: the first usable window is enough
        return True

    api.EnumWindows(visit, 0)
    return found


def engine_window_visible(pid: int, own_hwnd: int | None) -> bool:
    """Whether a process in `pid`'s tree (the engine, even behind a wrapper) has a real window on screen."""
    if not WINDOWS or pid <= 0:
        return False
    try:
        pids = _descendants(pid, _process_pairs())
        return _find_window(pids, own_hwnd) is not None
    except Exception:  # failing to look must never keep the player on the splash or crash the app
        return False
