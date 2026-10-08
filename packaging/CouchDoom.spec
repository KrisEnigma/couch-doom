# PyInstaller build: pyinstaller packaging/CouchDoom.spec  ->  dist/CouchDoom/CouchDoom.exe
# One folder rather than one file: starts instantly (no unpack to %TEMP%) and trips fewer antivirus heuristics.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
tsf_datas, tsf_binaries, tsf_hidden = collect_all("tinysoundfont")

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
    icon=str(root / "packaging" / "couch-doom.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="CouchDoom")
