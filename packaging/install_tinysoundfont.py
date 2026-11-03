"""Install tinysoundfont with its sample-buffer pointer fixed.

tinysoundfont 0.3.7 vendors a TinySoundFont that, after shrinking the decoded sample
buffer, stores the pointer from before realloc instead of the pointer realloc returned.
When realloc moves the block, rendering reads freed samples and quitting frees them
again. macOS malloc moves that block in the full app, so the Intel build aborts on
every quit. Upstream TinySoundFont does not have the extra store. A plain
`pip install tinysoundfont` gets a wheel that still has it, so the release build
installs the source and removes the line first.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def _extract(archive: Path, dest: Path) -> None:
    """Extract a source tarball. filter='data' exists only on Python 3.12 and later."""
    dest = dest.resolve()
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            if target != dest and dest not in target.parents:
                raise ValueError(f"refusing to extract {member.name}")
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dest, filter="data")
        else:
            tar.extractall(dest)

VERSION = "0.3.7"

# The realloc result is kept on the line above. This following store puts the freed pointer back.
BAD_STORE = "\t*pFloatBuffer = res;\n"
TRIM = (
    "\tif (!(*pFloatBuffer = (float*)TSF_REALLOC(res, resNum * sizeof(float)))) *pFloatBuffer = res;\n"
    + BAD_STORE
)


def patch_tsf_header(text: str) -> str:
    """Drop the store that overwrites realloc's return value. Already-fixed text is left as it is."""
    if TRIM not in text:
        if BAD_STORE in text:
            raise ValueError("tinysoundfont's tsf.h has the bad store, but not where the patch expects it")
        return text
    return text.replace(TRIM, TRIM.replace(BAD_STORE, ""), 1)


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def install(python: str = sys.executable) -> None:
    with tempfile.TemporaryDirectory(prefix="tinysoundfont-src-") as tmp:
        root = Path(tmp)
        _run([python, "-m", "pip", "download", "--no-deps", "--no-binary=:all:",
              "-d", str(root), f"tinysoundfont=={VERSION}"])
        archive = next(root.glob("tinysoundfont-*.tar.gz"))
        _extract(archive, root)
        header = next(path for path in root.rglob("tsf.h") if "tsf" in path.parts)
        original = header.read_text(encoding="utf-8")
        patched = patch_tsf_header(original)
        if patched == original and TRIM.split(BAD_STORE)[0] not in original:
            raise ValueError(f"tinysoundfont {VERSION} no longer has the sample-buffer trim this patch knows")
        header.write_text(patched, encoding="utf-8")
        source = header
        while not (source / "pyproject.toml").is_file():
            if source.parent == source:
                raise ValueError("tinysoundfont source has no pyproject.toml")
            source = source.parent
        build_tools = ["scikit-build-core", "pybind11"]
        # The pip copies are large. Use the compiler tools already on PATH when a release image has them.
        if shutil.which("cmake") is None:
            build_tools.append("cmake")
        if shutil.which("ninja") is None:
            build_tools.append("ninja")
        _run([python, "-m", "pip", "install", *build_tools])
        _run([python, "-m", "pip", "install", "--no-deps", "--no-build-isolation", str(source)])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable, help="Interpreter to install into")
    args = parser.parse_args()
    install(args.python)


if __name__ == "__main__":
    main()
