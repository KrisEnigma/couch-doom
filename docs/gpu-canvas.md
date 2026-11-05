# GPU canvas on Windows and Linux

## Status

Ported, on `main` in `a90c4fe`. Windows and Linux draw through the same `canvas.Canvas` as the Mac, with no second renderer.

`use_gpu()` is on everywhere. `COUCHDOOM_RENDERER=software` forces the old path. A machine with no GPU still gets the window surface, because the canvas refuses SDL's software renderer.

Mac baseline, from the original port: M4 MacBook, 3024×1964, ProMotion, 120 Hz, pygame-ce 2.5.8 (SDL 2.32.10).

## Measured

Windows, the PC (Ryzen 5 5600X, RTX 3070 Ti), 2560×1440 at 125% scaling, 170 Hz, Direct3D 11:

- The log has `gpu renderer: driver: direct3d11` and `display refresh: 170 Hz`.
- Pacing: 167 fps at rest. `present()` blocks about 2 ms per frame, and the learned period is about 5.8 ms.
- Held Down through the list: about 135–140 fps. Held Up: about 147–150 fps. Frame work p50 0.4–0.6 ms. Software in the same build held about 90 fps.
- GPU and software pixels match within 2/255 on the checked frames.
- Title art appears a median 70 ms after a move (worst 144 ms). Before the vblank fix it was 917 ms median, 2.9 s worst. Software is 136 ms median.

Linux, under WSL2 with WSLg on a 60 Hz desktop: the renderer is `opengl` on both X11 and Wayland. Pacing holds the 60 Hz desktop rate. Wayland prints Mesa/EGL warnings but still comes up. Not tested on a real Linux desktop or a Steam Deck.

## What the port does

### Window

Windows and Linux open a `pygame.Window` (`_create_window`). Without `--windowed` it is borderless at `pygame.display.get_desktop_sizes()[0]`, at (0, 0). `--windowed` starts at 1440×810, or the size the player last dragged or snapped, and that window is resizable. It is not exclusive fullscreen, so the window tracks the desktop's refresh the way a normal window does. Alt+Enter (`_toggle_window`) switches between those two. It must stay borderless-at-desktop-size on Windows and Linux, and `set_fullscreen(desktop=True)` on Mac. Do not "fix" it to exclusive fullscreen: that changes the display mode and its refresh. Do not take the resize frame off the windowed mode.

Windows resizes the existing window on Alt+Enter. Destroying it ate Enter's key-up, and the keyboard reset then forgot a held Alt, so a second Alt+Enter did nothing until Alt was pressed again. Linux still closes and reopens: X11 ignores a position request on an existing window, so a borderless window grown in place stays centred and runs off the screen. A new window takes `position=(0, 0)` at creation. Do not switch Linux back to resizing in place. `allow_high_dpi=True` on every platform, and `_set_window_icon` runs after the window opens, or the taskbar shows pygame's logo.

### Refresh rate

`display_refresh_rate()` tries `get_current_refresh_rate()`, which always raises for a `pygame.Window`. On win32 and linux it falls back to `max(get_desktop_refresh_rates())`, skipping zeros, then to 60. The highest rate is a deliberate guess: pygame-ce 2.5.8 cannot say which display a window is on. The result is logged once as `display refresh` in `_create_window`.

### Native handle

`_force_foreground(handle)` and `_hold_loading` take `self.window.handle or None`. The handle is an HWND on Windows, an XID on X11, and 0 on Wayland, which reads as None. `get_wm_info()` is the fallback, since it returns `{}` for a `pygame.Window`. `Window.id` is SDL's id, not a handle, and must not be used here.

### Renderer driver

On Windows, `canvas.driver_index()` picks `direct3d11` by its index in `video.get_drivers()`, because pygame has no SDL hint API. SDL's own pick is the fallback if that driver is missing. Linux keeps SDL's default, which is OpenGL.

The log names the backend SDL chose. `canvas.driver_name` reads it through ctypes. On Linux the pygame-ce wheel loads a private, hashed copy of SDL from `pygame_ce.libs`, so `canvas.vendored_sdl` finds that file; the process-wide symbols are not there.

## Present() holds the GIL

This is not in the original spec, and it was the cause of the slow art.

On Windows and Linux, `present()` waits for vblank while holding the GIL. At 170 Hz that was about 5.6 ms of every 5.9 ms frame. Background workers (title art, the cache warmer, the MIDI render) only ran in the gaps. A background job took 270 ms while `present()` looped, against 90 ms idle.

