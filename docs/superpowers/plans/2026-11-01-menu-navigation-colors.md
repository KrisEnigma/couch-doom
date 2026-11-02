# Menu, Navigation, and Color Plan

**Status:** Menu, navigation, recent-played group, automatic 72-bin themes, and the per-preset Colors submenu are implemented in the working tree. Remaining work is hands-on review and commit. The earlier menu/browser baseline is `7eadf9f`; performance follow-up is `5acb810`.

## Goal

Keep CouchDoom's direct game-list flow while adding the creator-requested menu and improving keyboard/controller file navigation. Offer finer automatic art colors plus a small curated per-preset color override set without expanding into a general settings framework.

## Completed

- Overlay menu (Escape / Start): Back to list, Refresh, Title music, Menu sounds, Recently played group, Colors for this preset, Choose launcher when available, Help, Quit.
- Home/End list navigation, browser improvements, Help shortcuts, Quit death sound, performance work for art/theme/logo/music dwell — as previously recorded; performance committed in `5acb810`.
- Optional Recently Played group (off by default) from `State.history`, with overlay input isolation, Favorites removal behavior, Backspace/caret, and filter Escape-clear.
- Automatic theme detection uses 72 five-degree hue bins with an 8-degree warm house fallback.
- **Colors** menu row (app-wide): Left/Right or Enter cycles Automatic, Red, Orange, Gold, Green, Teal, Blue, Violet, Magenta with an instant theme change. Persisted as `color_palette`.

## Remaining Work

### 1. Verify the latest browser behavior on Windows

- Manually check drive-root versus “Drives & Home”, parent-folder behavior, scrollbar dragging, one-page Left/Right and Page Up/Down, Home/End, and non-wrapping wheel scroll.

### 2. Hands-on color and menu review

- Inspect automatic hues on bright, dark, monochrome, and warm/red art.
- Try each manual override on several presets and confirm Automatic restores the art tint.
- Confirm the Colors submenu feels reachable from the menu without cluttering the list flow.
- Confirm category-heading highlight fade, Recently Played group, and held-Backspace repeat on the creator's machine.

### 3. Commit the working-tree changes

- After the review above, commit the uncommitted menu/list/color work as a reviewable change set.

## Working Style / Scope

- Work one feature at a time and return for hands-on review where display judgment matters.
- Do not add arbitrary RGB controls or expose every automatic hue bucket as a manual option.
- Prefer existing navigation, persistence, and drawing helpers; keep changes easy to roll back.
