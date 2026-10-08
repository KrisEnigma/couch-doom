"""A small troubleshooting log: crashes, "nothing found" reports and one entry per game launch.

Local only, and bounded: the file rotates at MAX_BYTES into couch-doom.log.1, so the pair never exceeds twice that.
Environment variables are never written (launcher presets can carry secrets); file paths are, so check it before sharing.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .config import LOG_FILE

MAX_BYTES = 256 * 1024  # per file
OUTPUT_TAIL = 16 * 1024  # engine output kept per launch: the end, because that's where errors are


def write(title: str, body: str = "", path: Path | None = None) -> None:
    """Append one entry. Never raises: a log that can't be written must not break the app."""
    path = path or LOG_FILE
    head = f"=== {time.strftime('%Y-%m-%d %H:%M:%S')}  CouchDoom {__version__}  {sys.platform} {platform.machine()}  {title}\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > MAX_BYTES:
            os.replace(path, path.with_name(path.name + ".1"))
        with path.open("a", encoding="utf-8", errors="replace") as f:
            f.write(head + (body.rstrip("\n") + "\n" if body else "") + "\n")
    except OSError:
        pass


class Launched:
    """A running engine whose stdout and stderr are drained into a bounded buffer."""

    def __init__(self, proc: subprocess.Popen, name: str, command: str, cwd: Path | None):
        self.proc, self.name, self.command, self.cwd = proc, name, command, cwd
        self.tail = bytearray()
        self.output = ""  # the engine's last output, set once it has exited
        self.started = time.monotonic()
        # Daemon: a grandchild that keeps the pipe open must not hold CouchDoom up.
        self.reader = threading.Thread(target=self._drain, daemon=True)
        self.reader.start()

    def _drain(self) -> None:
        try:
            while chunk := self.proc.stdout.read1(4096):
                self.tail += chunk
                if len(self.tail) > OUTPUT_TAIL:
                    del self.tail[: len(self.tail) - OUTPUT_TAIL]
        except (OSError, ValueError):
            pass

    def wait(self, path: Path | None = None) -> tuple[int, float]:
        """Block until the engine exits, log the launch, and return (exit code, seconds)."""
        code = self.proc.wait()
        elapsed = time.monotonic() - self.started
        self.reader.join(2)
        out = self.output = bytes(self.tail).decode("utf-8", errors="replace").strip()
        body = f"cmd: {self.command}\ncwd: {self.cwd}\nexit: {code} after {elapsed:.1f}s\n"
        body += f"--- engine output (last {OUTPUT_TAIL // 1024} KB) ---\n{out}\n" if out else "--- no engine output ---\n"
        write(f"launch: {self.name}", body, path)
        return code, elapsed


def spawn(argv: list[str], cwd: Path | None, env: dict[str, str], name: str, command: str) -> Launched:
    """Start the engine. Raises OSError like Popen; the caller reports it (and it is logged here)."""
    try:
        # stdin is closed because pythonw has none, and Popen refuses to mix missing and piped handles.
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as exc:
        write(f"launch failed: {name}", f"cmd: {command}\ncwd: {cwd}\nerror: {exc}")
        raise
    return Launched(proc, name, command, cwd)


def closed_early(code: int, seconds: float) -> bool:
    """Whether the engine quit fast enough that the player probably didn't mean it to."""
    return seconds < 5 or (code != 0 and seconds < 30)


def last_line(output: str) -> str:
    """The last non-empty line the engine printed: usually its own explanation of why it quit."""
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    return lines[-1][:90] if lines else ""


def needs_extract_retry(argv: list[str], env: dict[str, str], output: str, code: int, seconds: float) -> bool:
    """An AppImage that died at once complaining about FUSE can still run by unpacking itself first."""
    is_appimage = any(a.lower().endswith(".appimage") for a in argv[:3])  # the engine, after any command prefix
    return (is_appimage and code != 0 and seconds < 10 and "fuse" in output.lower()
            and "APPIMAGE_EXTRACT_AND_RUN" not in env)