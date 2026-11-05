# Building a personal copy

A personal build is a local PyInstaller app of the working tree, for the machine it is built on. It is not a release. Do not bump `__version__`, tag, or push. `dist/` and `build/` are gitignored.

PyInstaller prints warnings on every platform. None of them fail the build. See [Warnings that are not failures](#warnings-that-are-not-failures).

## What to run

From the repo root, with a project venv on Python 3.11 or later. Create it once, if `.venv` does not exist:

macOS and Linux:

```
python3 -m venv .venv
```

Windows (PowerShell):

```
python -m venv .venv
```

Then install and build.

macOS and Linux:

```
.venv/bin/python -m pip install -r requirements.txt pyinstaller pillow
.venv/bin/python packaging/install_tinysoundfont.py
.venv/bin/python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/CouchDoom.spec
```

Windows (PowerShell):

```
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller pillow
.venv\Scripts\python packaging\install_tinysoundfont.py
.venv\Scripts\python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/CouchDoom.spec
```

`install_tinysoundfont.py` patches tinysoundfont before installing it. A plain `pip install tinysoundfont` keeps a bug that aborts the Intel Mac app on quit. If the installer fails, continue. The spec builds without it and title music is left out. Say so.

Pillow is not in `requirements.txt`. The Mac bundle converts `packaging/couch-doom.png` to an icns, and that step needs it.

Do not build a Windows or Linux app on a Mac, or a Mac app on Windows. The spec does not cross-compile. Release builds for every target run in `.github/workflows/release.yml` when a `v*` tag is pushed.

## Speeding up repeat builds

Compiling tinysoundfont from source takes several minutes, and the installer does it on every run unless it finds a cached wheel. Set `COUCHDOOM_WHEEL_DIR` to a folder inside the repo before running the installer:

```
COUCHDOOM_WHEEL_DIR=$PWD/.ci/wheels .venv/bin/python packaging/install_tinysoundfont.py
```

PowerShell:

```
$env:COUCHDOOM_WHEEL_DIR = Join-Path (Get-Location) ".ci\wheels"
.venv\Scripts\python packaging\install_tinysoundfont.py
```

`.ci/` is gitignored. The first run stores `tinysoundfont-0.3.7-*.whl` there. Later runs print `tinysoundfont: using cached` and skip the compile.

The cache is only as current as its first build. The script reuses any cached wheel for version 0.3.7 and does not notice edits to `packaging/install_tinysoundfont.py`. After changing that script, delete the wheel in `.ci/wheels` so the next run rebuilds it. The release workflow rebuilds on that change because its cache key includes the script.

A cached wheel is for the Python that built it. Another Python version fails that install, and the script then compiles and replaces the wheel.

## Where the app lands

| Machine | Result |
| --- | --- |
| Mac | `dist/CouchDoom.app` |
| Windows | `dist/CouchDoom/CouchDoom.exe` |
| Linux | `dist/CouchDoom/CouchDoom` |

The bundle version is `src/couch_doom/__init__.py` `__version__`. A personal build keeps that string even when the tree has uncommitted work. Report both the path and the version label.

Check the Mac app without launching it:

- `file dist/CouchDoom.app/Contents/MacOS/CouchDoom` shows the architecture you built for.
- `CFBundleShortVersionString` in `Contents/Info.plist` matches `__version__`.
- `Contents/Resources/assets/prompts/keyboard_mouse/keyboard_f5.svg` is present. `packaging/CouchDoom.spec` packs `src/couch_doom/assets` only. `third_party/kenney-input-prompts/` stays out of the app on purpose.

Do not open the built app to smoke-test it. It starts fullscreen on the real library (`~/Library/Application Support/CouchDoom` on Mac). Launch only if the owner asks.

The app is ad-hoc signed. macOS may block the first open. Right-click the app and choose Open, or System Settings → Privacy & Security → Open Anyway.

A disk image is not part of a personal build. `create-dmg` runs only in the release workflow.

## Warnings that are not failures

PyInstaller 6.22.3 printed these on a macOS build and still exited 0:

- `Ignoring ... CoreGraphics` / `CoreFoundation` / `libproc.dylib` — ctypes imports of system frameworks. The hook only accepts basenames. They load from the OS at runtime.
- `Library SDL2 required via ctypes not found` — pygame carries its own SDL. The probe looks on the system path.
- `Library libX11.so.6 required via ctypes not found` — Linux only. It is absent on a Mac, which is expected.

Do not add those libraries to the spec to silence the lines.
