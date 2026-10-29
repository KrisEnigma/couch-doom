# Cross-platform Self-update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit in-app download, install, and restart flow for packaged Windows, macOS, and Linux builds.

**Architecture:** Keep release discovery in `update.py`, with a typed descriptor for the matching archive and checksum. Download and validation run off the UI thread into a per-user staging area; a staged app entry point performs the swap only after the current process exits, preserves state, and relaunches. Extend the existing GitHub release workflow to publish checksum sidecars.

**Tech Stack:** Python 3.11+, PyInstaller onedir bundles, `urllib.request`, `zipfile`, `tarfile`, subprocess/process IDs, GitHub Releases API and GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-29-self-update.md`

## Global Constraints

- Support only Windows x64, macOS arm64/x64, and Linux x64/arm64 packaged builds.
- Never require administrator or root privileges.
- Never replace user data; preserve portable `state/` and per-user settings.
- Keep manual release-page access and existing remind/skip/opt-out behavior.
- Reject checksum mismatches and unsafe archive paths before installation.
- Do not automatically install without an explicit user choice.
- Do not run a release workflow or publish a release as part of implementation.

---

## File Structure

- Modify `src/couch_doom/update.py`: define supported update targets, parse release metadata, and select exact matching assets/checksums.
- Create `src/couch_doom/self_update.py`: download, digest validation, safe extraction, staging cleanup, and installation orchestration.
- Create `tests/make_update_test_manifest.py`: produce a local fake latest-release manifest and checksummed archive so packaged self-update can be exercised without publishing a release.
- Modify `src/couch_doom/__main__.py`: route a private updater mode before normal UI startup so a staged executable can apply a prepared update after the old process exits.
- Modify `src/couch_doom/ui.py`: show install/download progress and errors, dispatch background work, and preserve existing update actions.
- Modify `src/couch_doom/state.py` only if needed to keep the existing state layout out of replacement and persist completion safely.
- Modify `packaging/CouchDoom.spec`: ensure the updater code is bundled and entry-point behavior works in the PyInstaller app.
- Modify `.github/workflows/release.yml`: create and publish a SHA-256 sidecar for each archive.
- Modify `tests/smoke.py` or create focused `tests/test_update.py` and `tests/test_self_update.py`: deterministic unit coverage with mocked HTTP and filesystem fixtures.
- Modify `README.md` and `packaging/release-header.md`: document supported in-app updating and the manual fallback.

## Task 1: Define target metadata and match release assets

**Files:**
- Modify: `src/couch_doom/update.py`
- Test: `tests/test_update.py` (create if focused tests are split from smoke tests)

**Interfaces:**
- Add immutable `ReleaseAsset` with `name: str`, `url: str`, `sha256_url: str`.
- Add `asset_for_platform(os_name: str, machine: str) -> str | None` mapping runtime platform values to one of the five exact target suffixes.
- Extend `check(current: str, skipped: str | None = None, *, platform: str | None = None) -> dict | None`; retain existing fields and add `asset: ReleaseAsset | None` when platform is supported and matching release assets/checksum sidecar exist.
- Continue returning update notice data for unsupported/source installs, with `asset=None`, so the manual release link remains available.

- [ ] Write tests for each OS/architecture mapping, unsupported targets, selecting exact version-and-target assets, absent checksums, malformed URLs, and preserving `is_newer`, skipped version, and disabled behavior.
- [ ] Run `python -m pytest tests/test_update.py -q` and confirm the new cases fail before implementation.
- [ ] Parse GitHub release `assets` by exact expected archive name and exact `<archive>.sha256` sidecar name. Accept only `https://github.com/` or `https://api.github.com/` URLs and the current newer tag version.
- [ ] Normalize OS and machine input inside the module so it is passed explicitly in tests; do not let test results depend on the host machine.
- [ ] Run the focused tests and `python -m pyflakes src tests`.

