"""Helpers for keeping CPU-heavy background work from starving the UI."""
from __future__ import annotations

import ctypes
import sys


def lower_current_thread_priority() -> bool:
    """Drop this worker below the UI thread, so a cache walk loses when both want the CPU. Returns whether it took."""
    if sys.platform == "win32":
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            get_current_thread = kernel32.GetCurrentThread
            get_current_thread.restype = ctypes.c_void_p
            set_thread_priority = kernel32.SetThreadPriority
            set_thread_priority.argtypes = (ctypes.c_void_p, ctypes.c_int)
            set_thread_priority.restype = ctypes.c_int
            return bool(set_thread_priority(get_current_thread(), -1))  # THREAD_PRIORITY_BELOW_NORMAL
        except (AttributeError, OSError):
            return False
    if sys.platform.startswith("linux"):
        # glibc 2.30+ gettid. Nice 5 is a modest step down, about the same idea as BELOW_NORMAL; nice is
        # per-thread on Linux even though it is per-process on other Unixes.
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            gettid = getattr(libc, "gettid", None)
            if gettid is None:
                return False
            gettid.restype = ctypes.c_int
            setpriority = libc.setpriority
            setpriority.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_int)
            setpriority.restype = ctypes.c_int
            return setpriority(0, gettid(), 5) == 0  # PRIO_PROCESS, this thread, nice 5
        except (AttributeError, OSError, TypeError):
            return False
    return False
