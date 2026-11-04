# GPU canvas on Windows and Linux

Mac already draws through the GPU. Windows and Linux still paint in software, and that is the whole job: put them on the same path. Do not write a second renderer.

The Mac work is local and uncommitted. `canvas.py` is not on `origin/main`. Start from this working tree (or a commit of it), not from a fresh clone of main.

Tested on an M4 MacBook, 3024×1964, ProMotion, measured 120 Hz. pygame-ce 2.5.8 (SDL 2.32.10).

## Result on the Mac

Software, full screen, before this change: about 9.9 ms per frame at rest (~100 fps) and 15.7 ms while scrolling (~64 fps). A 120 Hz frame is 8.3 ms, so the CPU blit could not keep up.

GPU, same machine: the CPU spends about 1 ms per frame at rest and about 5 ms when moving to another game. The display holds 118–120 fps both at rest and while scrolling. `Renderer(vsync=True)` paces the present. Motion uses `dt` from the last frame (`_approach`), so a faster panel looks smoother and does not play animations faster.

Screenshots of the GPU and software paths, at rest and mid theme-fade, differed by at most 2/255 on any channel.

Overlay, dev only: `COUCHDOOM_SHOW_FPS=1` prints `120 fps · 120 Hz · gpu`. `COUCHDOOM_RENDERER=software` forces the old path. `COUCHDOOM_RENDERER=gpu` forces the canvas.

## Already done, shared by every platform

These were fixed on the Mac after review. They are in the tree, covered by tests, and are not your job. Know they exist so you don't redo or undo them.

- **Fallback catches renderer errors.** `video.Renderer` raises `pygame._sdl2.sdl2.error`, a `RuntimeError` that is not a `pygame.error`. `canvas.ERRORS = (pygame.error, RuntimeError)` is what `Canvas.__init__` and `App._window_target` catch. A failed renderer logs `gpu renderer unavailable` and the app uses `window.get_surface()`.
- **No SDL software renderer.** `canvas.ACCELERATED = 1`, so a machine without a GPU (RDP, basic display adapter, VM) gets the software window surface instead of SDL's software renderer, which is slower than plain blitting. Smoke sets `canvas.ACCELERATED = -1`, because the dummy video driver only has the software renderer.
- **Window events go through `App._on_window_event`.**
  - `WINDOWCLOSE` quits. With the canvas's hidden format window open, the close button and Alt+F4 post `WINDOWCLOSE` and never `QUIT`.
  - Events from the format window are swallowed, so its hide/show cannot mark the app hidden.
  - `WINDOWDISPLAYCHANGED` re-reads the refresh rate.
  - `RENDER_DEVICE_RESET` rebuilds the window, which re-uploads every texture.
- **The format window has `utility=True`** so it stays out of the Windows and X11 taskbar.
- **The refresh rate is read once per window,** into `App.refresh_hz` in `_create_window`, not every frame.
- **`App._frame_cap()` is the `clock.tick` ceiling.** On the canvas it is `round(refresh_hz * 1.25)`: vsync paces the present, and the cap only guards against a present that doesn't block. A cap equal to a rounded-down rate (Windows reports 59 or 119 for 59.94 or 119.88 Hz) drifts one sleep past a vblank about once a second. The software path keeps `tick(refresh_hz)`. Never use `tick(0)`: without a blocking vsync it spins a core, which matters on a Deck battery.

## Why Windows and Linux are still slow

`use_gpu()` in `src/couch_doom/ui.py` returns true on macOS unless the env var says otherwise. Windows and Linux never call it.

`_create_window` on those platforms uses `pygame.display.set_mode`. `canvas.Canvas` needs a `pygame.Window`, because `pygame._sdl2.video.Renderer` is built from a window. Setting `COUCHDOOM_RENDERER=gpu` on Windows today does nothing: the window is never offered to the canvas.

`canvas.py` itself is platform-neutral. The port is the window, the refresh rate, the window icon, and two native-handle call sites.

## What to change

### 1. Open a `pygame.Window` on Windows and Linux

Keep the Mac branch as it is: `allow_high_dpi=True`, then `set_fullscreen(desktop=True)` when not windowed, then the Dock and shadow calls.

For Windows and Linux, replace the `set_mode` branches:

- `--windowed` (flag in `__main__.py`): a normal window at `(1440, 810)`, same size as today.
- Without it: borderless, sized to `pygame.display.get_desktop_sizes()[0]`, at position `(0, 0)`. That matches today's `pygame.NOFRAME` window. Do not use exclusive fullscreen (`fullscreen=True`); it changes the display mode, and the point is to track the desktop's refresh the way a normal window does. Display 0 is the primary monitor, which on X11 is not always at `(0, 0)`. Today's `set_mode` setup has the same limitation; leave it.
- Pass `allow_high_dpi=True` on every platform. It keeps a scaled Wayland session sharp, and `self.dpi` already handles the ratio.
- SDL ignores `position` on Wayland. No error is raised; nothing to catch.
- Then the same steps as the Mac branch: `self.screen = self._window_target(self.window)`, `self.dpi = self.screen.get_width() / self.window.size[0]`, and `_set_window_icon(self.window)`. `pygame.Window` puts pygame's logo back on the window, and `display.set_icon` before `set_mode` no longer applies, so without that call the taskbar shows the pygame snake. Mouse events are already scaled by `self.dpi` when it is not 1.

