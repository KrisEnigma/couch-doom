# Playability Filter Implementation Plan

> **Status: CANCELLED.** Issue #8 closed; only one Missing-filter report. Keep this file as a sketch if demand returns. Do not implement.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menu cycle for All / Playable / Missing. Leave type-to-search and face buttons alone.

**Architecture:** Store `playability` on `State`. Filter in `_rebuild_rows` with `LaunchCommand.ok`. Menu row with Left/Right, same idea as Colors. No letter-key bindings.

**Tech Stack:** Python, pygame, existing `ui.App` menu + `state.State` JSON.

**Spec:** https://github.com/KrisEnigma/couch-doom/issues/8

## Global Constraints

- Default is All. Broken presets stay visible unless the player asks otherwise.
- No bare `p` / `m` keys. Printable keys already edit the search filter.
- No new face-button Action. Pad path is Escape/Start, menu, Left/Right.
- Reuse `commands[i].ok`. Don't invent a second missing check.
- Favorites and Recently Played use the same filter.
- Empty groups drop out after filtering, same as search.

---

### Task 1: Persist playability mode on State

**Files:**
- Modify: `src/couch_doom/state.py`
- Test: `tests/test_state_playability.py` (create)

**Interfaces:**
- Consumes: existing `State._load` / `_save` JSON shape in `last_played.json`
- Produces: `State.playability: str` one of `"all" | "playable" | "missing"`; `State.set_playability(mode: str) -> None`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from couch_doom.state import State


def test_playability_defaults_to_all_and_round_trips(tmp_path: Path):
    path = tmp_path / "last_played.json"
    state = State(path)
    assert state.playability == "all"

    state.set_playability("missing")
    assert State(path).playability == "missing"

    state.set_playability("nope")
    assert state.playability == "all"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_state_playability.py -v`

Expected: FAIL (`State` has no `playability`)

- [ ] **Step 3: Write minimal implementation**

In `state.py`:

```python
PLAYABILITY_MODES = ("all", "playable", "missing")

# in __init__:
self.playability = "all"

# in _load:
mode = data.get("playability", "all")
self.playability = mode if mode in PLAYABILITY_MODES else "all"

# new method:
def set_playability(self, mode: str) -> None:
    self.playability = mode if mode in PLAYABILITY_MODES else "all"
    self._save()

# in _save data dict:
"playability": self.playability,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_state_playability.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/couch_doom/state.py tests/test_state_playability.py
git commit -m "$(cat <<'EOF'
feat(state): persist playability list filter mode

EOF
)"
```

---

### Task 2: Filter rows by LaunchCommand.ok

**Files:**
- Modify: `src/couch_doom/ui.py` (`_matches` / `_rebuild_rows`, `make_app` helpers only via tests)
- Test: `tests/test_ui_features.py`

**Interfaces:**
- Consumes: `State.playability`; `self.commands[i].ok`
- Produces: `_playability_allows(idx: int) -> bool` used by row building

- [ ] **Step 1: Write the failing tests**

Extend `make_app` so tests can attach fake commands:

```python
def test_playability_playable_hides_missing_presets():
    app = make_app()
    app.state.playability = "playable"
    app.commands = [
        SimpleNamespace(ok=True),
        SimpleNamespace(ok=False),
        SimpleNamespace(ok=True),
    ]
    app._rebuild_rows()
    names = [row.text for row in app.rows if row.kind == "preset"]
    assert names == ["Alpha", "Gamma"]


