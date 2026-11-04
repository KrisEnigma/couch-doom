"""Ask GitHub whether a newer release exists. Never raises: offline, rate limits and odd replies all mean "no news"."""
from __future__ import annotations

import json
import os
import platform as _platform
import re
import ssl
import subprocess
import sys
from dataclasses import dataclass
import urllib.request

import certifi

from . import log

API = "https://api.github.com/repos/KrisEnigma/couch-doom/releases/latest"
TIMEOUT = 10.0
MAX_NOTES = 5


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str
    sha256_url: str
    target: str


def native_machine() -> str:
    """The CPU the Mac actually has. An Intel build under Rosetta reports x86_64 from platform.machine(),
    so asking that would keep the updater on the Intel download forever."""
    if sys.platform == "darwin":
        try:
            done = subprocess.run(["sysctl", "-n", "hw.optional.arm64"], capture_output=True, text=True,
                                  timeout=2, check=False)
            if done.stdout.strip() == "1":
                return "arm64"
        except (OSError, subprocess.SubprocessError):
            pass
    return _platform.machine()


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


def https_context() -> ssl.SSLContext:
    """The bundled CA store. A frozen macOS build has no system certificates, so the default context fails verification."""
    return ssl.create_default_context(cafile=certifi.where())


def _fetch_latest() -> dict:
    test_manifest = os.environ.get("COUCHDOOM_UPDATE_TEST_MANIFEST")
    if test_manifest:
        with open(test_manifest, encoding="utf-8") as stream:
            return json.load(stream)
    req = urllib.request.Request(API, headers={"User-Agent": "CouchDoom", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=https_context()) as resp:
        return json.load(resp)


def _release_asset(data: dict, tag: str, target: str | None) -> ReleaseAsset | None:
    if not target:
        return None
    suffix = ".zip" if target.startswith(("windows-", "macos-")) else ".tar.gz"
    name = f"CouchDoom-{tag}-{target}{suffix}"
    found = {str(item.get("name")): str(item.get("browser_download_url", ""))
             for item in data.get("assets", []) if isinstance(item, dict)}
    url, digest_url = found.get(name, ""), found.get(name + ".sha256", "")
    def allowed(value: str) -> bool:
        return value.startswith("https://github.com/") or (
            bool(os.environ.get("COUCHDOOM_UPDATE_TEST_MANIFEST")) and value.startswith("file://"))
    if allowed(url) and allowed(digest_url):
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
    return out


def disabled() -> bool:
    return bool(os.environ.get("COUCHDOOM_NO_UPDATE_CHECK"))


def process_is_translated() -> bool:
    """An Intel build on Apple Silicon (or the reverse). `platform.machine()` is the slice, not the Mac."""
    if sys.platform != "darwin":
        return False
    native = native_machine()
    return bool(native) and native != _platform.machine()


def check(current: str, skipped: str | None = None, *, platform: str | None = None) -> dict | None:
    """Release metadata, including whether the displayed notes omit extra entries."""
    if disabled():
        return None
    try:
        data = _fetch_latest()
        tag = str(data["tag_name"])
        url = str(data["html_url"])
        body = str(data.get("body") or "")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.write("update check failed", f"{type(exc).__name__}: {exc}")
        return None
    version = tag.lstrip("vV")
    if version == skipped:
        log.write("update check", f"Latest release {version} was skipped.")
        return None
    if not url.startswith("https://github.com/"):
        return None
    # `platform` is a test override. Only a real translated process may replace its own version:
    # an Intel 1.2.5 on Apple Silicon is not newer than 1.2.5, but it is the wrong download,
    # and Rosetta retranslates that whole app the first time the new files run.
    target = platform or asset_for_platform(sys.platform, native_machine())
    switching = platform is None and process_is_translated() and parse_version(version) == parse_version(current)
    if not is_newer(version, current) and not switching:
        log.write("update check", f"Current version {current}; latest release is {version}.")
        return None
    if switching:
        log.write("update check", f"This {_platform.machine()} build is running on {native_machine()}; offering {target} of {version}.")
    notes = whats_new(body, version)
    native_arm = (target or "").endswith("arm64")
    return {"version": version, "current": current, "notes": notes[:MAX_NOTES],
            "more_notes": len(notes) > MAX_NOTES, "url": url, "arch_switch": switching,
            "native_label": "Apple Silicon" if native_arm else "Intel",
            "running_label": "Intel" if native_arm else "Apple Silicon",
            "asset": _release_asset(data, tag, target)}
