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


def normalize_language_tag(tag: str | None) -> str:
    if not tag:
        return "en"
    raw = tag.replace("-", "_").split(".")[0]
    if raw in LANGUAGE_CODES:
        return raw
    primary = raw.split("_", 1)[0].lower()
    if primary == "pt":
        return "pt_BR"
    for code, _ in LANGUAGES:
        if code.lower() == primary or code.split("_", 1)[0].lower() == primary:
            return code
    return "en"


def detect_system_language() -> str:
    getters = (locale.getlocale, getattr(locale, "getdefaultlocale", lambda: (None, None)))
    for getter in getters:
        try:
            lang, _ = getter()
        except (TypeError, ValueError):
            lang = None
        if lang:
            return normalize_language_tag(lang)
    return "en"


set_language("en")
