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


_ABOUT_STEMS = ("about",)
_SKIP_STEMS = re.compile(r"change|history|credit|licen[sc]e|install|manual|added|todo|whatsnew|news|errata|bugs", re.I)
_GAME_FILE_EXTS = {".wad", ".pk3", ".pk7", ".ipk3", ".pke"}
_VERSION_TAIL_RE = re.compile(r"[ _\-]+v?\d+([._]\d+)*[a-z]?$", re.I)


def _inside(path: Path) -> tuple[str, bytes, bool] | None:
    """A readme at the root of a pk3/zip: (name, text, strong). A credits file alone is weak, because a readme
    sitting beside the archive under another name tells the player more."""
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
            if s == stem:
                rank = 0
            elif s.startswith(README_STEMS[:3]):
                rank = 1
            elif s.startswith(_ABOUT_STEMS):
                rank = 2
            elif s.startswith("credits"):
                rank = 3
            else:
                continue
            if best is None or rank < best[0]:
                best = (rank, real)
        return (best[1], a.read(best[1]), best[0] <= 1) if best else None
    finally:
        a.close()


def _squash(stem: str) -> str:
    """'Eviternity II' and 'eviternityii', 'aaliens_v1_2' and 'aaliens' compare equal."""
    while (shorter := _VERSION_TAIL_RE.sub("", stem)) != stem and shorter:
        stem = shorter
    return re.sub(r"[^a-z0-9]", "", stem.lower())


def _beside_fuzzy(path: Path) -> Path | None:
    """A text file beside `path` that is plainly its readme although the name doesn't match exactly.

    Two safe cases: the names agree once spacing and version tails are ignored, or the folder holds only this one
    game file and a single readme-looking text. A folder of unrelated downloads gets no guess at all: a blank
    beats another mod's text."""
    folder = path.parent
    try:
        texts = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in (".txt", ".md", ".nfo")
                 and f.stem.lower() != path.stem.lower() and not _SKIP_STEMS.search(f.stem)]
        games = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in _GAME_FILE_EXTS]
    except OSError:
        return None
    mine = _squash(path.stem)
    if len(mine) >= 4:
        close = [f for f in texts if len(t := _squash(f.stem)) >= 4 and (t == mine or t.startswith(mine) or mine.startswith(t))]
        if len(close) == 1:
            return close[0]
    if len(games) <= 1:
        looks = [f for f in texts if re.search(r"read[ _]?me", f.stem, re.I)]
        if len(looks) > 1:
            looks = [f for f in looks if re.search(r"(^|[ _\-])(eng|en|english)([ _\-]|$)", f.stem, re.I)]
        if len(looks) == 1:
            return looks[0]
    return None


def _read_beside(txt: Path) -> Readme | None:
    try:
        text = _decode(txt.read_bytes())
    except OSError:
        return None
    return Readme(txt.name, text, parse_fields(text))


_DATE_RE = re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$")


def _object_strings(blob: bytes) -> list[str]:
    """The text values of a .NET BinaryFormatter file (record type 6, a length-prefixed UTF-8 string), in file order.

    The in-game mod browser saves each download's title, description and author this way. Reading the strings
    alone is enough, and avoids implementing the whole format."""
    out: list[str] = []
    i = 0
    while i < len(blob) - 6:
        if blob[i] == 6:
            j, n, shift = i + 5, 0, 0
            while j < len(blob):
                c = blob[j]
                j += 1
                n |= (c & 0x7F) << shift
                shift += 7
                if not c & 0x80:
                    break
            if 0 < n < 50000 and j + n <= len(blob):
                try:
                    out.append(blob[j : j + n].decode("utf-8"))
                    i = j + n
                    continue
                except UnicodeDecodeError:
                    pass
        i += 1
    return out


def _mod_metadata(path: Path) -> Readme | None:
    """The `metadata` file the in-game mod browser leaves beside a downloaded WAD: title, English description, author, date."""
    meta = path.parent / "metadata"
    try:
        if not meta.is_file() or meta.stat().st_size > MAX_BYTES:
            return None
        strings = _object_strings(meta.read_bytes())
        games = [f for f in path.parent.iterdir() if f.suffix.lower() in _GAME_FILE_EXTS]
    except OSError:
        return None
    # Layout: ... local path, file name, title, one description per language, author, type, date, screenshots.
    dates = [i for i, v in enumerate(strings) if _DATE_RE.match(v)]
    start = next((i for i, v in enumerate(strings) if v.startswith("/WADs/")), None)
    if not dates or start is None or dates[0] < start + 5 or len(strings) < start + 5:
        return None
    file_name, title, description = strings[start + 1], strings[start + 2], strings[start + 3]
    author, date = strings[dates[0] - 2], strings[dates[0]]
    if file_name.lower() != path.name.lower() and len(games) != 1:
        return None  # a folder of several downloads: this file's description may belong to another
    if len(description) < 40:
        return None
    text = _decode(description.encode("utf-8"))
    head = "\n".join(f"{k:<13}: {v}" for k, v in (("Title", title), ("Author", author), ("Release date", date)) if v)
    first = re.split(r"\n\s*\n", text.strip())[0]
    fields = {"title": title, "author": author, "date": date, "description": re.sub(r"\s+", " ", first).strip()}
    return Readme("mod browser", f"{head}\n\n{text}", {k: v for k, v in fields.items() if v})


_EMBEDDED = ("WADINFO", "README", "READ_ME", "TEXTFILE")


def _embedded(path: Path) -> Readme | None:
    """Some WADs carry their own text file as a lump (BTSX has a WADINFO in the idgames template)."""
    a = open_archive(path)
    if a is None or isinstance(a, Zip):
        if a:
            a.close()
        return None
    try:
        for name in (*_EMBEDDED, "CREDITS"):
            if (data := a.lump(name)) and len(data) > 80:
                text = _decode(data)
                if name == "CREDITS" or parse_fields(text):
                    return Readme(f"{path.name} \u203a {name}", text, parse_fields(text))
        return None
    finally:
        a.close()


def find_readme(preset: Preset) -> Readme | None:
    maps = [f for mp in preset.mappacks if mp.exists() for f in _expand_mappack(mp)]
    embedded = None
    for path in [*maps, *preset.mods]:
        if not path.is_file():
            continue
        if (txt := _beside(path)) and (found := _read_beside(txt)):
            return found
        inside = _inside(path)
        if inside and inside[2]:
            return Readme(f"{path.name} \u203a {inside[0]}", _decode(inside[1]), parse_fields(_decode(inside[1])))
        if found := _mod_metadata(path):
            return found
        if (txt := _beside_fuzzy(path)) and (found := _read_beside(txt)):
            return found
        if inside:  # only credits or an about file
            text = _decode(inside[1])
            return Readme(f"{path.name} \u203a {inside[0]}", text, parse_fields(text))
        if not embedded:
            embedded = _embedded(path)
    # The curated entries for the official games outrank a text a WAD happens to carry.
    return _known_readme(preset, [*maps, *preset.mods]) or embedded


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
