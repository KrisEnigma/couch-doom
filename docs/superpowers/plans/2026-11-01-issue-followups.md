# Issue Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship expand/collapse all (#3 follow-up) on main.

**Architecture:** Detail steps live in the expand/collapse plan. This file is the order and the final GitHub note.

**Tech Stack:** Python 3, pygame, pytest (`python -m pytest`), existing CouchDoom `App`.

**Spec:** `docs/superpowers/plans/2026-11-01-expand-collapse-all.md` (issue #3 follow-up)

## Global Constraints

- #8 playability filter is skipped (closed). Do not implement it.
- No F5 refresh shortcut. Menu Refresh already exists on main.
- No metadata store, no most-played counts, no light theme, no per-preset color UI/JSON.
- Printable keys stay type-to-search. No letter-key bulk fold shortcuts.
- On a preset row, Tab/X stays Info. Bulk fold is header-only (plus menu).
- Author commits as KrisEnigma via env vars only; never change git config.
- After each task commit: `python -m pytest tests/test_ui_features.py -q` at minimum.
- When commenting on GitHub: say "on main for the next release," not "released," unless a GitHub Release tag exists.

## Menu row order (after #3)

1. Back to list
2. Refresh list
3. Title music
4. Menu sounds
5. Recently played group
6. Expand all groups
7. Collapse all groups
8. Colors
9. Choose launcher (optional)
10. Help
11. Quit

---

### Task 1: Expand / collapse all (#3)

**Files:**
- Follow: `docs/superpowers/plans/2026-11-01-expand-collapse-all.md` Tasks 1–2 end to end
- Modify: `src/couch_doom/ui.py`, `tests/test_ui_features.py`

**Interfaces:**
- Consumes: existing `collapsed_sections`, `_toggle_section` filter toast
- Produces: `_expand_all_groups`, `_collapse_all_groups`, `_bulk_fold_from_alt`, menu keys `expand_all` / `collapse_all`

- [ ] **Step 1: Execute expand-collapse plan Task 1** (helpers + ALT on headers + footer hint)

Do every checkbox in that task: failing tests, implement, pass, commit.

- [ ] **Step 2: Execute expand-collapse plan Task 2** (menu rows + Help line)

Insert `expand_all` / `collapse_all` after `"recent"`, before `"colors"`.

- [ ] **Step 3: Gate**

Run:

```bash
python -m pytest tests/test_ui_features.py -q
python tests/smoke.py
python -m pyflakes src tests
```

Expected: pass (note if smoke skips for no display).

---

### Task 2: Comment on #3

**Files:** none (GitHub only)

- [ ] **Step 1: Comment on #3**

Expand/collapse all is on main for the next release (not a GitHub Release yet). Point at the commit(s). Mention menu + Tab/X on a group heading.

- [ ] **Step 2: Stop**

No push unless Kris asks.

---

## Self-review

1. Spec: #3 only. #8 declined.
2. Placeholders: none.