`App._flip()` therefore sleeps until about `VSYNC_MARGIN` (2 ms) before the next vblank, then calls `present()`. Sleeping releases the GIL.

The sleep target comes from a learned period, `_frame_period`, not from the desktop guess alone:

- A `present()` that blocks for more than 0.5 ms means the wait woke too early. The period grows by half the overshoot.
- A `present()` that returns at once (a compositor that does not block) shortens the wait.
- A frame that hitched late is ignored, so a stall does not stretch the period.
- The period is clamped to 24–360 Hz.
- `WINDOWDISPLAYCHANGED` resets it, because the new panel has a new vblank.

Do not remove the sleep to simplify `_flip`. It is what keeps the art fast.

## Background upload

A full-screen background used to be one 6 ms texture upload at 2560×1440. `_make_background` now builds a one-pixel column and scales it, and keeps the column in `_bg_columns`. On the canvas, `_blit_background` draws the column with `Canvas.blit_scaled`, which costs about 0.01 ms. The pixels are identical to the old full-screen blend. Software still blits the full surface.

## Linux background workers

`lower_current_thread_priority()` sets nice 5 on the calling thread (`gettid` + `setpriority`), the same step as Windows' below-normal priority. Other platforms are a no-op. The nice value is per-thread on Linux, so only the workers drop, not the UI thread.

## Rules that will bite if you "just draw"

- A surface must not be drawn onto after its first blit to a `Canvas`. Textures are cached in a `WeakKeyDictionary` keyed by the surface and never refreshed. The same applies to `_bg_columns`: a column is only drawn, never changed after `_make_background` returns.
- `Canvas.blit` rejects `special_flags`. The blend the screen needs is `blit_mix` (theme overlays). `fill(..., special_flags=BLEND_MULT)` is implemented as `BLENDMODE_MOD` and is the dim during the launch wipe. A new blend needs a real implementation, not a silent software fallback.
- `Canvas.copy()` is `Renderer.to_surface()`, a full readback. The launch wipe calls it once. Do not call it per frame.
- Shapes go through `canvas.rect`, `canvas.lines` and `canvas.line`, which cache a small texture. Do not add raw `pygame.draw.*` calls on `self.screen`.
- `Canvas.close()` must run before `window.destroy()`. SDL frees the renderer and its textures with the window. The format window is destroyed inside `close()`.
- The detail panel is a subsurface of only the inked rows, and its blit uses `get_offset()`. Uploading the whole panel made move frames the slow case. Keep the crop.
- First sight of a title picture uploads tens of MB and can drop a frame: 12–15 ms on the Mac, about 2.8 ms for a 1500×1100 panel on Windows. Later visits reuse the texture. It has not shown up as a problem on Windows, so leave it.
- `present()` must keep the sleep in front of it (see above).
- `packaging/readme_screenshots.py` overrides `_create_window` with a hidden `set_mode` window and needs a real `Surface` for `smoothscale`. It stays on software. Its `_force_foreground` stub takes `*a`.
- `Canvas.blit` and `blit_scaled` are the only ways a background reaches the screen on the GPU. Do not add a path that uploads a full-screen surface per theme.

## What a frame costs, so you know a regression

Mac, GPU path, from the original port:

| Moment | CPU time | What dominated |
| --- | --- | --- |
| Rest, warm textures | ~1 ms | UI bookkeeping. Present waits on vsync. |
| Scrolling, warm | well under an 8.3 ms frame | Same. Held 120 fps. |
| Move to a new preset, detail open | ~5 ms | Detail-panel upload. |
| First sight of a theme or title art | 12–15 ms once | Texture upload. |

Windows, GPU path, 2560×1440: full-screen texture upload 6.2 ms (now avoided for the background), panel upload 2.8 ms, overlay 0.03 ms, background column 0.01 ms. A move that costs more than about 10 ms in `work` is a regression.

Software costs at the Mac's ~6 MP: full-screen blit ~1.6 ms, theme crossfade ~4.3 ms, veil ~2.3 ms, flip upload ~2.3 ms. These scale with pixel count. A 4K frame misses 144 Hz in software and should not miss on the GPU.

## How to test

From the repo, with the project venv. PowerShell:

```
.\.venv\Scripts\python -m pytest -q
$env:COUCHDOOM_RENDERER='gpu'; .\.venv\Scripts\python tests\smoke.py
$env:COUCHDOOM_RENDERER='software'; .\.venv\Scripts\python tests\smoke.py
```