## Task 2: Implement streamed download, digest validation, and safe staging

**Files:**
- Create: `src/couch_doom/self_update.py`
- Test: `tests/test_self_update.py`

**Interfaces:**
- `download_and_stage(asset: ReleaseAsset, version: str, *, staging_root: Path, progress: Callable[[int, int | None], None] | None = None, cancel: threading.Event | None = None) -> StagedUpdate`
- `StagedUpdate` contains `version`, `root: Path`, `app_path: Path`, and `archive_path: Path`.
- `UpdateError` is the user-displayable base exception; expected failures include network, cancellation, digest, extraction, and disk failures.

- [ ] Add tests using mocked response streams for chunk progress, cancellation, short reads, network exceptions, valid and invalid SHA-256 sidecars, and temporary-file cleanup.
- [ ] Add ZIP and tar fixtures with normal files, `../` traversal, absolute paths, and links escaping the extraction root; require all unsafe members to be rejected before writing outside staging.
- [ ] Run focused tests and confirm these tests fail before implementation.
- [ ] Stream both archive and checksum downloads to unique `.part` files; calculate SHA-256 as archive bytes arrive; compare case-insensitively to the strict sidecar digest; atomically rename completed files.
- [ ] Extract only after digest success. Resolve every destination under the staging root, reject absolute/traversal members and escaping symlinks/hardlinks, and retain executable mode bits for tar members.
- [ ] Confirm extracted root contains the expected `CouchDoom.exe`, `CouchDoom.app`, or `CouchDoom` payload for its platform before returning `StagedUpdate`.
- [ ] Run focused tests and `python -m pyflakes src tests`.

## Task 3: Add post-exit apply mode and preserve app data

**Files:**
- Modify: `src/couch_doom/__main__.py`
- Modify: `src/couch_doom/state.py` only if path helpers need to be exposed or adjusted
- Modify: `packaging/CouchDoom.spec`
- Modify: `src/couch_doom/self_update.py`
- Test: `tests/test_self_update.py`

**Interfaces:**
- `apply_staged_update(staged_app: Path, install_path: Path, *, pid: int, platform: str, relaunch: bool = True) -> int`
- Private CLI form: `CouchDoom --apply-update <staged-app> <install-path> <pid> <platform>`; malformed arguments return a nonzero result without touching files.
- `installation_path(executable: Path, platform: str) -> Path | None` returns the app directory or `.app` bundle root for packaged installs and `None` for source execution.

- [ ] Write platform-independent orchestration tests with mocked process-wait, rename, copy, launch, and cleanup operations. Assert ordering: wait for PID exit, stage backup/swap, preserve `state/`, relaunch, then remove backup.
- [ ] Add failure-path tests for non-writable destination, failed rename, failed relaunch, malformed CLI arguments, and source installs; assert the current install and user data are not deleted.
- [ ] Run focused tests and confirm failure before implementation.
- [ ] Implement directory-based Windows/Linux replacement using same-volume staging where possible, moving existing app files to a temporary backup before promotion; keep portable `state/` outside the payload and copy it forward only when necessary.
- [ ] Implement macOS `.app` bundle root discovery from the executable path, replace the bundle after process exit, and relaunch the bundle executable with `open` or a direct launch strategy validated on macOS.
- [ ] Make the apply mode start before pygame/UI initialization; on Windows, launch the staged executable as the helper so the old executable can exit before replacement.
- [ ] Keep recovery data until relaunch succeeds; on any apply failure, restore the backup and write a concise diagnostic for the foreground UI to surface.
- [ ] Run focused tests and `python -m pyflakes src tests`.

## Task 4: Integrate user initiated update flow in UI

**Files:**
- Modify: `src/couch_doom/ui.py`
- Modify: `src/couch_doom/self_update.py`
- Test: `tests/smoke.py` and/or `tests/test_self_update.py`

