# Menu, Navigation, and Color Plan

**Status:** Menu and navigation changes are implemented. Follow-up performance fixes are complete and tested; this plan and handoff are being refreshed for the next thread. Recent-played group and color review remain open. The earlier menu/browser baseline is `7eadf9f` (`feat(ui): add menu and improve file browser navigation`).

## Goal

Keep CouchDoom's direct game-list flow while adding the creator-requested menu and improving keyboard/controller file navigation. Consider more nuanced automatic art colors and a small set of manual color controls without duplicating existing metadata behavior or expanding the UI unnecessarily.

## Completed

- Added an overlay menu opened with Escape or controller Start. Its first selected option returns to the list. It includes refresh, title music, menu sounds, launcher selection when available, Help, and Quit.
- Refresh leaves the menu open and shows a temporary inline confirmation. Music and menu sound settings are separate and toggle with either Left or Right. Removed the no-longer-needed F2 and launcher shortcuts.
- Menu Quit exits without another confirmation and uses Doom's player-death sound (`DSPLDETH`) from the selected IWAD, trying a bundled fallback when one is available.
- Kept F1/Back/View as Help shortcuts. B does nothing on the main selector and backs out of open panels. Help & Feedback remains reachable from Help rather than as a separate menu item.
- Added Home/End list navigation and updated the main-list footer hint order.
- Improved the launcher browser: distinct drive/home chooser and drive contents, parent/location rows, non-wrapping Page Up/Down and Left/Right page navigation, Home/End, non-wrapping wheel scrolling, a styled draggable scrollbar, and click-only row selection. Escape closes the browser.
- Removed redundant “Select to load” text in the launcher picker. Updated README guidance.
- Creator has manually reviewed and steered the menu/browser iterations. The original menu/browser baseline is commit `7eadf9f`.
- Reduced selection hitches in the 105-preset local launcher: art, theme, and logo rendering stay off the UI thread; logos are prepared independently and appear without first flashing the text fallback; long detail text layout is cached and bounded; music preparation starts only after a 0.65-second selection dwell and its file/cache identity work and stream pruning run off-thread at lower priority.
- Added regression coverage for dwell timing, asynchronous music identity/pruning, art/logo job ordering and title fallback, long-text layout, theme/cache behavior, and background worker priority.
- Replayed the complete local list down and back up at both 0.5-second and 0.2-second press intervals (231 presses each). The dummy-display runs recorded no frame intervals over 50 ms. These runs exercise the application loop but do not replace a hardware/fullscreen check.
- Reviewed and refreshed tests that had become stale against current behavior: incomplete app fixtures, current menu/controller bindings, browser parent rows and startup-root semantics, and the optional IWAD quit sound (there is no bundled `DSPLDETH` asset). Full suite: **125 passed, 2 skipped**.

## Remaining Work

### 1. Verify the latest browser behavior on Windows

- Manually check the browser on Windows, especially drive-root versus “Drives & Home” navigation, parent-folder behavior, and scrollbar dragging.
- Check Page Up/Down and Left/Right advance exactly one visible page, stop at both ends, and keep the selection visible. Check Home/End and mouse wheel do not wrap.
- Automated browser tests now reflect the separate root chooser and parent-directory row. Manual checks for drive-root navigation, page-sized movement, scrollbar dragging, and non-wrapping endpoints remain useful.

### 2. Revisit the color request against the actual code

- `src/couch_doom/theme.py` groups vivid pixels into 72 five-degree hue bins, then derives theme colors from the weighted mean hue inside the dominant bin. The warm house fallback now covers hues within 8 degrees of its red center; low-color art still uses the fallback. Four focused tests pass. The saved launcher has 105 presets with title art and no load failures: the 8-degree range yields 53 house fallbacks and 41 distinct visual themes, compared with 67 and 30 at the original 22-degree range. Hands-on UI review is still useful.
- Fixed raw asset cache serialization for ENDOOM bytes; 37 of the creator's 105 presets include ENDOOM. The local scan now finds cache entries for all presets. Bounded rendered theme caches to 48 entries, enough for the current 41 visual themes. Reworked background generation to expand a one-pixel gradient strip; sampled output pixels match the prior renderer. App-path profiling found three completed art jobs could be processed in one UI frame (~30 ms), so `_update_art` now prioritizes the selected preset and processes at most one surface per frame. In the dummy display run this split into ~10–12 ms per frame; manual hardware review remains necessary.
- Found the persistent slowdown in the Hell Revealed 2 detail panel: its 403-character byline made `_fit` measure and trim one character at a time, costing about 145 ms on every draw. `_fit` now binary-searches the fitting prefix. The detail panel measures about 5.5 ms, and warmed 2048x1152 dummy-display frames measure 8.9 ms for Hell Revealed 2 versus 8.0 ms for Doom II. Manual hardware review remains necessary.
- The creator clarified that the request is for more buckets in **automatic color detection**, not a larger manual palette. Keep any existing color controls limited; inspect the current metadata/color behavior first so we do not duplicate functionality or misread the code.
- The code inspection found no manual color setting or metadata color field. Keep changes easy to roll back if the finer distinctions add noise rather than value.
- Do not add arbitrary RGB controls or an expansive manual palette. Preserve existing color controls unless code review shows they are redundant; any additions should stay curated and small.

### 3. Add the optional last-played group

- This was part of the creator's original menu direction but is not in the current menu. `State.history` already records recent presets (up to 10).
- If proceeding, add a small on/off setting and synthetic group using that existing history, with stale names filtered against the active launcher data. Reuse current category behavior and avoid play counts or a second history store.
- Implement as a separate, locally reviewable change so the creator can try it and roll it back if it clutters the list.

## Working Style / Scope

- The creator is open to experimentation and local rollback. Be selective with public-user feature requests, but take creator-directed ideas seriously and finish the requested change before asking for manual review.
- Work one feature at a time and return the app for hands-on testing between features.
- Read the current implementation before proposing or changing behavior; metadata is already possible in relevant parts of the app, so verify exact capabilities instead of assuming they are absent.
- Do not add unrelated polish or broad settings frameworks. Prefer existing navigation, persistence, and drawing helpers.
- No tests were run for the changes in commit `7eadf9f`; `git diff --check` passed before commit. Do not claim broader verification.
