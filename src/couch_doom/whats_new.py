"""What changed since the version the player last ran, read from the CHANGELOG.md bundled with the app.

The update notice only carries the newest release's notes, so someone who skipped a few releases would never
see the ones in between. The new build has the whole changelog, so it fills that gap on its first launch.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from .config import FROZEN, PROJECT_ROOT
from .update import _plain, parse_version

CHANGELOG = Path(sys._MEIPASS) / "CHANGELOG.md" if FROZEN else PROJECT_ROOT / "CHANGELOG.md"
_HEADING = re.compile(r"\*\*New in ([^*]+)\*\*")


def sections(text: str) -> list[tuple[str, list[str]]]:
    """Every "New in X" section as (version, bullets), in file order."""
    out: list[tuple[str, list[str]]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if m := _HEADING.fullmatch(line):
            out.append((m.group(1).strip(), []))
        elif out and line.startswith(("- ", "* ")):
            out[-1][1].append(_plain(line[2:]))
    return out


def since(text: str, previous: str | None, current: str) -> list[tuple[str, list[str]]]:
    """Releases after `previous` up to `current`, newest first. With no previous version, only `current`."""
    cur = parse_version(current)
    prev = parse_version(previous) if previous else None
    picked = [(v, notes) for v, notes in sections(text) if notes and (pv := parse_version(v)) <= cur
              and (pv == cur if prev is None else pv > prev)]
    return sorted(picked, key=lambda item: parse_version(item[0]), reverse=True)


def pending(previous: str | None, returning: bool, current: str, path: Path | None = None) -> dict | None:
    """{"version", "previous", "sections"} to show once after an update, or None.

    `previous` is the last version this player ran; versions before 1.2.3 never recorded one, so a returning
    player without it sees only this release. A fresh install has nothing to compare and sees nothing."""
    if previous is None and not returning:
        return None
    if previous is not None and parse_version(current) <= parse_version(previous):
        return None
    try:
        text = (path or CHANGELOG).read_text(encoding="utf-8")
    except OSError:
        return None
    found = since(text, previous, current)
    return {"version": current, "previous": previous, "sections": found} if found else None
