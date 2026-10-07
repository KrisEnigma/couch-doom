from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
# A packaged build keeps user data (state, soundfonts) beside the exe and read-only assets in the bundle.
PROJECT_ROOT = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parents[2]
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
DEFAULT_OPTIONS = Path(r"D:\Standalone\UZDoom\DoomRunner\options.json")
STATE_DIR = PROJECT_ROOT / "state"
STATE_FILE = STATE_DIR / "last_played.json"
LOG_FILE = STATE_DIR / "couch-doom.log"


def options_candidates(cli_value: str | None) -> list[Path]:
    """Where DoomRunner's options.json may live, in order. An explicit choice is the only candidate:
    silently falling back to a different setup would be more confusing than an error."""
    if cli_value:
        return [Path(cli_value)]
    env = os.environ.get("DOOMRUNNER_OPTIONS")
    if env:
        return [Path(env)]
    # DoomRunner keeps options.json beside its exe when portable, in the per-user app data folder when installed.
    found = [PROJECT_ROOT / "options.json", PROJECT_ROOT.parent / "options.json"] if FROZEN else []
    found.append(DEFAULT_OPTIONS)
    for var in ("LOCALAPPDATA", "APPDATA"):
        if base := os.environ.get(var):
            found.append(Path(base) / "DoomRunner" / "options.json")
    return found
