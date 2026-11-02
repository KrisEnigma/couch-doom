from __future__ import annotations

import hashlib
import io
import os
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from couch_doom import self_update, update
from couch_doom.__main__ import main
from couch_doom.ui import update_choices
from tests.make_update_test_manifest import write_manifest


class ReleaseTargetTests(unittest.TestCase):
    def test_latest_release_fetch_uses_bundled_ca_certificates(self):
        response = io.BytesIO(b'{"tag_name":"v1.0.0","html_url":"https://github.com/KrisEnigma/couch-doom/releases/tag/v1.0.0"}')
        context = object()
        with patch.object(update.certifi, "where", return_value="bundle/cacert.pem"), \
                patch.object(update.ssl, "create_default_context", return_value=context) as create_context, \
                patch.object(update.urllib.request, "urlopen", return_value=response) as urlopen:
            data = update._fetch_latest()

        self.assertEqual(data["tag_name"], "v1.0.0")
        create_context.assert_called_once_with(cafile="bundle/cacert.pem")
        self.assertIs(urlopen.call_args.kwargs["context"], context)

    def test_current_release_check_records_success_in_local_log(self):
        data = {
            "tag_name": "v1.0.0",
            "html_url": "https://github.com/KrisEnigma/couch-doom/releases/tag/v1.0.0",
            "body": "",
            "assets": [],
        }
        with patch.object(update, "_fetch_latest", return_value=data), \
                patch.object(update.log, "write") as write_log:
            result = update.check("1.0.0")

        self.assertIsNone(result)
        write_log.assert_called_once_with("update check", "Current version 1.0.0; latest release is 1.0.0.")

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

    def test_test_manifest_is_loaded_only_when_explicitly_enabled(self):
        data = {"tag_name": "v99.0.0", "html_url": "https://github.com/KrisEnigma/couch-doom/releases/tag/v99.0.0"}
        with tempfile.TemporaryDirectory() as temp:
            manifest = Path(temp) / "latest.json"
            manifest.write_text(json.dumps(data))
            with patch.dict(os.environ, {"COUCHDOOM_UPDATE_TEST_MANIFEST": str(manifest)}):
                self.assertEqual(update._fetch_latest(), data)

    def test_local_asset_urls_are_allowed_only_in_test_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "payload.txt"
            file.write_text("fixture")
            with self.assertRaises(self_update.UpdateError):
                self_update._request(file.as_uri())
            with patch.dict(os.environ, {"COUCHDOOM_UPDATE_TEST_MANIFEST": str(Path(temp) / "latest.json")}):
                with self_update._request(file.as_uri()) as response:
                    self.assertEqual(response.read(), b"fixture")

    def test_manifest_builder_repackages_local_artifact_with_matching_checksum(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "CouchDoom-dev-macos-arm64.zip"
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w") as zf:
                zf.writestr("CouchDoom/CouchDoom.app/Contents/MacOS/CouchDoom", b"app")
            source.write_bytes(payload.getvalue())
            manifest_path = write_manifest(source, root / "test-release", target="macos-arm64")
            manifest = json.loads(manifest_path.read_text())
            asset = manifest["assets"][0]
            self.assertEqual(asset["name"], "CouchDoom-v99.0.0-macos-arm64.zip")
            self.assertTrue(asset["browser_download_url"].startswith("file://"))
            with patch.dict(os.environ, {"COUCHDOOM_UPDATE_TEST_MANIFEST": str(manifest_path)}):
                info = update.check("0.6.0", platform="macos-arm64")
            self.assertEqual(info["asset"].name, asset["name"])
            with patch.dict(os.environ, {"COUCHDOOM_UPDATE_TEST_MANIFEST": str(manifest_path)}):
                staged = self_update.download_and_stage(info["asset"], info["version"],
                                                        staging_root=root / "staging", platform="macos-arm64")
            self.assertEqual((staged.app_path / "Contents/MacOS/CouchDoom").read_bytes(), b"app")


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

    def test_zip_executable_mode_is_preserved(self):
        if os.name == "nt":
            self.skipTest("Unix executable bits are not represented by Windows file permissions")
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            executable = zipfile.ZipInfo("CouchDoom/CouchDoom")
            executable.create_system = 3
            executable.external_attr = 0o100755 << 16
            zf.writestr(executable, b"app")
        with tempfile.TemporaryDirectory() as temp:
            self_update._extract_zip(archive.getvalue(), Path(temp) / "stage")
            mode = (Path(temp) / "stage/CouchDoom/CouchDoom").stat().st_mode
            self.assertTrue(mode & 0o111, oct(mode))

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

    def test_relaunched_app_does_not_inherit_local_test_manifest(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"COUCHDOOM_UPDATE_TEST_MANIFEST": "fixture.json"}):
            base = Path(temp)
            install, staged = base / "CouchDoom", base / "new" / "CouchDoom"
            install.mkdir()
            staged.mkdir(parents=True)
            (install / "CouchDoom.exe").write_text("old")
            (staged / "CouchDoom.exe").write_text("new")
            with patch.object(self_update, "_wait_for_exit"), patch.object(self_update.subprocess, "Popen") as popen:
                self_update.apply_staged_update(staged, install, pid=79, platform="windows-x64")
            self.assertNotIn("COUCHDOOM_UPDATE_TEST_MANIFEST", popen.call_args.kwargs["env"])
            self.assertTrue(popen.call_args.kwargs["start_new_session"])
            for stream in ("stdin", "stdout", "stderr"):
                self.assertIs(popen.call_args.kwargs[stream], self_update.subprocess.DEVNULL)

    def test_apply_helper_runs_from_a_copy_outside_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / "stage" / "extracted" / "CouchDoom"
            app.mkdir(parents=True)
            (app / "CouchDoom.exe").write_text("binary")
            (app / "CouchDoom.exe").chmod(0o755)
            staged = self_update.StagedUpdate("1.2.0", root / "stage", app, root / "archive.zip")
            install = root / "installed" / "CouchDoom"
            install.parent.mkdir()
            staged = self_update.prepare_apply_helper(staged, "windows-x64")
            with patch.object(self_update.subprocess, "Popen") as popen:
                self_update.launch_apply_helper(staged, install, 42, "windows-x64", root / "state" / "result.json")
            helper_argv = popen.call_args.args[0]
            self.assertEqual(helper_argv[-1], str(root / "state" / "result.json"))
            self.assertNotEqual(Path(helper_argv[0]).parent, app)
            self.assertTrue(Path(helper_argv[0]).is_relative_to(staged.root))
            self.assertTrue(Path(helper_argv[0]).is_file())
            self.assertTrue(popen.call_args.kwargs["start_new_session"])
            for stream in ("stdin", "stdout", "stderr"):
                self.assertIs(popen.call_args.kwargs[stream], self_update.subprocess.DEVNULL)

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

    def test_cancel_mid_download_removes_staging_dir(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as zf:
            zf.writestr("CouchDoom/CouchDoom.exe", b"app")
        archive = payload.getvalue()
        digest = hashlib.sha256(archive).hexdigest()
        cancel = __import__("threading").Event()

        class Response(io.BytesIO):
            headers = {"Content-Length": str(len(archive))}
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
            def read(self, size=-1):
                cancel.set()
                return super().read(size)

        def open_url(request, timeout):
            body = archive if request.full_url.endswith(".zip") else f"{digest}  CouchDoom-v1.2.0-windows-x64.zip\n".encode()
            return Response(body)

        asset = update.ReleaseAsset(
            name="CouchDoom-v1.2.0-windows-x64.zip",
            url="https://github.com/KrisEnigma/couch-doom/releases/download/v1.2.0/archive.zip",
            sha256_url="https://github.com/KrisEnigma/couch-doom/releases/download/v1.2.0/archive.zip.sha256",
            target="windows-x64",
        )
        with tempfile.TemporaryDirectory() as temp, patch.object(self_update.urllib.request, "urlopen", side_effect=open_url):
            with self.assertRaises(self_update.UpdateError):
                self_update.download_and_stage(
                    asset, "1.2.0", staging_root=Path(temp), platform="windows-x64", cancel=cancel)
            leftover = [p for p in Path(temp).iterdir() if p.name.startswith("couchdoom-update-")]
            self.assertEqual(leftover, [])

    def test_apply_removes_cleanup_root_staging_dir(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            staging = Path(tempfile.mkdtemp(prefix="couchdoom-update-", dir=base))
            install, staged = base / "CouchDoom", staging / "extracted" / "CouchDoom"
            install.mkdir()
            (install / "CouchDoom.exe").write_text("old")
            staged.mkdir(parents=True)
            (staged / "CouchDoom.exe").write_text("new")
            with patch.object(self_update, "_wait_for_exit"):
                self_update.apply_staged_update(
                    staged, install, pid=80, platform="windows-x64", relaunch=False, cleanup_root=staging)
            self.assertFalse(staging.exists())
            self.assertEqual([p.name for p in base.iterdir() if p.name.startswith("couchdoom-update-")], [])

    def test_orphan_staging_dirs_are_removed_by_purge(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            orphan = Path(tempfile.mkdtemp(prefix="couchdoom-update-", dir=root))
            (orphan / "partial.zip.part").write_text("leftover")
            keep = root / "CouchDoom"
            keep.mkdir()
            (keep / "CouchDoom.exe").write_text("app")

            self_update.purge_stale_update_dirs(root)

            self.assertFalse(orphan.exists())
            self.assertTrue(keep.exists())

    def test_new_download_purges_prior_orphan_staging_dirs(self):
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
            body = archive if request.full_url.endswith(".zip") else f"{digest}  CouchDoom-v1.2.0-windows-x64.zip\n".encode()
            return Response(body)

        asset = update.ReleaseAsset(
            name="CouchDoom-v1.2.0-windows-x64.zip",
            url="https://github.com/KrisEnigma/couch-doom/releases/download/v1.2.0/archive.zip",
            sha256_url="https://github.com/KrisEnigma/couch-doom/releases/download/v1.2.0/archive.zip.sha256",
            target="windows-x64",
        )
        with tempfile.TemporaryDirectory() as temp, patch.object(self_update.urllib.request, "urlopen", side_effect=open_url):
            root = Path(temp)
            orphan = Path(tempfile.mkdtemp(prefix="couchdoom-update-", dir=root))
            (orphan / "stuck.part").write_text("old")
            staged = self_update.download_and_stage(asset, "1.2.0", staging_root=root, platform="windows-x64")
            self.assertFalse(orphan.exists())
            self.assertTrue(staged.root.exists())
            self.assertTrue(staged.root.name.startswith("couchdoom-update-"))
            self_update.discard_staged(staged)


def _fake_release(files: dict[str, bytes]):
    """A zip release served through a patched urlopen, and its asset."""
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as zf:
        for name, data in files.items():
            # Unix mode bits, like the real packages: on Linux and macOS the helper must be executable.
            info = zipfile.ZipInfo(name)
            info.create_system, info.external_attr = 3, (0o100755 << 16)
            zf.writestr(info, data)
    archive = payload.getvalue()
    digest = hashlib.sha256(archive).hexdigest()

    class Response(io.BytesIO):
        headers = {"Content-Length": str(len(archive))}
        def __enter__(self): return self
        def __exit__(self, *args): self.close()

    def open_url(request, timeout):
        body = archive if request.full_url.endswith(".zip") else f"{digest}  CouchDoom-v1.2.0-windows-x64.zip\n".encode()
        return Response(body)

    asset = update.ReleaseAsset(
        name="CouchDoom-v1.2.0-windows-x64.zip",
        url="https://github.com/KrisEnigma/couch-doom/releases/download/v1.2.0/archive.zip",
        sha256_url="https://github.com/KrisEnigma/couch-doom/releases/download/v1.2.0/archive.zip.sha256",
        target="windows-x64",
    )
    return patch.object(self_update.urllib.request, "urlopen", side_effect=open_url), asset


class InstallFlowTests(unittest.TestCase):
    FILES = {"CouchDoom/CouchDoom.exe": b"app", "CouchDoom/lib/a.dll": b"a", "CouchDoom/lib/b.dll": b"b"}

    def test_phases_arrive_in_order_and_the_helper_is_ready(self):
        network, asset = _fake_release(self.FILES)
        seen: list[tuple[str, int, int | None]] = []
        with tempfile.TemporaryDirectory() as temp, network:
            staged = self_update.download_and_prepare(asset, "1.2.0", staging_root=Path(temp), platform="windows-x64",
                                                      progress=lambda *step: seen.append(step))
            self.assertTrue(staged.helper.is_file())
            self.assertTrue(staged.helper.is_relative_to(staged.root / "apply-helper"))
        phases = [phase for phase, _, _ in seen]
        order = [p for i, p in enumerate(phases) if i == 0 or phases[i - 1] != p]
        self.assertEqual(order, list(self_update.PHASES))
        unpacking = [(done, total) for phase, done, total in seen if phase == "unpacking"]
        self.assertEqual(unpacking[-1][0], unpacking[-1][1])
        self.assertEqual(unpacking[-1][1], len(self.FILES))

    def test_cancel_while_unpacking_stops_and_removes_the_stage(self):
        network, asset = _fake_release(self.FILES)
        cancel = __import__("threading").Event()

        def progress(phase, done, total):
            if phase == "unpacking" and done == 1:
                cancel.set()

        with tempfile.TemporaryDirectory() as temp, network:
            with self.assertRaises(self_update.UpdateError):
                self_update.download_and_prepare(asset, "1.2.0", staging_root=Path(temp), platform="windows-x64",
                                                 progress=progress, cancel=cancel)
            self.assertEqual([p for p in Path(temp).iterdir() if p.name.startswith("couchdoom-update-")], [])

    def test_unprepared_stage_is_not_launched(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            staged = self_update.StagedUpdate("1.2.0", root, root / "CouchDoom", root / "a.zip")
            with patch.object(self_update.subprocess, "Popen") as popen, self.assertRaises(self_update.UpdateError):
                self_update.launch_apply_helper(staged, root / "install", 1, "windows-x64")
            popen.assert_not_called()

    def test_finished_job_only_spawns_the_helper_on_the_ui_thread(self):
        from concurrent.futures import Future
        from couch_doom import ui

        staged = self_update.StagedUpdate("1.2.0", Path("stage"), Path("stage/app"), Path("a.zip"), Path("stage/helper"))
        job = Future()
        job.set_result(staged)
        app = ui.App.__new__(ui.App)
        app.update_install_job, app.update_cancel, app.update_job = job, None, None
        app.update = {"version": "1.2.0", "asset": SimpleNamespace(target="windows-x64")}
        app.restarting, app.quit_at = False, None
        app.ignore_until = 0.0
        no_copy = AssertionError("file copying belongs on the worker thread")
        with patch.object(self_update.shutil, "copytree", side_effect=no_copy), \
                patch.object(self_update, "prepare_apply_helper", side_effect=no_copy), \
                patch.object(self_update, "installation_path", return_value=Path("install")), \
                patch.object(self_update, "launch_apply_helper") as launch:
            app._poll_update(100.0)
        launch.assert_called_once()
        self.assertIs(launch.call_args.args[0], staged)
        self.assertEqual(launch.call_args.args[4].name, self_update.RESULT_FILE)
        self.assertTrue(app.restarting)
        self.assertGreater(app.quit_at, 100.0)


class ResultFileTests(unittest.TestCase):
    def _swap(self, base: Path, popen_effect=None):
        install, staged = base / "CouchDoom", base / "new" / "CouchDoom"
        install.mkdir()
        (install / "CouchDoom.exe").write_text("old")
        staged.mkdir(parents=True)
        (staged / "CouchDoom.exe").write_text("new")
        result = install / "state" / self_update.RESULT_FILE
        seen = []

        def relaunch(*args, **kwargs):
            seen.append(json.loads(result.read_text()) if result.exists() else None)
            if popen_effect:
                effect = popen_effect.pop(0)
                if effect:
                    raise effect
            return object()

        with patch.object(self_update, "_wait_for_exit"), patch.object(self_update.subprocess, "Popen", side_effect=relaunch):
            try:
                self_update.apply_staged_update(staged, install, pid=81, platform="windows-x64", result_file=result)
            except self_update.UpdateError:
                pass
        return result, seen

    def test_success_is_recorded_before_the_new_version_starts(self):
        with tempfile.TemporaryDirectory() as temp:
            result, seen = self._swap(Path(temp))
            self.assertEqual(seen, [{"ok": True, "error": ""}])
            self.assertEqual(self_update.take_result(result), {"ok": True, "error": ""})
            self.assertIsNone(self_update.take_result(result))

    def test_failure_is_recorded_before_the_old_version_returns(self):
        with tempfile.TemporaryDirectory() as temp:
            result, seen = self._swap(Path(temp), [OSError("blocked"), None])
            self.assertFalse(seen[-1]["ok"])
            self.assertIn("blocked", seen[-1]["error"])
            self.assertEqual((Path(temp) / "CouchDoom" / "CouchDoom.exe").read_text(), "old")

    def test_older_six_argument_helper_call_still_applies(self):
        with patch.object(self_update, "apply_staged_update", return_value=0) as apply:
            self.assertEqual(main(["--apply-update", "a", "b", "1", "windows-x64", "c"]), 0)
        self.assertIsNone(apply.call_args.kwargs["result_file"])
        with patch.object(self_update, "apply_staged_update", return_value=0) as apply:
            self.assertEqual(main(["--apply-update", "a", "b", "1", "windows-x64", "c", "r.json"]), 0)
        self.assertEqual(apply.call_args.kwargs["result_file"], Path("r.json"))


if __name__ == "__main__":
    unittest.main()
