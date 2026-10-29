# CouchDoom Self-Selection Easter Egg

**Goal:** Make selecting CouchDoom itself in the manual browser show a small, playful response instead of a launcher error.

**Approach:** Compare the selected path with the running frozen executable; on macOS also recognize the containing `.app` bundle. Include the executable in the default browser filter. Intercept self-selection before launcher detection and show a short toast. Keep using sounds from a recognized Doom-family IWAD when one is present; if the available IWADs are Hexen/Strife or there is no IWAD, use a small bundled Freedoom menu sound set. For the egg, prefer `DSSECRET`, then `DSITMBK`, then the bundled Freedoom `DSITMBK`. Include Freedoom's copyright, license conditions and disclaimer with source and packaged builds. Do not add settings or a new overlay.

## Steps

1. Add a Doom-family IWAD classifier using known Doom-family file names; don’t treat a shared `DSPSTOP` lump alone as proof that a Hexen or Strife IWAD should provide the menu pack. Test Doom, Freedoom, Hexen, Strife and unknown filenames.
2. Add Freedoom source WAVs for the existing `move`, `confirm`, `open`, `close` and `error` menu cues, plus `DSITMBK` for the egg fallback. Preserve the full BSD-3-Clause copyright notice, conditions and disclaimer in a third-party notice; credit Freedoom without implying endorsement. Include the notice and sound assets in source packages, app bundles, Windows/Linux archives and the AUR package.
3. Change `Sfx` source selection: use existing sounds from a recognized Doom-family IWAD; otherwise load the bundled Freedoom menu set. For the egg, prefer the selected IWAD's `DSSECRET`, then its `DSITMBK`, then the bundled `DSITMBK`. Keep the bundled menu set usable when no IWAD/audio source exists. Test source priority, sound-lump fallback and silent audio-device behavior.
4. Add a small path-matching helper and tests for the running executable on Windows/Linux and the containing `.app` bundle on macOS. Match Linux's extensionless `CouchDoom` binary; keep source runs from treating Python itself as CouchDoom.
5. Include the packaged executable in the default manual-browser filter on each platform. In `_on_drop`, detect self-selection before `Launchers.add` and show: **“Doomception! I’m already running.”** Play the secret-style sound; leave launcher state unchanged.
6. Extend the headless smoke check to select the Windows executable, Linux executable and macOS bundle paths and verify the easter-egg response replaces the normal launcher error. Run pytest, smoke, and pyflakes.

## Acceptance

- Selecting `CouchDoom.exe`, the extensionless Linux `CouchDoom` executable or `CouchDoom.app` shows the easter egg, not the unsupported-launcher message.
- With no Doom-family IWAD, including Hexen/Strife-only setups, the bundled Freedoom menu sounds play when audio is available.
- With a Doom-family IWAD, that IWAD's sounds remain preferred.
- The Freedoom third-party notice ships with source and packaged builds.
- Other selected files retain their current behavior.
- No new graphics or persistent state are added.
