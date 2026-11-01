# Main Menu, Play History, Navigation, and Color Options Implementation Plan

> **For agentic workers:** Implement this plan inline in small reviewable steps. The plan follows the creator's direction in GitHub issues #5, #6, and #10 and the follow-up discussion in this session.

**Goal:** Explore a compact, controller-friendly menu for common actions, finer automatic color detection, and a small set of optional per-preset color overrides.

**Architecture:** Extend the existing UI mode/overlay flow rather than introducing a separate settings framework. Reuse the saved local state file for the recent-group toggle and limited per-preset color overrides; keep launcher configuration read-only. Keep Home/End as direct list navigation actions. Increase hue resolution in the existing title-art theme algorithm while retaining automatic color as the default and the current contrast ladder.

**Tech Stack:** Python 3.11+, pygame, existing `State` JSON persistence, existing `UI` action/mode/drawing architecture, pytest project tests, local interactive build.

**Spec:** Creator direction and GitHub issues [#5](https://github.com/KrisEnigma/couch-doom/issues/5), [#6](https://github.com/KrisEnigma/couch-doom/issues/6), [#10](https://github.com/KrisEnigma/couch-doom/issues/10); issue [#7](https://github.com/KrisEnigma/couch-doom/issues/7) motivates an optional recent-played group.

## Global Constraints

- Keep launcher settings read-only; CouchDoom preferences belong in its existing `last_played.json` state file.
- Keep colors automatic and art-derived by default. Offer only a small curated set of manual per-preset overrides; do not expose arbitrary RGB input or every automatic hue bucket as a manual option.
- Keep menu actions usable by keyboard, controller, and mouse, following existing overlay patterns.
- Do not add dependencies or change launch behavior.
- Treat the UI as an experiment: locally inspect it and narrow or roll back menu/palette scope if it makes the list flow worse.
- Add focused regression tests for state persistence, recent-group construction, palette selection, and list navigation; run relevant tests and perform a local keyboard/controller interaction review.

---

## Code Map

- `src/couch_doom/theme.py`: maps title-art hue to the current theme. There are currently 36 hue buckets; label/accent/background saturation and lightness are fixed, and warm red/orange art uses `HOUSE`.
- `src/couch_doom/ui.py`: owns the `mode` overlay dispatch, keyboard/controller actions, section list construction, theme transitions, footer hints, and overlay drawing. `_reload()` already refreshes source data and `_apply()` resets dependent caches and list state.
- `src/couch_doom/gamepad.py`: translates physical keys to semantic `Action`s. F5 currently means `ISSUES`; F1 and controller Back/View mean `HELP`; Escape and controller B mean `BACK`; controller Start means `MUSIC`; PgUp/PgDn are list paging.
- `src/couch_doom/state.py`: persists `last_played`, unique recent `history` (up to 10), favorites, music, and preferences in `last_played.json`.
- `README.md`: documents current controls and art-driven experience.
- `tests/test_ui_features.py`, `tests/test_issue_fixes.py`, `tests/test_config.py`: existing test locations to inspect for relevant fixtures and behavior.

## Proposed interaction decisions

- In the main selector, Escape or controller Start opens a compact menu. Controller B does nothing on the main selector for now; it does not open the menu or quit. Preserve B/Escape back behavior inside existing overlays and search. The menu has Back to games, Refresh list, Recent games (on/off), Title music (on/off), Colors for this preset, Help & Feedback, and Quit. Back to games is the default selected row and simply closes the menu. Quit from the deliberately opened menu exits immediately without a second confirmation.
- Help remains directly available through F1 and controller Back/View, and is also listed in the menu. Do not repurpose F1 or controller Back/View as menu triggers. Menu Back/Escape returns to the list.
- Refresh calls existing `_reload()`. It is enabled only when reload is available; preserve the current blocked-screen reload behavior.
- Recent games is an optional synthetic group built from `State.history`, ordered newest first, limited by existing history length, and filtered to names present in current launcher data. It is off by default. Reuse existing category-row and collapse behavior; don't introduce a second history store or frequency counts.
- Automatic color remains the default. Increase the current 36 hue buckets to finer resolution (initial proposal: 72 buckets, five degrees each), preserving the existing saturation/lightness contrast ladder and warm red/orange `HOUSE` treatment unless local inspection shows that boundary also needs adjustment. Also offer a small curated override set for the selected preset (initial proposal: Automatic, Warm, Gold, Green, Blue, Violet). Persist overrides per preset, scoped by launcher source, settings path, and preset name. Automatic removes that preset's override and returns to art-derived color.
- Home and End select the first/last selectable row in the current visible list, including headers, matching existing row navigation. They keep selection visible. In search mode, retain text-editing semantics; in other overlays, retain existing behavior unless a screen already uses these keys for navigation.

## Task 1: Add Home/End actions

**Files:**
- Modify: `src/couch_doom/gamepad.py`
- Modify: `src/couch_doom/ui.py`
- Modify: `tests/test_ui_features.py`

- [ ] Add semantic `HOME` and `END` actions and map `pygame.K_HOME` / `pygame.K_END`.
- [ ] Route the actions in list mode to a row-selection helper targeting the first/last visible row; preserve existing row selection and scroll invariants.
- [ ] Do not add footer hints; these are conventional keyboard affordances.
- [ ] Preserve search editing and overlay scrolling semantics.
- [ ] Add focused tests for first/last row selection, including collapsed headers and an active filter.

## Task 2: Add recent-group preference and row source

**Files:**
- Modify: `src/couch_doom/state.py`
- Modify: `src/couch_doom/ui.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_ui_features.py`

- [ ] Add backward-compatible boolean state preference `recent_group`, default `False`; load missing/invalid values safely and save alongside existing preferences.
- [ ] When enabled, build a `Recently Played` category from `history`, retaining only current preset names and deduplicating names. Place it after Favorites and before normal sections.
- [ ] Use existing category rows, detail preview, collapse, selection, and search logic. Search matching includes recent preset names; selecting a duplicate preset row still refers to the same preset identity.
- [ ] Keep favorites and recent history distinct; do not add play counts or change history policy.
- [ ] Add focused tests for old state files, persistence, filtering stale history from another launcher, and recent group ordering.

## Task 3: Add menu overlay and consolidate selected actions

**Files:**
- Modify: `src/couch_doom/gamepad.py`
- Modify: `src/couch_doom/ui.py`
- Modify: `README.md`
- Modify: `tests/test_ui_features.py`

- [ ] Add a distinct menu action for Escape and controller Start. In the main list it opens the menu; controller B (`BACK`) has no main-list action. Preserve Escape/B behavior inside search, info, launcher picker, file browser, and update overlay. Keep `HELP` (F1 and controller Back/View) opening Help directly.
- [ ] Add menu UI mode with selected-row state and an overlay matching existing launcher/update overlay interaction and visuals.
- [ ] Add Back to games, Refresh list, Recent games toggle, Title music toggle, Colors for this preset, Help & Feedback, and Quit entries. Select Back to games by default. Omit or disable Refresh when no reload callback exists; reflect toggle state in its label/check mark.
- [ ] Implement Back to games as plain overlay close; Refresh through `_reload()`; Recent games by saving preference and rebuilding rows while preserving current preset when possible; Music through `_toggle_music()`; Help by opening existing Help mode; Feedback by opening the existing issue URL; Quit by setting `running = False` directly without a second confirmation.
- [ ] Menu confirmation executes the selected action; up/down moves selection; mouse clicks use the existing `Hit` model. Start/Escape closes the menu; B may close it as an overlay back action. Clicking the shaded backdrop does not trigger an action.
- [ ] Keep F2 as direct keyboard music toggle if useful; controller Start becomes menu, so music remains accessible as a menu action and via F2. Remove stale controller Start/music hint.
- [ ] Update footer hints and README controls to describe Escape/Start opening the menu, F1/Back/View opening Help directly, B doing nothing on the main selector, and Home/End navigation.
- [ ] Add focused input/action tests for menu open/close, default selection, each action callback, direct Quit, and unchanged B behavior on the main list.

## Task 4: Increase automatic theme hue resolution

**Files:**
- Modify: `src/couch_doom/theme.py`
- Modify: `src/couch_doom/state.py`
- Modify: `src/couch_doom/ui.py`
- Modify: `tests/test_theme.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_ui_features.py`

- [ ] Increase `HUE_STEPS` from 36 to 72, making hue buckets five degrees wide while retaining the automatic `from_art()` flow.
- [ ] Keep the existing saturation/lightness ladder, `HOUSE` fallback, and theme fade/cache architecture unless visual inspection reveals a specific issue.
- [ ] Add focused tests that confirm art samples falling in separate five-degree buckets yield distinct theme keys, achromatic art still selects `HOUSE`, and hues in the warm house range retain current behavior.
- [ ] Inspect the 72-bucket result across representative title art to ensure finer hue differences feel intentional and not noisy; adjust bucket count only if visual review supports it.
- [ ] Define a compact manual palette registry (Automatic, Warm, Gold, Green, Blue, Violet) using stable keys and the existing contrast ladder. Keep this list intentionally smaller than the automatic hue resolution; no custom RGB picker.
- [ ] Persist selected-preset color overrides keyed by launcher source, settings path, and preset name. Invalid keys and malformed state entries fall back to Automatic without affecting startup.
- [ ] Add a Colors submenu for the currently selected preset. Selecting a manual palette updates the active theme immediately and persists it; selecting Automatic removes that preset's override. Other presets continue to use their own override or automatic art-derived hue.
- [ ] Add focused tests for override persistence, same-name preset isolation, and restoring Automatic; keep the override set small enough to review directly without paging.

## Task 5: Local product review and scope gate

**Files:**
- Modify only if findings warrant: `src/couch_doom/ui.py`, `src/couch_doom/theme.py`, `README.md`

- [ ] Launch locally at couch distance and use keyboard, controller, and mouse. Judge whether Escape/Start menu entry is discoverable, Back to games is an obvious first option, actions are quick to reach, and the current list flow still feels direct.
- [ ] Check that B is inert on the main selector while still backing out of overlays, and that quitting from the menu exits immediately as requested.
- [ ] Inspect automatic hues on bright, dark, monochrome, and warm/red art; verify text, selection, and toast contrast and confirm achromatic art still uses the house theme. Try each manual override on several presets and confirm Automatic restores the art tint.
- [ ] If the menu feels busy, remove duplicate entry points or the optional Recent games item first. If 72 hue buckets produce distinctions too subtle to matter, adjust the resolution based on hands-on use. Keep manual choices curated and few rather than exposing all hue buckets.
- [ ] Keep changes easy to revert as a cohesive feature set; no launcher config migration is needed.

## Self-review

- Issue #5 is addressed with finer automatic hue detection plus a small, reversible per-preset override set; automatic art-derived color remains the default.
- Issue #6 is covered by unhinted Home/End list navigation.
- Issue #7 is addressed narrowly as an opt-in recent group using existing history; most-played counts are excluded.
- Issue #10 uses the existing reload path.
- Menu triggers follow creator direction: Escape and Start open it; F1/Back/View remain Help shortcuts; B has no main-selector action. The first menu selection returns to the game list, and intentional Quit is immediate.
- No implementation changes are part of this plan-editing turn.
