"""Ask GitHub whether a newer release exists. Never raises: offline, rate limits and odd replies all mean "no news"."""
from __future__ import annotations

import json
import os
import re
import urllib.request

API = "https://api.github.com/repos/KrisEnigma/couch-doom/releases/latest"
TIMEOUT = 4.0
MAX_NOTES = 4


def parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", text.split("-")[0].lstrip("vV")))


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return bool(a) and a > b  # tuples, so 0.10.0 beats 0.9.0


def _plain(line: str) -> str:
    line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)  # markdown links keep their text
    return re.sub(r"[*`]", "", line).strip()


def whats_new(body: str, version: str) -> list[str]:
    """The bullets under this release's "New in X" heading in the release notes, as plain text."""
    out: list[str] = []
    inside = False
    for raw in body.splitlines():
        line = raw.strip()
        if re.match(r"\*\*New in ", line):
            if inside:
                break
            inside = parse_version(line) == parse_version(version)
        elif inside and line.startswith(("- ", "* ")):
            out.append(_plain(line[2:]))
    return out[:MAX_NOTES]


def disabled() -> bool:
    return bool(os.environ.get("COUCHDOOM_NO_UPDATE_CHECK"))


def check(current: str, skipped: str | None = None) -> dict | None:
    """{"version", "current", "notes", "url"} when a newer, not-skipped release exists, else None."""
    if disabled():
        return None
    try:
        req = urllib.request.Request(API, headers={"User-Agent": f"CouchDoom/{current}", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.load(resp)
        tag = str(data["tag_name"])
        url = str(data["html_url"])
        body = str(data.get("body") or "")
    except (OSError, ValueError, KeyError, TypeError):
        return None
    version = tag.lstrip("vV")
    if not is_newer(version, current) or version == skipped:
        return None
    if not url.startswith("https://github.com/"):
        return None
    return {"version": version, "current": current, "notes": whats_new(body, version), "url": url}
