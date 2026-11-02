"""In-process UI catalogs. English is the source of truth and the fallback."""
from __future__ import annotations

import json
import locale
import sys
from pathlib import Path

from .config import FROZEN, PACKAGE_DIR

# Packaged builds keep catalogs next to assets under _MEIPASS; source/pip keep them beside this module.
LOCALES_DIR = Path(sys._MEIPASS) / "locales" if FROZEN else PACKAGE_DIR / "locales"
LANGUAGES = [
    ("en", "lang.en"),
    ("es", "lang.es"),
    ("pt_BR", "lang.pt_BR"),
    ("fr", "lang.fr"),
    ("de", "lang.de"),
]
LANGUAGE_CODES = {code for code, _ in LANGUAGES}

_catalog: dict[str, str] = {}
_english: dict[str, str] = {}
_current = "en"


def load_catalog(code: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{code}.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def set_language(code: str) -> str:
    global _catalog, _english, _current
    if not _english:
        _english = load_catalog("en")
    code = code if code in LANGUAGE_CODES else "en"
    _current = code
    _catalog = _english if code == "en" else {**_english, **load_catalog(code)}
    return _current


def current_language() -> str:
    return _current


def t(key: str, **kwargs) -> str:
    template = _catalog.get(key) or _english.get(key) or key
    if kwargs:
        try:
            return template.format_map(kwargs)
        except (KeyError, ValueError):
            return template
    return template


# Windows' getlocale() reports names like "Spanish_Chile" rather than "es_CL".
_ENGLISH_NAMES = {"english": "en", "spanish": "es", "portuguese": "pt_BR", "french": "fr", "german": "de"}


def normalize_language_tag(tag: str | None) -> str:
    if not tag:
        return "en"
    raw = tag.replace("-", "_").split(".")[0]
    if raw in LANGUAGE_CODES:
        return raw
    primary = raw.split("_", 1)[0].lower()
    if primary in _ENGLISH_NAMES:
        return _ENGLISH_NAMES[primary]
    if primary == "pt":
        return "pt_BR"
    for code, _ in LANGUAGES:
        if code.lower() == primary or code.split("_", 1)[0].lower() == primary:
            return code
    return "en"


def _windows_ui_language() -> str | None:
    """The display language chosen in Windows Settings, which can differ from the regional format."""
    try:
        import ctypes
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return None
    return locale.windows_locale.get(langid)


def _macos_ui_language() -> str | None:
    """First entry of the macOS preferred languages; Finder launches get no LANG to read instead."""
    import subprocess
    try:
        out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        entry = line.strip().strip(",").strip('"')
        if entry and entry not in "()":
            return entry
    return None


def _environment_language() -> str | None:
    import os
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name, "").split(":")[0]
        if value and value not in ("C", "POSIX") and not value.startswith("C."):
            return value
    return None


def _locale_language() -> str | None:
    try:
        return locale.getlocale()[0]
    except (TypeError, ValueError):
        return None


def detect_system_language() -> str:
    getters = [_environment_language, _locale_language]
    if sys.platform == "win32":
        getters.insert(0, _windows_ui_language)
    elif sys.platform == "darwin":
        getters.insert(0, _macos_ui_language)
    for getter in getters:
        if tag := getter():
            return normalize_language_tag(tag)
    return "en"


set_language("en")
