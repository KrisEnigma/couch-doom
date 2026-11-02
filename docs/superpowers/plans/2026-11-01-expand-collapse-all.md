# Expand / Collapse All Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand all / collapse all for preset groups. Don't take over face buttons or printable keys on the main list.

**Architecture:** Keep using `collapsed_sections` and `_rebuild_rows`. Two entry points that are free today: menu one-shots, and `Action.ALT` only on a category header (on a preset, ALT still opens Info).

**Tech Stack:** Python, pygame, existing `ui.App` list + menu.

**Spec:** Follow-up on https://github.com/KrisEnigma/couch-doom/issues/3 (per-group toggle already shipped in v1.1.0)

## Global Constraints

- Per-group Confirm / click / marker toggle stays as it is.
- Bulk fold refuses while a text filter is active (same toast as `_toggle_section`: "Clear search before folding groups").
- Favorites and Recently Played fold with everything else (`collapsed_sections`).
- Printable keys stay type-to-search. No `[` / `]` / `-` / `=` shortcuts.
- No new always-on pad button. X/ALT only means bulk fold on headers.
- Menu covers people who never land on a header.

## Shortcut map (list mode after this change)

| Input | On preset row | On category header | Notes |
|--|--|--|--|
| Enter / A (`CONFIRM`) | Play | Toggle **that** group | Existing |
| Tab / X (`ALT`) | Info sheet | **Expand all** or **Collapse all** (see rule below) | New contextual use |
| Escape / Start | Menu | Menu | Existing; menu also exposes Expand/Collapse all |
| Letters / symbols | Edit filter | Edit filter | Untouched |
| F1 / Back | Help | Help | Untouched |
| F3 / R3 | Favorite | (no-op / existing) | Untouched |
| LB/RB, Left/Right | Sections | Sections | Untouched |

**ALT bulk rule:** If any current header name is outside `collapsed_sections`, ALT collapses all of them. If everything is already collapsed, ALT expands (clear the set). Collapse path should set `collapsed_sections` to the current header names.

Implementation sketch:

```python
def _all_header_names(self) -> set[str]:
    # Names that would appear as headers with the current filter cleared for fold purposes.
    # Practical approach: collect header texts from a no-filter rebuild intent:
    names = set()
    if self.state.favorites:
        names.add(FAVORITES)
    if getattr(self.state, "recent_group", False) and self.state.history:
        names.add(RECENTLY_PLAYED)
    names.update(self.opts.sections)
    return names

def _collapse_all_groups(self) -> None:
    if self.filter:
        self._notify("Clear search before folding groups", self.theme.label)
        return
    self.collapsed_sections = set(self._all_header_names())
    self._rebuild_rows()
    # Keep focus on a header if possible
    ...

def _expand_all_groups(self) -> None:
    if self.filter:
        self._notify("Clear search before folding groups", self.theme.label)
        return
    self.collapsed_sections.clear()
    self._rebuild_rows()
    ...

def _bulk_fold_from_alt(self) -> None:
    headers = self._all_header_names()
    if headers - self.collapsed_sections:
        self._collapse_all_groups()
    else:
        self._expand_all_groups()
```

Footer when `category_selected`: swap the omitted Info hint for the bulk-fold label:

- Pad: `(("X",), "Collapse all", (A.ALT,))` or `"Expand all"` depending on state
- Keyboard: `(("KEY:TAB",), "Collapse all", (A.ALT,))` likewise

---

### Task 1: Bulk fold helpers + ALT on headers

**Files:**
- Modify: `src/couch_doom/ui.py` (`_on_action` ALT branch, new helpers, `_footer_hints`)
- Test: `tests/test_ui_features.py`

**Interfaces:**
- Consumes: `collapsed_sections`, `_rebuild_rows`, `_toggle_section` filter guard pattern
- Produces: `_collapse_all_groups()`, `_expand_all_groups()`, `_bulk_fold_from_alt()`, footer label helper `_bulk_fold_label() -> str`

- [ ] **Step 1: Write the failing tests**

