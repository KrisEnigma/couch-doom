from __future__ import annotations

import hashlib
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from couch_doom import self_update, update
from couch_doom.__main__ import main
from couch_doom.ui import update_choices


class ReleaseTargetTests(unittest.TestCase):
    def test_target_mapping(self):
        self.assertEqual(update.asset_for_platform("win32", "AMD64"), "windows-x64")
        self.assertEqual(update.asset_for_platform("darwin", "arm64"), "macos-arm64")
        self.assertEqual(update.asset_for_platform("darwin", "x86_64"), "macos-x64")
        self.assertEqual(update.asset_for_platform("linux", "aarch64"), "linux-arm64")
        self.assertIsNone(update.asset_for_platform("linux", "riscv64"))

    def test_release_check_selects_matching_archive_and_digest_sidecar(self):
        assets = [
            {"name": "CouchDoom-v1.2.0-windows-x64.zip", "browser_download_url": "https://github.com/KrisEnigma/couch-doom/releases/download/v1.2.0/CouchDoom-v1.2.0-windows-x64.zip"},
            {"name": "CouchDoom-v1.2.0-windows-x64.zip.sha256", "browser_download_url": "https://github.com/KrisEnigma/couch-doom/releases/download/v1.2.0/CouchDoom-v1.2.0-windows-x64.zip.sha256"},
        ]
        with patch.object(update, "_fetch_latest", return_value={
            "tag_name": "v1.2.0", "html_url": "https://github.com/KrisEnigma/couch-doom/releases/tag/v1.2.0",
            "body": "", "assets": assets,
        }):
            info = update.check("1.0.0", platform="windows-x64")
        self.assertIsNotNone(info)
        self.assertEqual(info["asset"].name, assets[0]["name"])
        self.assertEqual(info["asset"].sha256_url, assets[1]["browser_download_url"])

    def test_install_action_is_only_available_for_packaged_matching_release(self):
        self.assertEqual(update_choices({"asset": object()}, True)[0][0], "install")
        self.assertNotIn("install", [item[0] for item in update_choices({"asset": object()}, False)])
        self.assertNotIn("install", [item[0] for item in update_choices({"asset": None}, True)])

    def test_private_updater_mode_rejects_incomplete_arguments_before_ui(self):
        self.assertEqual(main(["--apply-update"]), 2)


