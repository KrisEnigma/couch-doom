# Self-update design

## Goal

Let users of packaged CouchDoom builds download and install a newer GitHub release from the existing update notice, then restart into the new version.

## Scope

- Support the five release targets already built by `.github/workflows/release.yml`: Windows x64, macOS arm64, macOS x64, Linux x64, and Linux arm64.
- Update only the packaged PyInstaller app. Source installs and the Arch AUR package continue to use their own update mechanisms and retain the release-page link.
- Keep the existing manual release page choice as a fallback. Network, disk, archive, verification, and replacement failures must leave the currently installed app usable and report the release page URL.
- Preserve user data, including portable `state/` when it is stored beside the app. Never replace data directories as part of the app payload.
- Download and stage while the app runs; apply the replacement only after the old app exits; relaunch the installed app after success.
- Do not request administrator/root privileges.
- Use HTTPS GitHub release metadata and a SHA-256 digest published with the release assets to detect truncated or corrupted downloads. This is corruption detection, not protection against a compromised GitHub release account.
- Preserve current update-check opt-out, skipped-version behavior, and “remind me later” behavior.

## Architecture

The update check will return a structured release asset descriptor only when a matching asset exists for the current OS and architecture. The UI will show an “Update and restart” choice for supported packaged builds and continue to offer the release page. A background download writes to a temporary file, checks the digest, safely extracts into a staging directory, and starts a platform-aware apply helper. The helper waits for the current process to exit, swaps the staged app directory or bundle into place while preserving user data, and launches the updated app. Any failed step cleans up staging where possible and returns the user to the existing app with a manual-download option.

Release automation will emit checksums for each archive and publish them with the release. Platform install roots will be derived from the running executable or app bundle, not the current working directory. Unsupported/source installs do not expose the automatic install action.

## User experience

- A matching packaged build offers **Update and restart**, **Open download page**, **Remind me later**, and **Skip this version**.
- During download/application preparation, show progress and allow cancellation before replacement begins.
- On success, restart into the new version and do not show the same update again.
- On failure, explain the concise reason and offer the release page; do not mark the version as installed or skipped.
- Existing update-check preferences remain unchanged.

## Platform behavior

- **Windows:** Stage beside the installation directory when writable, otherwise use a per-user temp directory on the same volume where possible. Launch the staged app's updater entry point, wait for CouchDoom to exit, then replace the app files. If the installation directory is not writable, fail safely and open the release page; do not elevate.
- **macOS:** Identify the enclosing `.app` bundle, stage an equivalent bundle, quit the current process, replace the bundle, and reopen it. Preserve the current unsigned distribution behavior; code signing and notarization are a separate release decision and should be considered before shipping this feature.
- **Linux:** Identify the executable's app directory, stage and swap the app directory, preserve executable bits, and relaunch. Fail safely when the install directory is not writable.

## Release asset contract

Each archive filename maps to one target exactly:

- `CouchDoom-<version>-windows-x64.zip`
- `CouchDoom-<version>-macos-arm64.zip`
- `CouchDoom-<version>-macos-x64.zip`
- `CouchDoom-<version>-linux-x64.tar.gz`
- `CouchDoom-<version>-linux-arm64.tar.gz`

Each published archive has a same-name `.sha256` sidecar containing its lowercase SHA-256 digest and filename. The updater selects only a strict version-matched target asset; it rejects unknown OS/architecture combinations and malformed metadata.

For end-to-end local testing, setting `COUCHDOOM_UPDATE_TEST_MANIFEST` makes update discovery load the named JSON manifest instead of contacting GitHub. In this mode only, `file://` archive URLs are allowed. The installed app's relaunch removes this variable so the test source cannot affect normal startup.

## Acceptance criteria

1. A packaged app offers an install action only when a newer release contains a matching target asset and checksum.
2. Downloads are streamed to temporary storage, validated against SHA-256, and extracted with path traversal and link escape protections.
3. A failed, cancelled, corrupt, or unsupported update leaves the installed app and user data intact.
4. Windows, macOS, and Linux replacement happens only after the running app exits, requires no elevation, preserves user state, and relaunches the updated build.
5. The release workflow publishes checksums for every target archive.
6. Existing manual update, skip, later, and opt-out flows continue to work.
7. Automated tests cover metadata selection, checksums, safe extraction, cancellation/failure cleanup, data preservation, and platform apply orchestration without making real network requests.

## Out of scope

- Auto-updating Python/source installs, package managers, or the AUR package.
- Delta/patch downloads, background silent installs, automatic installation without user action, elevation, rollback across app launches, code signing/notarization, and cryptographic release signing.
