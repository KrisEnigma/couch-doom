"""Atomic file swaps that tolerate brief Windows locks (antivirus, concurrent readers)."""
from __future__ import annotations

import os
import time
from pathlib import Path


def replace_timeout() -> float:
    # AV and Explorer often hold a just-written cache file for a moment on Windows.
    return 5.0 if os.name == "nt" else 1.0


def replace_when_free(source: Path, destination: Path, timeout: float | None = None) -> None:
    """Move ``source`` onto ``destination``, retrying PermissionError until ``timeout``."""
    if timeout is None:
        timeout = replace_timeout()
    deadline = time.monotonic() + timeout
    delay = 0.05
    while True:
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 1.5, 0.25)
