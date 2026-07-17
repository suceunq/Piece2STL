# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import shutil

from PyInstaller.utils.hooks import collect_all


root = Path(SPECPATH)
datas = [
    (str(root / "vendor"), "vendor"),
    (str(root / "ai"), "ai"),
    (str(root / "assets"), "assets"),
]
binaries = []
hiddenimports = []

ffmpeg = shutil.which("ffmpeg")
if ffmpeg:
    binaries.append((ffmpeg, "vendor/ffmpeg/bin"))

for package in ("pymeshlab", "pyvista", "pyvistaqt", "trimesh"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    [str(root / "scripts" / "piece2stl_app.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Piece2STL",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=str(root / "assets" / "piece2stl.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Piece2STL",
)
