"""Ask GitHub whether a newer release exists. Never raises: offline, rate limits and odd replies all mean "no news"."""
from __future__ import annotations

import json
import os
import platform as _platform
import re
import sys
from dataclasses import dataclass
import urllib.request

API = "https://api.github.com/repos/KrisEnigma/couch-doom/releases/latest"
TIMEOUT = 4.0
MAX_NOTES = 4


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str
    sha256_url: str
    target: str


def asset_for_platform(os_name: str, machine: str) -> str | None:
    os_name, machine = os_name.lower(), machine.lower()
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    if os_name in ("win32", "windows") and arch == "x64":
        return "windows-x64"
    if os_name in ("darwin", "mac", "macos") and arch:
        return f"macos-{arch}"
    if os_name.startswith("linux") and arch:
        return f"linux-{arch}"
    return None


def _fetch_latest() -> dict:
    req = urllib.request.Request(API, headers={"User-Agent": "CouchDoom", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.load(resp)


def _release_asset(data: dict, tag: str, target: str | None) -> ReleaseAsset | None:
    if not target:
        return None
    suffix = ".zip" if target.startswith(("windows-", "macos-")) else ".tar.gz"
    name = f"CouchDoom-{tag}-{target}{suffix}"
    found = {str(item.get("name")): str(item.get("browser_download_url", ""))
             for item in data.get("assets", []) if isinstance(item, dict)}
    url, digest_url = found.get(name, ""), found.get(name + ".sha256", "")
    if url.startswith("https://github.com/") and digest_url.startswith("https://github.com/"):
        return ReleaseAsset(name, url, digest_url, target)
    return None


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


def check(current: str, skipped: str | None = None, *, platform: str | None = None) -> dict | None:
    """{"version", "current", "notes", "url"} when a newer, not-skipped release exists, else None."""
    if disabled():
        return None
    try:
        data = _fetch_latest()
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
    target = platform or asset_for_platform(sys.platform, _platform.machine())
    return {"version": version, "current": current, "notes": whats_new(body, version), "url": url,
            "asset": _release_asset(data, tag, target)}
