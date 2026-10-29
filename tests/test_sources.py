from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from couch_doom.sources import discover
from couch_doom.sources import doomrunner


class PortableDoomRunnerDiscoveryTests(unittest.TestCase):
    def test_discovers_doomrunner_in_sibling_folder_of_packaged_app(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "random-game-folder"
            app_dir = root / "CouchDoom"
            launcher_dir = root / "DoomRunner"
            app_dir.mkdir(parents=True)
            launcher_dir.mkdir()
            options = launcher_dir / "options.json"
            options.write_text("{}", encoding="utf-8")

            with patch.object(doomrunner, "FROZEN", True), \
                 patch.object(doomrunner, "PROJECT_ROOT", app_dir), \
                 patch.object(doomrunner, "DEV_LAUNCHERS", None), \
                 patch.dict(os.environ, {"LOCALAPPDATA": str(root / "empty-local"),
                                         "APPDATA": str(root / "empty-roaming")}), \
                 patch("couch_doom.sources.shortcuts.targets", return_value=[]):
                found = discover(only="doomrunner")

            self.assertEqual([choice.path for choice in found], [options])


if __name__ == "__main__":
    unittest.main()