class DownloadTests(unittest.TestCase):
    def test_download_checks_digest_before_extracting_zip(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as zf:
            zf.writestr("CouchDoom/CouchDoom.exe", b"app")
        archive = payload.getvalue()
        digest = hashlib.sha256(archive).hexdigest()

        class Response(io.BytesIO):
            headers = {"Content-Length": str(len(archive))}
            def __enter__(self): return self
            def __exit__(self, *args): self.close()

        def open_url(request, timeout):
            return Response(archive if request.full_url.endswith(".zip") else f"{digest}  CouchDoom-v1.2.0-windows-x64.zip\n".encode())

        asset = update.ReleaseAsset(
            name="CouchDoom-v1.2.0-windows-x64.zip",
            url="https://github.com/KrisEnigma/couch-doom/releases/download/v1.2.0/archive.zip",
            sha256_url="https://github.com/KrisEnigma/couch-doom/releases/download/v1.2.0/archive.zip.sha256",
            target="windows-x64",
        )
        with tempfile.TemporaryDirectory() as temp, patch.object(self_update.urllib.request, "urlopen", side_effect=open_url):
            staged = self_update.download_and_stage(asset, "1.2.0", staging_root=Path(temp), platform="windows-x64")
            self.assertEqual((staged.app_path / "CouchDoom.exe").read_bytes(), b"app")

    def test_archive_traversal_is_rejected(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../escaped", b"bad")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(self_update.UpdateError):
                self_update._extract_zip(archive.getvalue(), Path(temp) / "stage")
            self.assertFalse((Path(temp) / "escaped").exists())

    def test_internal_symlink_is_preserved_and_escaping_symlink_rejected(self):
        good = io.BytesIO()
        with zipfile.ZipFile(good, "w") as zf:
            zf.writestr("CouchDoom/real", b"payload")
            link = zipfile.ZipInfo("CouchDoom/alias")
            link.create_system = 3
            link.external_attr = (0o120777 << 16)
            zf.writestr(link, "real")
        bad = io.BytesIO()
        with zipfile.ZipFile(bad, "w") as zf:
            link = zipfile.ZipInfo("CouchDoom/escape")
            link.create_system = 3
            link.external_attr = (0o120777 << 16)
            zf.writestr(link, "../../outside")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            if os.name != "nt":
                self_update._extract_zip(good.getvalue(), root / "good")
                self.assertTrue((root / "good/CouchDoom/alias").is_symlink())
            with self.assertRaises(self_update.UpdateError):
                if os.name == "nt":
                    self_update._safe_link(root, root / "link", "../../outside")
                else:
                    self_update._extract_zip(bad.getvalue(), root / "bad")

    def test_update_keeps_portable_state_and_replaces_program_files(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            install, staged = base / "CouchDoom", base / "new" / "CouchDoom"
            (install / "state").mkdir(parents=True)
            (install / "state" / "last_played.json").write_text("saved")
            (install / "CouchDoom.exe").write_text("old")
            staged.mkdir(parents=True)
            (staged / "CouchDoom.exe").write_text("new")
            with patch.object(self_update, "_wait_for_exit"):
                self_update.apply_staged_update(staged, install, pid=77, platform="windows-x64", relaunch=False)
            self.assertEqual((install / "CouchDoom.exe").read_text(), "new")
            self.assertEqual((install / "state" / "last_played.json").read_text(), "saved")

    def test_failed_relaunch_restores_and_reopens_previous_install(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            install, staged = base / "CouchDoom", base / "new" / "CouchDoom"
            install.mkdir()
            (install / "CouchDoom.exe").write_text("old")
            staged.mkdir(parents=True)
            (staged / "CouchDoom.exe").write_text("new")
            with patch.object(self_update, "_wait_for_exit"), patch.object(
                    self_update.subprocess, "Popen", side_effect=[OSError("failed"), object()]) as popen:
                with self.assertRaises(self_update.UpdateError):
                    self_update.apply_staged_update(staged, install, pid=78, platform="windows-x64")
            self.assertEqual((install / "CouchDoom.exe").read_text(), "old")
            self.assertEqual(popen.call_count, 2)

    def test_apply_helper_runs_from_a_copy_outside_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / "stage" / "extracted" / "CouchDoom"
            app.mkdir(parents=True)
            (app / "CouchDoom.exe").write_text("binary")
            staged = self_update.StagedUpdate("1.2.0", root / "stage", app, root / "archive.zip")
            install = root / "installed" / "CouchDoom"
            install.parent.mkdir()
            with patch.object(self_update.subprocess, "Popen") as popen:
                self_update.launch_apply_helper(staged, install, 42, "windows-x64")
            helper_argv = popen.call_args.args[0]
            self.assertNotEqual(Path(helper_argv[0]).parent, app)
            self.assertTrue(Path(helper_argv[0]).is_file())

    def test_wrong_digest_does_not_leave_partial_stage(self):
        class Response(io.BytesIO):
            headers = {"Content-Length": "3"}
            def __enter__(self): return self
            def __exit__(self, *args): self.close()

        def open_url(request, timeout):
            return Response(b"wrong" if request.full_url.endswith(".zip") else b"0" * 64)

        asset = update.ReleaseAsset(
            name="CouchDoom-v1.2.0-windows-x64.zip",
            url="https://github.com/KrisEnigma/couch-doom/releases/download/v1.2.0/archive.zip",
            sha256_url="https://github.com/KrisEnigma/couch-doom/releases/download/v1.2.0/archive.zip.sha256",
            target="windows-x64",
        )
        with tempfile.TemporaryDirectory() as temp, patch.object(self_update.urllib.request, "urlopen", side_effect=open_url):
            with self.assertRaises(self_update.UpdateError):
                self_update.download_and_stage(asset, "1.2.0", staging_root=Path(temp), platform="windows-x64")
            self.assertEqual(list(Path(temp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
