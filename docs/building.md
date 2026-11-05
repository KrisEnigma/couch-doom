# Building a personal copy

A personal build is a local PyInstaller app of the working tree, for the machine it is built on. It is not a release. Do not bump `__version__`, tag, or push. `dist/` and `build/` are gitignored.

The last Mac build (Kris-Mac, arm64, macOS 26, 4 Nov 2026) finished with exit 0. PyInstaller printed warnings. None of them failed the build. See [Warnings that are not failures](#warnings-that-are-not-failures).

## What to run

From the repo root, with the project venv (Python 3.11 or later; this Mac uses `.venv` on uv's CPython 3.11):

```
.venv/bin/python -m pip install -r requirements.txt pyinstaller pillow
.venv/bin/python packaging/install_tinysoundfont.py
.venv/bin/python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/CouchDoom.spec
```

`install_tinysoundfont.py` patches tinysoundfont before installing it. A plain `pip install tinysoundfont` keeps a bug that aborts the Intel Mac app on quit. If the installer fails, continue. The spec builds without it and title music is left out. Say so.

Pillow is not in `requirements.txt`. The Mac bundle converts `packaging/couch-doom.png` to an icns, and that step needs it.

On Windows the same commands work in PowerShell with `.venv\Scripts\python`. Do not build Windows or Linux apps from the Mac. A Mac session does not SSH, and this spec does not cross-compile. Release builds for the other targets run in `.github/workflows/release.yml` when a `v*` tag is pushed.

## Where the app lands

| Machine | Result |
| --- | --- |
| Mac | `dist/CouchDoom.app` |
| Windows | `dist/CouchDoom/CouchDoom.exe` |
| Linux | `dist/CouchDoom/CouchDoom` |

The bundle version is `src/couch_doom/__init__.py` `__version__`. A personal build keeps that string even when the tree has uncommitted work. Tell Kris both the path and the version label.

Check the Mac app without launching it:

- `file dist/CouchDoom.app/Contents/MacOS/CouchDoom` is arm64 on this Mac.
- `CFBundleShortVersionString` in `Contents/Info.plist` matches `__version__`.
- `Contents/Resources/assets/prompts/keyboard_mouse/keyboard_f5.svg` is present. `packaging/CouchDoom.spec` packs `src/couch_doom/assets` only. `third_party/kenney-input-prompts/` stays out of the app on purpose.

Do not open the built app to smoke-test it. It starts fullscreen on the real library (`~/Library/Application Support/CouchDoom` on Mac). Launch only if Kris asked.

The app is ad-hoc signed. macOS may block the first open. Right-click the app and choose Open, or System Settings → Privacy & Security → Open Anyway.

A disk image is not part of a personal build. `create-dmg` runs only in the release workflow.

## Warnings that are not failures

PyInstaller 6.22.3 printed these on the Mac build and still exited 0:

- `Ignoring ... CoreGraphics` / `CoreFoundation` / `libproc.dylib` — ctypes imports of system frameworks. The hook only accepts basenames. They load from the OS at runtime.
- `Library SDL2 required via ctypes not found` — pygame carries its own SDL. The probe looks on the system path.
- `Library libX11.so.6 required via ctypes not found` — Linux only. It is absent on a Mac, which is expected.

Do not add those libraries to the spec to silence the lines.