Run smoke in both modes. Smoke only proves the API does not crash under SDL's dummy driver. Frame timing has to come from a real window.

Linux: the same tests pass under WSL2 in a Linux venv. `tests/test_window_lifecycle.py` and `tests/test_background.py` cover the vblank wait, the column, the driver lookup and the Linux priority.

On the PC's panel:

```
$env:PYTHONPATH='src'; $env:COUCHDOOM_SHOW_FPS='1'
.\.venv\Scripts\python -m couch_doom
```

(`run.bat` sets `PYTHONPATH` too. Linux: export the same variable and use `.venv/bin/python`. `COUCHDOOM_RENDERER=software` is the old path.)

Checked on the PC at 170 Hz, 125% scaling, without anyone at the keyboard. What that could not reach is marked open.

1. Done. With no renderer env var the log reads `gpu renderer: driver: direct3d11` and `display refresh: 170 Hz`. Fps sits near 167 at rest and 135–150 while holding up or down.
2. Done for pixels. Software is about 90 fps in the same build, and the GPU and software pixels match within 2/255. A by-eye look at the fps overlay is still open.
3. Done for mouse and keyboard on this desktop. A click landed on the row under the pointer, and Down moved the selection. The process is DPI-aware, so at 125% the window and the framebuffer are the same size (dpi 1.0) in both 1440×810 and 2560×1440. A desktop where those two sizes differ, and a gamepad, are still open.
4. Done. A real Alt+F4 quits. So does the menu's Quit, and so does the close message Windows sends for the close button. Afterwards there is no CouchDoom process and no window, visible or hidden. While it is running there is a second window, hidden: the canvas's 1×1 format window, and it goes away with the process. A synthesized Alt+F4 chord does not reach the borderless window; the real key does.
5. Done. Ultimate Doom's window was found (the launcher's own handle was ignored), the game was closed, and CouchDoom came back to the foreground. A second launch did the same.
6. Done. `--windowed` is 1440×810. Borderless fullscreen was sent to the background and brought back, and it kept drawing.
7. Open, Steam Deck. Borderless on the 800p panel, Game Mode's "Exit game" quits cleanly (an X11 close request, which is `WINDOWCLOSE`), and a native-Wayland session in Desktop Mode. SDL picks XWayland while `DISPLAY` is set; force native with `SDL_VIDEODRIVER=wayland`. If the canvas fails there, `gpu renderer unavailable` plus a software window is the accepted result, not a crash. Handover already bails out on native Wayland; do not break that while chasing a handle.

After a PyInstaller build on Windows, confirm both `couch_doom.canvas` in the PYZ and the compiled `pygame/_sdl2/video` extension in the bundle. The extension lives outside the archive, so finding `couch_doom.canvas` alone does not prove the GPU path shipped.

## Leave alone

- Motion. `_approach(current, target, rate, dt)` is already frame-rate independent. Do not retune the rates.
- `handover.hold` sleeps `frame_seconds` from the caller. `_hold_loading` passes `1/hz` and a grace count from `HANDOVER_GRACE_SECONDS` (4/60 s). A faster panel paints more frames in the same cover. Do not switch back to a fixed frame count.
- The frame cap. On the canvas `_frame_cap()` is `round(refresh_hz * 1.25)`, above the display so vsync paces. Windows reports 59 or 119 for 59.94 or 119.88 Hz, and a cap equal to the rounded-down rate drifts one sleep past a vblank about once a second. The software path keeps `tick(refresh_hz)`. Never use `tick(0)`: without a blocking present it spins a core.
- Mac fullscreen, the CoreGraphics rate, and the Dock icon.
- The window-event handling in `_on_window_event`: close and Alt+F4 post `WINDOWCLOSE`, events from the format window are swallowed, and `RENDER_DEVICE_RESET` recreates the window.

## Music, so you don't chase it

Not part of this port. Title music starts after the art is on screen because of timers, not rendering. A settled preset starts its track after `DWELL_SECONDS` (0.12 s, just past a held repeat) and fades in over `FADE_IN_MS` (200), while the art fades in over 0.15 s. The presets above and below are rendered ahead into the cache. Do not change `DWELL_SECONDS`, `FADE_IN_MS`, or `MusicPlayer.warm` in this port. `tests/test_music_dwell.py` locks the timing.
