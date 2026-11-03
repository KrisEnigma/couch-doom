"""The tinysoundfont patch must remove one store and leave a fixed header alone."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

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
