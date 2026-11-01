"""Helpers for keeping CPU-heavy background work from starving the UI."""
from __future__ import annotations

import ctypes
import sys


def lower_current_thread_priority() -> bool:
    """Set this worker below normal priority on Windows; return whether it succeeded."""
    if sys.platform != "win32":
        return False
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
