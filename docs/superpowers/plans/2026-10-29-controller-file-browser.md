# Controller-Friendly File Browser Implementation Plan

> **For agentic workers:** Implement inline and complete each task in order. Steps use checkbox (`- [x]`) syntax for completed work.

**Goal:** Replace the external native file picker for “Find it myself…” with an in-app browser that can be used with a controller or keyboard on Windows, macOS and Linux.

**Architecture:** Add a small filesystem browser module that lists one directory at a time, sorts directories before files, and exposes only navigation and filtering data. Add a browser overlay mode to the existing Pygame UI; it returns the selected path to the existing `Launchers.add` / `_on_drop` validation flow. The browser starts in the home directory, supports parent navigation and platform filesystem roots, and shows likely Doom launcher/settings files by default with a controller-accessible all-files toggle.

**Tech Stack:** Python 3.11+, `pathlib`, `os.scandir`, Pygame CE, existing `Action` input abstraction and UI drawing helpers.

**Spec:** User-approved evaluation in this conversation: “replace the native dialog for this one ‘Find it myself…’ flow with an in-app, controller-first browser”; preserve drag-and-drop and existing launcher validation.

## Global Constraints

- Support Windows, macOS and Linux without adding dependencies.
- Keep manual browsing read-only; selecting a path must continue through existing launcher recognition and validation.
- Keep the browser usable with D-pad/left stick, A/Start, B and keyboard equivalents.
- Do not change automatic launcher discovery, saved launcher selection, or drag-and-drop behavior.
- Run the focused tests and cross-platform smoke checks before considering the browser complete.

---

## File Structure

- Create `src/couch_doom/filebrowser.py`: directory entry model, platform root discovery, safe directory enumeration, sorting and launcher-file filtering.
- Modify `src/couch_doom/ui.py`: browser state, input handling, overlay rendering, footer hints, and handoff of selected paths to `_on_drop`.
- Modify `src/couch_doom/filedialog.py`: remove it once the in-app flow is its only caller; no platform dialog code should remain reachable.
- Create `tests/test_filebrowser.py`: temporary-directory tests for ordering, visibility/filter behavior, inaccessible paths, and parent/root navigation.
- Modify `README.md`: describe controller browsing and remove native-dialog-specific Linux/macOS caveats.

## Task 1: Build a testable filesystem browser model

**Files:**
- Create: `src/couch_doom/filebrowser.py`
- Create: `tests/test_filebrowser.py`

**Interfaces:**
- `Entry(path: Path, is_dir: bool)` is an immutable directory row; expose a display name that marks directories without requiring platform-specific separators.
- `roots(home: Path | None = None) -> list[Path]` returns the home directory first and the navigable filesystem roots for the current OS, deduplicated. Windows roots come from mounted logical drives; POSIX includes `/`.
- `list_entries(directory: Path, *, show_all: bool = False, names: Collection[str] = ..., suffixes: Collection[str] = ...) -> list[Entry]` returns directories and matching files, with directories first and case-insensitive alphabetical ordering. With `show_all=True`, include all files. Skip entries whose metadata cannot be read and return an empty list when the directory cannot be opened.
- Symlinked directories are not traversed, avoiding cycles; ordinary files and directories remain selectable/openable. Do not recursively scan.

- [x] Write tests using `tmp_path` for directory-first alphabetical ordering, case-insensitive launcher/settings matching, all-files inclusion, no recursion, and unreadable/missing directories.
- [x] Run `python -m pytest tests/test_filebrowser.py -q` and confirm the tests fail because the module is absent.
- [x] Implement `Entry`, `roots`, and `list_entries` with `os.scandir` and `pathlib`; isolate platform root discovery so tests can exercise Windows drive enumeration without depending on the host OS.
- [x] Run the focused tests and `python -m pyflakes src tests`.

## Task 2: Add browser overlay state and navigation

**Files:**
- Modify: `src/couch_doom/ui.py`
- Test: `tests/test_filebrowser.py` or focused UI tests in `tests/test_filebrowser_ui.py`