Do not call `get_surface()` on the main window before the `Renderer` exists: SDL answers `Surface already associated with window` and the canvas cannot be created afterwards. `_window_target` already handles the order.

Leave `use_gpu()` defaulting off for Windows and Linux in the port commit, and test with `COUCHDOOM_RENDERER=gpu`. Flip the default in a separate commit once the hardware checks below pass, and update `use_gpu`'s docstring, which still says those platforms use `set_mode`.

### 2. Refresh rate without `set_mode`

`pygame.display.get_current_refresh_rate()` raises `No open window` for every `pygame.Window`, including the software fallback. After this port nothing uses `set_mode`, so that call will always fail on Windows and Linux. On the Mac that is why the loop capped at 60 on a 120 Hz panel until the CoreGraphics fallback went in.

`display_refresh_rate()` today: try `get_current_refresh_rate`, then on Darwin CoreGraphics for the main display, else `FALLBACK_FPS` (60). It is called once per window and on `WINDOWDISPLAYCHANGED`, never per frame.

Add a Windows and Linux fallback after the `get_current_refresh_rate` attempt:

- `pygame.display.get_desktop_refresh_rates()` works with no `set_mode` window and returns one rate per display.
- pygame-ce 2.5.8 has no API for a window's display index or for display positions, so the window's own display cannot be found. Take `max(rates)`. Guessing high is safe: on the canvas, vsync paces the present at the window's real rate and the cap only stops a spin. Guessing low makes `tick` sleep and throws the GPU win away.
- Skip zeros. If every entry is 0, return `FALLBACK_FPS`.
- Log the chosen rate where it is computed (`_create_window` or the display-changed event), not inside the function, so it does not log per frame.

The CoreGraphics helper stays Mac-only. It reads the main display, which is wrong for a window on a second monitor; vsync still presents at the real rate, only the cap is off.

Add a test beside `test_pygame_window_on_mac_uses_the_display_rate`: when `get_current_refresh_rate` raises and the platform is `win32` or `linux`, the result is the max of the desktop rates, and 60 when they are all 0.

### 3. Native handle: `Window.handle`, not `get_wm_info`

Two call sites use `pygame.display.get_wm_info()["window"]`. For a `pygame.Window`, `get_wm_info()` returns `{}`:

- `_force_foreground()` — after a game exits, Windows will not focus a background process without this HWND.
- `_hold_loading` — passes the handle to `handover.engine_window_visible` so the loading cover can ignore our own window. The search is by the engine's pid, so a missing handle usually still finds the game. The foreground call has no such backup.

pygame-ce 2.5.8 adds `Window.handle`: HWND on Windows, X11 window on X11/XWayland, 0 on Wayland. Change `_force_foreground()` to `_force_foreground(handle: int | None = None)`, pass `self.window.handle` when it is non-zero, and keep `get_wm_info` as the fallback when no handle is given. Use the same handle in `_hold_loading`. Do not use `Window.id`; that is SDL's window id, not an HWND or Xid.

`packaging/readme_screenshots.py` replaces `_force_foreground` with `lambda: None`. Make that `lambda *a: None` once the signature takes an argument.

Wayland already releases the loading cover without a handle (`handover.engine_uses_wayland`). Leave that logic alone.

### 4. Pick the Windows renderer driver

Default SDL ordering on Windows may pick Direct3D 9. Prefer Direct3D 11: set the `SDL_RENDER_DRIVER` hint to `direct3d11` before `Canvas` builds the renderer, or pass its index from `video.get_drivers()`. Fall back to SDL's choice if that driver is missing. Log the driver in use alongside a successful canvas, so a report says which backend the numbers came from. Linux keeps SDL's default (OpenGL).

## Rules that will bite if you "just draw"

- A surface must not be drawn onto after its first blit to a `Canvas`. The texture is cached in a `WeakKeyDictionary` keyed by the surface object and never refreshed. The UI already builds a surface once and then only blits it. A new full-screen background is a new surface, which is correct: the first blit uploads it.
- `Canvas.blit` rejects `special_flags`. The one blend the screen needs is `blit_mix` (theme overlays). `fill(..., special_flags=BLEND_MULT)` is implemented (`BLENDMODE_MOD`) and is the dim during the launch wipe. Any new blend needs a real implementation, not a silent software fallback that looks right in tests and wrong on screen.
- `Canvas.copy()` is `Renderer.to_surface()`, a full readback. The launch wipe calls it once. Do not call it per frame.
- Shapes go through `canvas.rect`, `canvas.lines`, and `canvas.line`. They call `pygame.draw` on a real surface and cache a small texture on a `Canvas`. Do not add raw `pygame.draw.*` calls on `self.screen`.
- `Canvas.close()` must run before `window.destroy()`. SDL frees the renderer and its textures with the window. `_close_window` already does this; keep the order. The format window is destroyed inside `close()`.
- The detail panel is a subsurface of only the inked rows, and the blit uses `get_offset()` to put it back. Uploading the whole panel made move frames the slow case. Leave that crop in place.
- First time a game's art or a theme is shown, the upload can be tens of MB and drop a frame (12–15 ms on the Mac). Later visits reuse the texture. Do not fix that in this port. If it shows on a 144 Hz panel, the follow-up is to build the background from a 1 px gradient and a scanline strip instead of a full-screen surface per theme, as a separate change.
- `packaging/readme_screenshots.py` overrides `_create_window` with a hidden `set_mode` window and needs a real `Surface` for `smoothscale`. Leave it on software.

