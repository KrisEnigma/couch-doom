# PyInstaller build: pyinstaller packaging/CouchDoom.spec
#   Windows/Linux -> dist/CouchDoom/ (CouchDoom.exe or CouchDoom)   macOS -> dist/CouchDoom.app
# One folder rather than one file: starts instantly (no unpack to %TEMP%) and trips fewer antivirus heuristics.
import importlib.util
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
sys.path.insert(0, str(root / "src"))
from couch_doom import __version__  # noqa: E402

# MIDI title music is optional: a platform without a tinysoundfont wheel still builds, just without it.
tsf_datas, tsf_binaries, tsf_hidden = collect_all("tinysoundfont") if importlib.util.find_spec("tinysoundfont") else ([], [], [])
mac = sys.platform == "darwin"

a = Analysis(
    [str(root / "packaging" / "couch_doom_entry.py")],
    pathex=[str(root / "src")],
    binaries=tsf_binaries,
    datas=[(str(root / "src" / "couch_doom" / "assets"), "assets"), *tsf_datas],
    hiddenimports=tsf_hidden,
    excludes=["tkinter", "unittest", "pydoc", "pyaudio"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CouchDoom",
    console=False,
    icon=str(root / "packaging" / "couch-doom.ico") if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="CouchDoom")
if mac:
    app = BUNDLE(
        coll,
        name="CouchDoom.app",
        icon=str(root / "packaging" / "couch-doom.png"),  # PyInstaller converts it to .icns (needs Pillow)
        bundle_identifier="com.krisenigma.couchdoom",
        version=__version__,
        info_plist={"NSHighResolutionCapable": True, "LSApplicationCategoryType": "public.app-category.games"},
    )
