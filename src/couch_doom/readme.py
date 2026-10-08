"""Find and parse a preset's readme.

Looks at the map files first (they're usually what a preset is "about"), then mods. Accepts a
same-named .txt beside the file, or a readme/credits text at the root of a PK3/ZIP. Arbitrary
.txt lumps are ignored on purpose: PK3s are full of DECORATE.TXT, MAPINFO.TXT and friends.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .archive import Zip, open_archive
from .known import KNOWN
from .launch import _expand_mappack
from .options import Preset

MAX_BYTES = 256 * 1024
TEXT_EXTS = {".txt", ".nfo", ".md", ""}
README_STEMS = ("readme", "read_me", "read me", "credits", "about")

# idgames text-file template keys we surface, mapped to one canonical name.
_FIELDS = {
    "title": "title",
    "author": "author",
    "authors": "author",
    "author(s)": "author",
    "release date": "date",
    "date finished": "date",
    "date": "date",
    "description": "description",
}
_KEY_RE = re.compile(r"^\s{0,4}([A-Za-z][A-Za-z ()'/\-]{1,32}?)\s*:\s?(.*)$")
_YEAR_RE = re.compile(r"\b(19[89]\d|20\d\d)\b")
_CONTROL_RE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")  # font rendering rejects NULs; ^Z ends DOS files
_SHORT_DATE_RE = re.compile(r"\b\d{1,2}[/.\-]\d{1,2}[/.\-](\d{2})\b")


@dataclass
class Readme:
    source: str
    text: str
    fields: dict[str, str] = field(default_factory=dict)
    width: int | None = None  # longest line, filled in lazily by the viewer

    @property
    def author(self) -> str:
        return self.fields.get("author", "")

    @property
    def year(self) -> str:
        date = self.fields.get("date", "")
        if m := _YEAR_RE.search(date):
            return m.group(1)
        if m := _SHORT_DATE_RE.search(date):  # "03/28/10": Doom shipped in '93, so 93-99 are the 1900s
            yy = int(m.group(1))
            return str(1900 + yy if yy >= 93 else 2000 + yy)
        return ""

    @property
    def blurb(self) -> str:
        return self.fields.get("description", "")


def _decode(raw: bytes) -> str:
    raw = raw[:MAX_BYTES]
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # DOS box-drawing art lives in 0xB0-0xDF; otherwise high bytes are usually Latin-1 names.
        box = sum(1 for b in raw if 0xB0 <= b <= 0xDF)
        text = raw.decode("cp437" if box >= 8 else "cp1252", "replace")
    text = re.sub(r"\r*\n|\r", "\n", text).expandtabs(8)  # some editors wrote \r\r\n
    return _CONTROL_RE.sub("", text).rstrip()


def parse_fields(text: str) -> dict[str, str]:
    """Pull the idgames template fields; values may continue on indented lines."""
    fields: dict[str, str] = {}
    current: str | None = None
    for line in text.split("\n")[:400]:
        m = _KEY_RE.match(line)
        key = m and _FIELDS.get(re.sub(r"\s+", " ", m.group(1).strip().lower()))
        if key:
            current = key if key not in fields else None
            if current:
                fields[current] = m.group(2).strip()
            continue
        if current and line and not line.strip():
            continue  # space-padded "blank" lines are paragraph breaks inside a field; truly empty lines end it
        if current and line.strip() and line[:1].isspace() and not set(line.strip()) <= set("=-*_~#+| "):
            fields[current] = f"{fields[current]} {line.strip()}".strip()
            continue
        current = None
    return {k: re.sub(r"\s+", " ", v).strip() for k, v in fields.items() if v.strip()}


def _beside(path: Path) -> Path | None:
    for ext in (".txt", ".TXT"):
        candidate = path.with_suffix(ext)
        if candidate != path and candidate.is_file():
            return candidate
    return None


def _inside(path: Path) -> tuple[str, bytes] | None:
    a = open_archive(path)
    if not isinstance(a, Zip):
        if a:
            a.close()
        return None
    try:
        stem = path.stem.lower()
        best = None
        for n, real in a.names.items():
            if "/" in n:
                continue
            p = Path(n)
            if p.suffix.lower() not in TEXT_EXTS:
                continue
            s = p.stem.lower()
            rank = 0 if s == stem else 1 if s.startswith(README_STEMS) else None
            if rank is not None and (best is None or rank < best[0]):
                best = (rank, real)
        return (best[1], a.read(best[1])) if best else None
    finally:
        a.close()


def find_readme(preset: Preset) -> Readme | None:
    maps = [f for mp in preset.mappacks if mp.exists() for f in _expand_mappack(mp)]
    for path in [*maps, *preset.mods]:
        if not path.is_file():
            continue
        if txt := _beside(path):
            try:
                text = _decode(txt.read_bytes())
            except OSError:
                continue
            return Readme(txt.name, text, parse_fields(text))
        if found := _inside(path):
            name, raw = found
            text = _decode(raw)
            return Readme(f"{path.name} › {name}", text, parse_fields(text))
    return _known_readme(preset, [*maps, *preset.mods])


def _known_readme(preset: Preset, files: list[Path]) -> Readme | None:
    """The official IWADs and add-ons ship without readmes. The IWAD only speaks for a preset that loads nothing else,
    so a mod on top of Doom II never gets Doom II's blurb."""
    candidates = files if files else [preset.iwad] if preset.iwad else []
    info = next((k for f in candidates if (k := KNOWN.get(f.name.lower()))), None)
    if info is None:
        return None
    rows = [("Title", info.title), ("Author", info.author), ("Release date", info.year)]
    head = "\n".join(f"{k:<13}: {v}" for k, v in rows if v)
    fields = {"title": info.title, "author": info.author, "date": info.year, "description": info.description}
    return Readme(info.source, f"{head}\n\n{info.description}", {k: v for k, v in fields.items() if v})