## What a frame costs, so you know a regression

Measured on the Mac, GPU path:

| Moment | CPU time | What dominated |
| --- | --- | --- |
| Rest, warm textures | ~1 ms | UI bookkeeping. Present waits on vsync. |
| Scrolling, warm | well under an 8.3 ms frame | Same. Held 120 fps. |
| Move to a new preset, detail open | ~5 ms | Detail-panel upload. |
| First sight of a theme or title art | 12–15 ms once | Texture upload. |

Software costs at the Mac's ~6 MP: full-screen blit ~1.6 ms, theme crossfade ~4.3 ms, veil ~2.3 ms, flip upload ~2.3 ms. Scale with pixel count. A 4K frame is the one that misses 144 Hz in software and should not miss it on the GPU.

## How to test

From the repo, with the project venv. PowerShell:

```
.\.venv\Scripts\python -m pytest -q
$env:COUCHDOOM_RENDERER='gpu'; .\.venv\Scripts\python tests\smoke.py
$env:COUCHDOOM_RENDERER='software'; .\.venv\Scripts\python tests\smoke.py
```

Run smoke in both modes. Only the Mac defaults to the canvas, so a plain smoke run on Windows or Linux skips it. Smoke only proves the API does not crash under SDL's dummy driver. Frame timing has to come from a real window.

Then, on the PC's actual panel:

```
$env:PYTHONPATH='src'; $env:COUCHDOOM_SHOW_FPS='1'; $env:COUCHDOOM_RENDERER='gpu'
.\.venv\Scripts\python -m couch_doom
```

(`run.bat` sets `PYTHONPATH` too. Linux: export the same variables and use `.venv/bin/python`.)

Check, in this order:

1. The overlay reads the panel's real Hz, not 60, and fps sits on that number at rest and while holding up/down through the list. The log has `gpu renderer` with the driver name, not `gpu renderer unavailable`.
2. `COUCHDOOM_RENDERER=software` in the same build is visibly the old pace, and the overlay says `software`. Screenshot both at rest and halfway through a theme change; per-channel difference should stay in the noise (max 2 on the Mac).
3. Mouse hits the row you click, including on a scaled Windows desktop (150%). Keyboard and gamepad too.
4. Quit from the close button, Alt+F4, and the in-app confirm. The process must exit, and there is no second CouchDoom entry in the taskbar.
5. Launch a game. The loading cover stays up until the engine's window is visible, CouchDoom comes back to the foreground when the game exits, and a second launch still works. This is the `Window.handle` check.
6. With `--windowed` (1440×810) and without it (borderless fullscreen). Alt-tab away and back in borderless.
7. Steam Deck: borderless on the 800p panel, Game Mode's "Exit game" quits cleanly (an X11 close request, which is `WINDOWCLOSE`), and a native-Wayland session in Desktop Mode. SDL picks XWayland while `DISPLAY` is set; force native with `SDL_VIDEODRIVER=wayland`. If the canvas fails there, the log line `gpu renderer unavailable` plus a software window is the accepted result, not a crash. Handover already bails out on native Wayland; do not break that while chasing a handle.

After a PyInstaller build on Windows, confirm both `couch_doom.canvas` in the PYZ and the compiled `pygame/_sdl2/video` extension in the bundle. The extension lives outside the archive, so finding `couch_doom.canvas` alone does not prove the GPU path shipped.

## Leave alone

- Motion. `_approach(current, target, rate, dt)` is already frame-rate independent. Do not retune the rates.
- `handover.hold`. It sleeps `frame_seconds` from the caller. `_hold_loading` already passes `1/hz` and a grace count from `HANDOVER_GRACE_SECONDS` (4/60 s). A faster panel paints more frames in the same cover. Do not switch that back to a fixed frame count.
- The music timers. See below.
- Mac fullscreen, the CoreGraphics rate, and the Dock icon.

## Music, so you don't chase it

Not part of this port. Title music starts well after a preset's art is on screen. That is timers, not rendering.

The Mac is tuning this on its own. A settled preset starts its track after `DWELL_SECONDS` (0.12 s, just past a held repeat) and fades in over `FADE_IN_MS` (200), while the art fades in 0.3 s. The preset above and below is rendered ahead into the cache. Do not change `DWELL_SECONDS`, `FADE_IN_MS`, or `MusicPlayer.warm` in this port. `tests/test_music_dwell.py` locks the timing.