```python
def test_alt_on_header_collapses_all_groups():
    app = make_app()
    app._rebuild_rows()
    app._select_row(0)  # Section A header
    opened = []
    app._open_info = lambda now: opened.append(now)

    app._on_action(Action.ALT, 0.0)

    assert app.collapsed_sections == {"Section A", "Section B"}
    assert not opened
    assert all(row.kind == "header" for row in app.rows)


def test_alt_on_header_expands_when_everything_is_collapsed():
    app = make_app(collapsed={"Section A", "Section B"})
    app._rebuild_rows()
    app._select_row(0)

    app._on_action(Action.ALT, 0.0)

    assert app.collapsed_sections == set()


def test_alt_on_preset_still_opens_info():
    app = make_app()
    app._rebuild_rows()
    app._select_row(1)  # Alpha preset
    opened = []
    app._open_info = lambda now: opened.append(now)

    app._on_action(Action.ALT, 1.0)

    assert opened == [1.0]
    assert app.collapsed_sections == set()


def test_bulk_fold_blocked_while_filter_active():
    app = make_app(filter_text="Alpha")
    app._rebuild_rows()
    notes = []
    app._notify = lambda msg, color: notes.append(msg)
    app.collapsed_sections = set()
    # Force header selection if present, or call helper directly:
    app.filter = "Alpha"
    app._collapse_all_groups()
    assert notes
    assert app.collapsed_sections == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ui_features.py::test_alt_on_header_collapses_all_groups tests/test_ui_features.py::test_alt_on_header_expands_when_everything_is_collapsed tests/test_ui_features.py::test_alt_on_preset_still_opens_info tests/test_ui_features.py::test_bulk_fold_blocked_while_filter_active -v`

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Change ALT handling:

```python
elif action == Action.ALT:
    row = self._sel_row()
    if self.rows and self.rows[row].kind == "header":
        self._bulk_fold_from_alt()
    elif self.rows and self.rows[row].kind == "preset":
        self._open_info(now)
```

Update `_footer_hints` so when `category_selected`, append the bulk-fold hint instead of leaving Info empty.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ui_features.py -k "alt_on_header or alt_on_preset or bulk_fold" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/couch_doom/ui.py tests/test_ui_features.py
git commit -m "$(cat <<'EOF'
feat(ui): expand or collapse all groups from a category header

EOF
)"
```

---

### Task 2: Menu rows for Expand all / Collapse all

**Files:**
- Modify: `src/couch_doom/ui.py` (`_menu_items`, `_menu_pick`)
- Test: `tests/test_ui_features.py`
- Optional: one sentence in `HELP_SECTIONS` under BROWSE THE LIST

**Interfaces:**
- Consumes: `_expand_all_groups`, `_collapse_all_groups`
- Produces: menu keys `"expand_all"`, `"collapse_all"`

**Menu too:** Pad users who stay on presets never hit X-as-bulk. Escape/Start → menu matches Refresh / Recent, without inventing L3 or a shoulder chord.

- [ ] **Step 1: Write the failing test**

```python
def test_menu_collapse_all_and_expand_all():
    app = make_app()
    app._rebuild_rows()
    app.mode = "menu"
    app._sound = lambda _n: None
    items = app._menu_items()
    collapse_i = next(i for i, (key, _) in enumerate(items) if key == "collapse_all")
    app._menu_pick(collapse_i)
    assert app.collapsed_sections == {"Section A", "Section B"}
    expand_i = next(i for i, (key, _) in enumerate(app._menu_items()) if key == "expand_all")
    app._menu_pick(expand_i)
    assert app.collapsed_sections == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ui_features.py::test_menu_collapse_all_and_expand_all -v`

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Insert after `"recent"` (or near the end before Help):

```python
("expand_all", "Expand all groups"),
("collapse_all", "Collapse all groups"),
```

In `_menu_pick`:

```python
elif key == "expand_all":
    self._expand_all_groups()
elif key == "collapse_all":
    self._collapse_all_groups()
```

These are one-shot menu picks (Enter/A), not Left/Right toggles.

Help line: "On a group heading, Tab (or X on a controller) expands or collapses every group. The menu can do the same."

- [ ] **Step 4: Run full UI feature tests**

Run: `python -m pytest tests/test_ui_features.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/couch_doom/ui.py tests/test_ui_features.py
git commit -m "$(cat <<'EOF'
feat(ui): add expand-all and collapse-all menu actions

EOF
)"
```

---

## Self-review

1. Spec: expand/collapse all, keyboard + pad, no letter-key clash, per-group toggle kept.
2. Placeholders: none.
3. ALT: Info on presets, bulk fold on headers only.