**Interfaces:**
- Add UI mode `"browse"` and state for current directory, entries, selected row, visible scroll window, all-files toggle, and root selection.
- `_open_browser()` starts in `Path.home()`, loads entries, sets `mode = "browse"`, and plays the existing open sound.
- `Browser.refresh()` reloads the current directory and clamps selection; the UI keeps its visible scroll window clamped to the selected row.
- `_browser_action(action: Action)` handles UP/DOWN, PAGE_UP/PAGE_DOWN, CONFIRM/MENU, BACK, and the X/Tab all-files toggle. Choosing a directory enters it; choosing a file closes the overlay and calls `_on_drop(path)`; BACK goes to the parent when possible, then closes from a root.
- Left/right or shoulder navigation switches among `roots()` entries while preserving the common selected root. Keep rules consistent with the existing abstract actions and displayed input glyphs.

- [x] Write focused tests for selection clamping after a refresh, entering a directory, selecting a file, moving to parent, backing out from a root, and toggling all files.
- [x] Run focused tests and confirm new behavior fails before adding the UI state and handlers.
- [x] Implement browser open/refresh/action transitions using the model from Task 1. Keep selection acceptance routed through the existing `_on_drop` function so launchers/settings retain existing detection behavior.
- [x] Run the focused tests and `python -m pyflakes src tests`.

## Task 3: Render the browser and connect the launcher picker

**Files:**
- Modify: `src/couch_doom/ui.py`
- Test: UI smoke coverage if existing headless rendering helpers can exercise overlay modes without a real display

**Interfaces:**
- Replace the `None` picker row action in `_picker_pick` with `_open_browser()`; remove `filedialog.available()` gating so “Find it myself…” always appears.
- Draw a full-screen dimmed overlay with current path, parent/root navigation affordance, scrollable directory/file rows, selected-row highlight, empty/error state, and current filter mode.
- Show controller prompts for Open, Back, Show all/Launcher files, roots and page navigation. Keyboard prompts use Enter, Esc, Tab, arrows and Page Up/Down; support mouse row selection through existing `Hit` objects.
- Dispatch `mode == "browse"` in `_on_action` and `draw`; prevent browser actions from reaching list or launcher-picker handling.
- Use bounded row rendering and the existing `PAGE_UP` / `PAGE_DOWN` actions so large directories remain navigable without constructing oversized surfaces.

- [x] Add or extend a headless smoke check that opens the browser overlay, draws an empty and populated directory state, and confirms the selected row can be activated.
- [x] Run the new smoke check and observe the expected failure before wiring the overlay.
- [x] Implement rendering, footer hints and event routing; retain the current launcher picker and list behavior.
- [x] Run `python tests/smoke.py` and `python -m pyflakes src tests`.

## Task 4: Remove the native picker path and update user guidance

**Files:**
- Modify: `src/couch_doom/ui.py`
- Delete: `src/couch_doom/filedialog.py`
- Modify: `README.md`
- Modify: `packaging/aur/PKGBUILD` if its optional dialog dependencies become unused

- [x] Search for all `filedialog`, `zenity`, `kdialog`, and native open-dialog references; identify only user-facing documentation and packaging references related to this flow.
- [x] Remove the `_browse` native-process branch and its imports, event pumping, window-level workarounds, and dialog-specific input cooldown. Keep drop handling unchanged.
- [x] Remove obsolete `zenity` / `kdialog` optional dependencies and platform-specific dialog instructions; document D-pad/stick navigation and A/B controls for manual browsing.
- [x] Run `python -m pytest -q`, `python tests/smoke.py`, and `python -m pyflakes src tests`; inspect the README and package metadata for stale native-picker references.

## Acceptance Criteria

- The “Find it myself…” option is always available and stays inside CouchDoom on all supported operating systems.
- A controller can navigate folders, choose a launcher/settings file, change the visible file filter, page through long folders, and cancel without a mouse or keyboard.
- Keyboard and mouse users can perform the same navigation.
- Missing or unreadable folders show an empty/error message and remain safely navigable.
- A selected file is passed through the existing `_on_drop` validation path; accepted launcher behavior and failure messaging remain unchanged.
- No external file-dialog process or runtime dependency remains for this flow.
