# macOS DMG Installer Implementation Plan

> **For agentic workers:** Implementation was performed inline in this session.

**Goal:** Publish a drag-to-Applications DMG for each supported macOS architecture while preserving the ZIP updater assets.

**Architecture:** Extend the existing macOS release job to stage a conventional DMG layout and create a compressed UDZO image alongside the ZIP. Generate checksums for both archives and update the README and release header with DMG download instructions.

**Tech Stack:** GitHub Actions YAML, macOS `hdiutil`, Bash, Markdown.

**Spec:** User request to make a DMG installer after confirming a clean folder and only the `main` branch.

## Global Constraints

- Keep `macos-arm64` and `macos-x64` targets.
- Preserve ZIP assets because the updater expects `.zip`.
- Include `CouchDoom.app`, `How to use.txt`, and `LICENSE` in the DMG.
- State that the app remains unsigned and may need user approval on first launch.

---

### Task 1: Produce and publish DMG assets

**Files:** Modify `.github/workflows/release.yml`, `README.md`, and `packaging/release-header.md`.

- [x] Keep existing macOS ZIP packaging.
- [x] Create a separate DMG staging folder with the app, help, license, and Applications symlink.
- [x] Produce compressed DMG and SHA-256 checksum for each architecture in release CI.
- [x] Document DMG downloads, drag-to-Applications install, unsigned first-launch behavior, and ZIP fallback.
- [x] Review the diff; `git diff --check` and YAML/Bash syntax validation passed.

**Validation limit:** The DMG itself requires macOS `hdiutil`, so it will be built when the release workflow runs on the macOS runners.
