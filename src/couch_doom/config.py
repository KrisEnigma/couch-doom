from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
PACKAGE_DIR = Path(__file__).resolve().parent
# A packaged build keeps user data (state, soundfonts) beside the exe and read-only assets in the bundle.
PROJECT_ROOT = Path(sys.executable).parent if FROZEN else PACKAGE_DIR.parents[1]
# A macOS app's executable sits in CouchDoom.app/Contents/MacOS; "beside the app" means the folder holding the .app.
APP_BUNDLE = FROZEN and sys.platform == "darwin" and PROJECT_ROOT.parent.name == "Contents"
if APP_BUNDLE:
    PROJECT_ROOT = PROJECT_ROOT.parents[2]
SOURCE_TREE = not FROZEN and (PROJECT_ROOT / "pyproject.toml").is_file()
ASSET_DIR = Path(sys._MEIPASS) / "assets" if FROZEN else PACKAGE_DIR / "assets"


def home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def xdg(var: str, default: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value and Path(value).is_absolute() else home() / default


def _user_data_dir() -> Path:
    """Where an installed copy (pip, AUR) keeps its state: the install dir itself is read-only."""
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or home() / "AppData" / "Local") / "CouchDoom"
    if sys.platform == "darwin":
        return home() / "Library" / "Application Support" / "CouchDoom"
    return xdg("XDG_DATA_HOME", ".local/share") / "couch-doom"


# The app bundle can't hold state: Gatekeeper may run a downloaded app from a read-only, randomized copy.
DATA_DIR = PROJECT_ROOT if (FROZEN and not APP_BUNDLE) or SOURCE_TREE else _user_data_dir()
# The author's own launcher folder, searched only when running from source; a release must not list it.
DEV_LAUNCHERS = Path(r"D:\Standalone\UZDoom") if SOURCE_TREE and os.name == "nt" else None
DEFAULT_OPTIONS = Path(r"D:\Standalone\UZDoom\DoomRunner\options.json")
STATE_DIR = DATA_DIR / "state"
STATE_FILE = STATE_DIR / "last_played.json"
LOG_FILE = STATE_DIR / "couch-doom.log"
