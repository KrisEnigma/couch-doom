from __future__ import annotations

import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
# A packaged build keeps user data (state, soundfonts) beside the exe and read-only assets in the bundle.
PROJECT_ROOT = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parents[2]
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
# The author's own launcher folder, searched only when running from source; a release must not list it.
DEV_LAUNCHERS = None if FROZEN else Path(r"D:\Standalone\UZDoom")
DEFAULT_OPTIONS = Path(r"D:\Standalone\UZDoom\DoomRunner\options.json")
STATE_DIR = PROJECT_ROOT / "state"
STATE_FILE = STATE_DIR / "last_played.json"
LOG_FILE = STATE_DIR / "couch-doom.log"