def test_playability_missing_shows_only_broken_presets():
    app = make_app()
    app.state.playability = "missing"
    app.commands = [
        SimpleNamespace(ok=True),
        SimpleNamespace(ok=False),
        SimpleNamespace(ok=True),
    ]
    app._rebuild_rows()
    names = [row.text for row in app.rows if row.kind == "preset"]
    assert names == ["Beta"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ui_features.py::test_playability_playable_hides_missing_presets tests/test_ui_features.py::test_playability_missing_shows_only_broken_presets -v`

Expected: FAIL (all presets still listed)

- [ ] **Step 3: Write minimal implementation**

```python
def _playability_allows(self, idx: int) -> bool:
    mode = getattr(self.state, "playability", "all")
    if mode == "all" or not getattr(self, "commands", None):
        return True
    ok = self.commands[idx].ok
    if mode == "playable":
        return ok
    if mode == "missing":
        return not ok
    return True
```

Gate every preset index that enters Favorites / Recently Played / section hits with `self._playability_allows(i)` in addition to `_matches`. Keep text search independent: both must pass.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ui_features.py::test_playability_playable_hides_missing_presets tests/test_ui_features.py::test_playability_missing_shows_only_broken_presets -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/couch_doom/ui.py tests/test_ui_features.py
git commit -m "$(cat <<'EOF'
feat(ui): filter preset list by playability

EOF
)"
```

---

### Task 3: Menu row + Left/Right cycle (keyboard and controller)

**Files:**
- Modify: `src/couch_doom/ui.py` (`_menu_items`, `_set_menu_option`, `_menu_pick`, menu draw label, Help blurb if needed)
- Test: `tests/test_ui_features.py`

**Interfaces:**
- Consumes: `State.set_playability`, `PLAYABILITY_MODES` (import or mirror labels in ui)
- Produces: menu key `"playability"`; `_cycle_playability(delta: int) -> None`

**Input rules:**

| Input | Binding | Notes |
|--|--|--|
| Keyboard letters | Do not bind | They append to `self.filter` |
| Escape / Start | Opens menu | Existing |
| Menu Left / Right | Cycle All → Playable → Missing | Same as Colors |
| Menu Enter / A | Advance one step | Same as Colors |
| List footer | No new hint | Keep the footer light; menu / Help is enough |

- [ ] **Step 1: Write the failing test**

```python
def test_menu_left_right_cycles_playability():
    app = make_app()
    app.state.playability = "all"
    app.state.set_playability = lambda mode: setattr(app.state, "playability", mode)
    app.commands = [SimpleNamespace(ok=True)] * 3
    app.mode = "menu"
    app.menu_sel = next(i for i, (key, _) in enumerate(app._menu_items()) if key == "playability")
    app._rebuild_rows = lambda: None
    app._sound = lambda _n: None

    app._on_menu_action(Action.RIGHT)
    assert app.state.playability == "playable"
    app._on_menu_action(Action.RIGHT)
    assert app.state.playability == "missing"
    app._on_menu_action(Action.LEFT)
    assert app.state.playability == "playable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ui_features.py::test_menu_left_right_cycles_playability -v`

Expected: FAIL (no playability menu row)

- [ ] **Step 3: Write minimal implementation**

Add to `_menu_items` after `"recent"`:

```python
("playability", "Show presets"),
```

Labels for the value column (mirror Colors drawing):

```python
PLAYABILITY_LABELS = {"all": "All", "playable": "Playable", "missing": "Missing"}
```

```python
def _cycle_playability(self, delta: int) -> None:
    modes = ["all", "playable", "missing"]
    cur = getattr(self.state, "playability", "all")
    idx = modes.index(cur) if cur in modes else 0
    self.state.set_playability(modes[(idx + delta) % len(modes)])
    self._rebuild_rows()
    self._sound("open")
```

Wire `_set_menu_option` / `_menu_pick` like Colors. In `_draw_menu`, show `PLAYABILITY_LABELS[...]` beside the row.

Optional Help line under SEARCH AND FAVORITES: "The menu can limit the list to playable or missing games."

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_ui_features.py -v`

Expected: PASS (including new tests)

- [ ] **Step 5: Commit**

```bash
git add src/couch_doom/ui.py tests/test_ui_features.py
git commit -m "$(cat <<'EOF'
feat(ui): cycle playability filter from the menu

EOF
)"
```

---

## Self-review

1. Spec: All / Playable / Missing, default All, no `p`/`m`, reachable from the menu.
2. Placeholders: none.
3. Types: `playability` string modes match in state and ui.