**Interfaces:**
- Extend update notice choices to include `update` only when `info["asset"]` is present.
- Add UI state for a background future, progress, cancellation event, and outcome message; follow the existing single-worker update-check pattern.
- Worker returns a staged update or an `UpdateError`; UI handles completion on the main thread.

- [ ] Add UI-level tests for supported/unsupported choices, starting/cancelling download, progress display state, failure fallback link, success helper launch, and later/skip behavior.
- [ ] Run focused tests and confirm failure before implementation.
- [ ] Add “Update and restart” as the first action for installable releases, retain “Open download page”, “Remind me later”, and “Skip this version”; keep safe default on “Remind me later”.
- [ ] Submit download/stage work to a worker thread; never block the frame loop on HTTP or extraction.
- [ ] Draw progress and allow cancel only before helper handoff. On failure, show the message and a button to open the existing release URL.
- [ ] On successful staging, start the staged app in apply mode with current PID and install path, then close the old UI. On helper-launch failure, keep the old app open and offer the release link.
- [ ] On next startup, detect successful version change through the normal current version and avoid repeating the now-obsolete notice.
- [ ] Run focused tests, `python -m pyflakes src tests`, and `python tests/smoke.py`.
- [ ] Verify `COUCHDOOM_UPDATE_TEST_MANIFEST` loads a local manifest, enables only local file asset URLs, and is removed from the relaunched installed app environment.

## Task 5: Publish checksums and verify release asset contract

**Files:**
- Modify: `.github/workflows/release.yml`
- Test: `tests/test_update.py` (asset naming/sidecar parsing)

- [ ] Add a package step after archive creation that writes `<archive>.sha256` with lowercase SHA-256 and the exact archive filename; upload both archive and sidecar as release assets.
- [ ] Add workflow validation that fails if any expected target archive or sidecar is missing or if sidecar filename does not match archive name.
- [ ] Exercise the checksum parser with the exact GNU `sha256sum` output generated in CI and malformed/mismatched filenames.
- [ ] Run local shell-equivalent checksum generation against a temporary fixture archive and verify the parser accepts the output.

## Task 6: Update user and release documentation

**Files:**
- Modify: `README.md`
- Modify: `packaging/release-header.md`
- Modify: `packaging/How to use.txt` if the quick-start steps mention manual-only updates

- [ ] Document that packaged builds can download and apply a release from the update notice, while source/AUR installs use their package/manual update path.
- [ ] Explain the explicit restart, manual release page fallback, and that the update never requests elevated privileges.
- [ ] Keep architecture-specific release links and current macOS unsigned warning accurate; do not imply signing/notarization has been added.
- [ ] Review help text against actual UI labels and release asset names.

## Task 7: Cross-platform verification

**Files:**
- Modify: `.github/workflows/ci.yml` only if new focused tests are not already included

- [ ] Run `python -m pyflakes src tests` and `python tests/smoke.py` locally.
- [ ] Run the deterministic focused update tests on Windows, macOS, and Linux CI matrix; tests must mock GitHub and must not perform real update downloads.
- [ ] Add a packaging smoke step for each runner that builds and checks the expected updater entry point and target identity; do not publish artifacts from this check.
- [ ] Perform manual release-candidate checks for Windows locked executable replacement, Intel and Apple Silicon `.app` replacement, and Linux x64/arm64 directory replacement in writable and read-only locations.
- [ ] Confirm failure cases leave the original app runnable and open the correct release URL.
- [ ] Confirm settings survive update for both portable and per-user installations.

## Self-review

- The spec's supported targets, manual fallback, user data preservation, no elevation, checksum, and existing preference requirements map to Tasks 1–6.
- Unsafe archive handling, network failure, cancellation, process replacement ordering, and platform checks map to Tasks 2–4 and 7.
- Signing/notarization and package-manager/source self-updating are explicitly excluded by the spec.
- Release checksum sidecar format and filename contract are shared between the spec, Tasks 1 and 5.
