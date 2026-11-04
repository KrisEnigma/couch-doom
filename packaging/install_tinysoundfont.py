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
import os
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


def wheel_dir_from_env() -> Path | None:
    """Where a previous run left the patched wheel. CI caches this directory between builds."""
    raw = os.environ.get("COUCHDOOM_WHEEL_DIR")
    return Path(raw) if raw else None


def cached_wheels(wheel_dir: Path) -> list[Path]:
    if not wheel_dir.is_dir():
        return []
    return sorted(wheel_dir.glob(f"tinysoundfont-{VERSION}-*.whl"))


def _install_cached_wheel(python: str, wheel_dir: Path | None) -> bool:
    """Install a wheel built earlier for this platform. An incompatible wheel is left for the next one."""
    if wheel_dir is None:
        return False
    for wheel in cached_wheels(wheel_dir):
        result = subprocess.run([python, "-m", "pip", "install", "--no-deps", str(wheel)], check=False)
        if result.returncode == 0:
            print(f"tinysoundfont: using cached {wheel.name}", flush=True)
            return True
    return False


def _store_wheel(python: str, source: Path, wheel_dir: Path) -> None:
    """Compile the patched source into `wheel_dir`, replacing any wheel already there, and install that."""
    wheel_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tinysoundfont-wheel-") as tmp:
        out = Path(tmp)
        _run([python, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-w", str(out), str(source)])
        built = next(cached_wheels(out))
        for old in cached_wheels(wheel_dir):
            old.unlink()
        stored = wheel_dir / built.name
        shutil.copy2(built, stored)
    _run([python, "-m", "pip", "install", "--no-deps", str(stored)])


def install(python: str = sys.executable, wheel_dir: Path | None = None) -> None:
    wheel_dir = wheel_dir_from_env() if wheel_dir is None else wheel_dir
    if _install_cached_wheel(python, wheel_dir):
        return
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
        if wheel_dir is not None:
            _store_wheel(python, source, wheel_dir)
        else:
            _run([python, "-m", "pip", "install", "--no-deps", "--no-build-isolation", str(source)])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable, help="Interpreter to install into")
    args = parser.parse_args()
    install(args.python)


if __name__ == "__main__":
    main()
