# Full screen toggle

## Status

On `main`. Alt+Enter and the menu row shipped with the GPU window (changelog **New in 1.2.6**). `__version__` is still `1.2.5`, so the log header says 1.2.5 until that moves.

Live check on the PC, 4 Nov 2026: 2560×1440, 125% scaling (120 dpi), 170 Hz, Direct3D 11, pygame-ce 2.5.8 (SDL 2.32.10). A throwaway `COUCHDOOM_DATA_DIR` was used. Kris's real `state/settings.ini` was not touched.

A bug found in that check is fixed in the working tree and not committed: recreating the window swallowed the key-up. See [Key-up lost on recreate](#key-up-lost-on-recreate).

## What it is

`WINDOWED_SIZE` is `(1440, 810)`, the size of a window that has never been dragged. The other mode is borderless at `pygame.display.get_desktop_sizes()[0]`, placed at `(0, 0)`. Not exclusive fullscreen. Exclusive fullscreen changes the display mode and its refresh. Do not "fix" it to that.

The windowed frame is `resizable=True`, with `minimum_size` at `WINDOWED_MIN` `(400, 240)` (or the desktop, when that is smaller). That thick frame is what Windows snap needs. Dragging, snapping, and the maximize button all change the client size. `_on_window_resized` runs `_layout()` when the drawable size changes, and clears a canvas clip so the new area is not left black. Text scale stays `h / 1080`. The borderless window stays `resizable=False`.

The size written to `state` is `window.size` (the units passed back to `pygame.Window`), under `window_size`. A drag emits a size per move, so the file is written after `WINDOW_SIZE_SAVE_DELAY` (0.4 s), or immediately when Alt+Enter leaves the window or the app quits. The default 1440×810 is not written while `window_size` is still missing. A saved size is clamped into the desktop on the next open. A borderless size change is laid out and not stored.

| | Windows | Linux | Mac |
| --- | --- | --- | --- |
| Full screen | same window, `borderless=True`, the monitor the window is already on | new `pygame.Window(..., borderless=True, position=(0, 0))` | `set_fullscreen(desktop=True)`, then `_disable_macos_fullscreen_shadow()` |
| Window | same window, `borderless=False`, saved size, resize frame on | new resizable window, `WINDOWPOS_UNDEFINED` | `set_windowed()`, then `size = _windowed_size()` |
| Toggle | resize in place. Same HWND. | `_close_window` + `_open_window`. A new window. | resize in place. Same window. |

Moving that borderless window onto another monitor, such as with Win+Shift+Arrow, resizes it to the monitor it landed on. A captioned window is left at the size you dragged. Windows keeps the window so Enter's key-up still arrives. The "already toggling" latch clears on that key-up, and Alt stays down, so a second Alt+Enter while Alt is held toggles again. Do not recreate it, and do not call `SDL_ResetKeyboard` on this path: that call forgets a held Alt.

X11 ignores a move on a window that already exists, so Linux still recreates. A borderless window grown in place stays centred and runs off the screen. The new window is placed at creation. Its canvas and textures die with the old one. The log gains another `gpu renderer` / `display refresh` pair per toggle. Two pairs for one toggle is the recreate. A stream of them is the bug below. Linux is also the path that still clears the latch and calls `SDL_ResetKeyboard`, because the key-up was delivered to a window that no longer exists.

`App.__init__` takes `windowed=args.windowed or state.windowed`. `--windowed` forces a window for this run and does not write the file. The file changes only in `_toggle_window`, via `state.set_windowed`. A fresh data dir still saves `windowed: false` during language detection, while the on-screen flag is true because of `--windowed`. The next save is the first toggle.

`state.windowed` is true only when the JSON value is exactly `true`. Missing or anything else means full screen.

## Menu

Row order from `_menu_items`: Back to list, Refresh list, Title music, Menu sounds, Recently played group, **Full screen**, Colors, Language, then Choose launcher when any launcher is known, Help, Quit. Full screen is the item after Recently played. Five Downs from the top land on it.

The badge is `not self.windowed`: **On** is borderless, **Off** is the window. Enter / A calls `_menu_pick`. Left / Right call `_set_menu_option`. Both call `_toggle_window`. A repeated Left/Right must not. `repeat=True` returns before the toggle. Colors and Language still repeat.

Escape opens the menu only from the list. On the launcher picker, Escape is Back. On What's new, Escape closes that screen and a second Escape opens the menu. Alt+Enter is handled in `_on_key` before any of that, in every mode, including search, and it does not also confirm. A held Alt+Enter toggles once (`_alt_enter_held`, cleared on Return key-up).

The menu panel is `(18, 14, 13)`. The selected row is a 16/255 white wash over that, which reads as about `(33, 29, 28)`. Scale is `h / 1080`. At 810 px tall the panel is only about 570 px wide (`min(window, 760 * 0.75)`). A sample 280 px left of center misses it. Samples inside ±120 px of center hit it.

## Measured

Aware of per-monitor DPI (`SetProcessDpiAwareness(2)`). An unaware process on this display virtualizes the same window to an outer size of about 1166×686. Do not judge 1440×810 from an unaware process.

Windowed, on 4 Nov 2026, before the resize frame. Caption on, thick frame off, popup off, style `0x16CA0000`. The current windowed style is `0x16CF0000`. See the probe notes below.

- Client `(1440, 810)`. That is the pygame size. The outer rect was `(551, 277, 1458, 857)`: the caption and borders add about 18×47.
- `GetDpiForWindow` was 120.

Borderless, no caption, popup, style `0x96020000`:

- Window and client both `(0, 0, 2560, 1440)`, equal to the monitor rect.
- HWND changed. The old one was destroyed.

Menu, after the fix: Down onto Full screen showed **On** while borderless. Enter created a new captioned 1440×810 window, the row read **Off**, and `windowed` in the throwaway state file was `true`. A second launch with the same data dir and no `--windowed` opened that 1440×810 window again.

The log for one Alt+Enter plus one menu Enter is three `gpu renderer` lines (startup, shortcut, menu), then one more on the relaunch. Not a burst.

## Key-up lost on recreate

Confirmed before the fix, on this PC.

Windows and Linux destroy the window inside `_toggle_window` while Alt and Enter are still down. The key-up is delivered to a window that no longer exists. SDL keeps Alt in its modifier state, and `_alt_enter_held` stays true because the Return key-up never arrives.

What that looks like:

- Down, Escape, and Left still work. They are not the Alt+Enter chord.
- The next Enter is seen as Alt+Enter. `_alt_enter_held` is still set, so `_on_key` swallows it and does not toggle. The menu row stays selected. Enter appears dead. `GetAsyncKeyState(VK_MENU)` can already say Alt is up; SDL's mod state is the one that is stuck.
- Left and Right are in `gamepad.REPEATABLE` (first repeat after 0.32 s, then every 0.07 s). The key-up is gone, so `Input.update` keeps firing. Each firing calls `_toggle_window`, which recreates the window again and loses the key-up again. The window flipped for about eight seconds (a `gpu renderer` line several times a second) until the process died with exit code 1. A held Left is enough. Do not retest that path without the guard below.

The fix, at the end of `_toggle_window`:

- `_alt_enter_held = False`
- `input.reset()`, so a held direction is no longer repeating
- `_release_keyboard()` → `SDL_ResetKeyboard()`. On Windows that is `pygame/SDL2.dll` via `ctypes.WinDLL`. Elsewhere `ctypes.CDLL(None)` (RTLD_DEFAULT); pygame has already loaded SDL. A missing symbol is ignored.

And `_set_menu_option` ignores `repeat=True` for the Full screen row, so one nudge is one toggle even if a repeat sneaks through before the reset.

`SDL_ResetKeyboard` sends key-ups for whatever SDL still thinks is down. It does not re-press a key the user is still physically holding. The next real press works. Do not remove the reset because a unit test has no real keyboard: the live failure is the lost key-up, and the unit test only checks that `input.reset` ran and the latch cleared.

## Unit tests

```
.\.venv\Scripts\python -m pytest -q --tb=short -k "fullscreen or alt_enter or window_mode or menu_full"
```

Eight tests, all passing after the fix:

- `test_menu_full_screen_row_uses_the_same_toggle_as_alt_enter` — Enter and Left both call `_toggle_window`. A `repeat=True` Right does not add a third call.
- `test_the_window_mode_is_remembered` — the JSON flag round-trips.
- `test_alt_enter_on_linux_recreates_the_window_so_borderless_lands_at_the_corner` — close, `display.init`, open, flag saved, latch cleared, `input.reset` called.
- `test_alt_enter_on_windows_keeps_the_window_and_a_held_alt` — same window, borderless at `(0, 0)`, captioned window restored to where it sat. The latch stays set and the keyboard is not reset.
- `test_borderless_window_is_created_at_the_desktop_corner` — size is the desktop, `borderless=True`, `position=(0, 0)`.
- `test_alt_enter_on_mac_uses_desktop_fullscreen_not_a_mode_change` — `set_windowed` / `set_fullscreen(desktop=True)`, not a mode change. Shadow helper runs only on the way into full screen.
- `test_alt_enter_is_consumed_and_a_held_key_toggles_once` — Return and keypad Enter, with either Alt bit. A second event while the latch is set does not toggle again. A bare Return is not consumed.
- `test_alt_enter_toggles_while_search_is_open_instead_of_closing_it`.

These do not open a real window. The sizes, the badge, and the lost key-up were only visible live.

## Live check, without repeating the dead ends

Throwaway data dir. Do not point this at the repo `state/` or at `%LOCALAPPDATA%\CouchDoom`.

```
$env:COUCHDOOM_DATA_DIR = "$env:TEMP\couchdoom-fs-data"
$env:COUCHDOOM_NO_UPDATE_CHECK = '1'
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python -m couch_doom --windowed --options 'D:\Standalone\UZDoom\DoomRunner\options.json'
```

`--options` skips the picker, so Escape opens the menu. `COUCHDOOM_NO_UPDATE_CHECK` skips the update notice. An empty data dir is a first run (`returning` is false), so What's new stays closed. Writing a `settings.ini` before launch makes `returning` true and What's new opens; the first Escape then closes that, and only the second opens the menu.

The window exists about two seconds after launch, when the log has `gpu renderer` and `display refresh`. Title music will start (`D_INTRO`, then the selected preset). That is the normal music path, not a hang. `INPUT_COOLDOWN` (0.45 s) applies after a game returns, not at startup.

### The window is not the process you spawned

`.venv\Scripts\python.exe` on Windows relaunches itself. `Popen.pid` stays alive as the parent and owns an empty 0×0 window. The CouchDoom window belongs to the child python. Walk the process tree. `taskkill /F /T /PID <parent>` kills both. `Popen.kill()` leaves the child on screen.

There are two top-level windows titled CouchDoom. The canvas format window is 1×1 and hidden (`canvas.py`, `pygame.Window(..., hidden=True)`). Keep the visible one whose rect is larger than 100×100.

### ctypes will silently find no window

`EnumWindows` gives a 64-bit HWND. Calling `GetWindowThreadProcessId` / `GetWindowRect` / `IsWindowVisible` without `argtypes` truncates it to 32 bits, the pid never matches, and the probe reports no window while the log already shows a renderer. Set `argtypes` on every user32 call that takes an HWND. `GetWindowLongW` is fine for `GWL_STYLE` (-16) once the HWND is passed intact. Style values that passed: windowed `0x16CA0000`, borderless `0x96020000`.

Set the probe DPI-aware before measuring. A fresh window's client rect is 1440×810, or `window_size` when that is set. The borderless window rect matches the monitor from `MonitorFromWindow` + `GetMonitorInfoW`, within a few pixels. Caption present vs absent is the other half of the check (`WS_CAPTION = 0x00C00000`).

Style values: windowed `0x16CF0000` (the old `0x16CA0000` plus `WS_THICKFRAME` `0x00040000` and `WS_MAXIMIZEBOX` `0x00010000`), borderless `0x96020000`. The thick frame is the resize and snap handle. A probe that still expects `0x16CA0000` is looking at the fixed window from before this.

### Sending keys

`SendInput` works once the window is foreground. Arrow keys are extended: set `KEYEVENTF_EXTENDEDKEY` (0x0001) or SDL never sees Down. Escape and Enter are not extended, so a probe that forgets the flag opens the menu and then sits on Back to list. Five extended Downs move onto Full screen.

Hold Alt+Enter until the HWND changes, wait a couple of tenths, then release. Releasing during the recreate is the lost key-up, and the following Enter does nothing even though the OS says Alt is up.

Do not mix `keybd_event` Alt (the focus trick in `_force_foreground`) with a later `SendInput` Alt chord. The two paths desync, and Alt stays down. Check `GetAsyncKeyState(VK_MENU)` before the menu keys. If the window is already foreground, `SetForegroundWindow` alone is enough.

Enter on the game list launches the selected game. Press it only after the center of the window is the menu panel (`(18, 14, 13)` on several pixels). A dark title screen can look similar; the badge text and the selected-row wash are the confirmation.

A synthesized Alt+F4 does not reach the borderless window. `PostMessage(hwnd, WM_CLOSE, 0, 0)` does. The app treats `WINDOWCLOSE` as quit. After a clean close the process is gone, including the hidden format window.

## Leave alone

- Borderless-at-desktop-size on Windows and Linux, and `set_fullscreen(desktop=True)` on Mac. The GPU canvas (`docs/gpu-canvas.md`) has the same rule, plus the vblank sleep. This toggle recreates the window, which already zeros `_frame_period` so the new panel's vblank is learned again.
- The one-toggle latch on Alt+Enter. A held chord must not flip every repeat.
- The repeat guard on the menu row. Taking it off brings back the recreate loop.
- `_release_keyboard`. The unit tests do not prove it; the live Enter-after-Alt+Enter case does.
