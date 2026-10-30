"""Render the Markdown changelog as a reader-facing plain-text file."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def convert(source: str) -> str:
    lines = source.splitlines()
    output = ["CouchDoom Changelog", "===================", ""]
    for line in lines:
        if line == "# Changelog" or line.startswith("Each release's notes on GitHub"):
            continue

        heading = re.fullmatch(r"\*\*New in ([^*]+)\*\*", line)
        if heading:
            if output[-1] != "":
                output.append("")
            title = f"Version {heading.group(1)}"
            output.extend((title, "-" * len(title)))
            continue

        line = re.sub(r"`([^`]*)`", r"\1", line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        line = re.sub(r"\*([^*]+)\*", r"\1", line)
        if not line and output[-1] == "":
            continue
        output.append(line)

    while output and not output[-1]:
        output.pop()
    return "\n".join(output) + "\n"


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: make_changelog_txt.py INPUT.md OUTPUT.txt")
    source, destination = map(Path, sys.argv[1:])
    destination.write_text(convert(source.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
