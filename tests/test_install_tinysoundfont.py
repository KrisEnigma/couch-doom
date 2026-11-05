"""The tinysoundfont patch must remove one store and leave a fixed header alone."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_spec = importlib.util.spec_from_file_location(
    "install_tinysoundfont",
    Path(__file__).resolve().parents[1] / "packaging" / "install_tinysoundfont.py",
)
install_tinysoundfont = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install_tinysoundfont)


class TinysoundfontPatchTests(unittest.TestCase):
    def test_patch_drops_the_store_of_the_pre_realloc_pointer(self):
        header = "before\n" + install_tinysoundfont.TRIM + "after\n"
        patched = install_tinysoundfont.patch_tsf_header(header)
        self.assertNotIn(install_tinysoundfont.BAD_STORE, patched)
        self.assertIn("TSF_REALLOC(res, resNum * sizeof(float))", patched)
        self.assertEqual(patched.count("TSF_REALLOC(res, resNum"), 1)

    def test_patch_leaves_an_already_fixed_header_unchanged(self):
        fixed = install_tinysoundfont.TRIM.replace(install_tinysoundfont.BAD_STORE, "")
        self.assertEqual(install_tinysoundfont.patch_tsf_header(fixed), fixed)

    def test_patch_refuses_a_header_where_the_bad_store_moved(self):
        with self.assertRaises(ValueError):
            install_tinysoundfont.patch_tsf_header("\t*pFloatBuffer = res;\n")

    def test_a_cached_wheel_is_installed_without_compiling(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            wheel_dir = Path(tmp)
            wheel = wheel_dir / f"tinysoundfont-{install_tinysoundfont.VERSION}-cp314-cp314-py3-none-any.whl"
            wheel.write_bytes(b"")
            seen: list[list[str]] = []

            def run(cmd, check=False):
                seen.append(list(cmd))
                return subprocess.CompletedProcess(cmd, 0)

            with patch.object(install_tinysoundfont.subprocess, "run", run):
                install_tinysoundfont.install(sys.executable, wheel_dir)
        self.assertEqual(seen, [[sys.executable, "-m", "pip", "install", "--no-deps", str(wheel)]])

    def test_store_wheel_compiles_copies_and_installs(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_wheel, tempfile.TemporaryDirectory() as tmp_src:
            wheel_dir = Path(tmp_wheel)
            source_dir = Path(tmp_src)
            (source_dir / "pyproject.toml").write_text("", encoding="utf-8")
            old_wheel = wheel_dir / f"tinysoundfont-{install_tinysoundfont.VERSION}-old.whl"
            old_wheel.write_bytes(b"old")
            seen: list[list[str]] = []

            def run(cmd, check=False):
                seen.append(list(cmd))
                if cmd[1:4] == ["-m", "pip", "wheel"]:
                    out_idx = cmd.index("-w") + 1
                    out_dir = Path(cmd[out_idx])
                    target = out_dir / f"tinysoundfont-{install_tinysoundfont.VERSION}-cp314-cp314-test.whl"
                    target.write_bytes(b"new")
                return subprocess.CompletedProcess(cmd, 0)

            with patch.object(install_tinysoundfont, "_run", run):
                install_tinysoundfont._store_wheel(sys.executable, source_dir, wheel_dir)

            expected_stored = wheel_dir / f"tinysoundfont-{install_tinysoundfont.VERSION}-cp314-cp314-test.whl"
            self.assertTrue(expected_stored.is_file())
            self.assertFalse(old_wheel.exists())
            self.assertEqual(seen[-1], [sys.executable, "-m", "pip", "install", "--no-deps", str(expected_stored)])

