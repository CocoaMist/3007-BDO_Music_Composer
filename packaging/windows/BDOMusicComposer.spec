# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_root = Path(SPECPATH).parents[1]

datas = [
    (str(project_root / "assets" / "ui" / "timeline_background.png"), "assets/ui"),
    (str(project_root / "assets" / "icons" / "app_icon.png"), "assets/icons"),
    (str(project_root / "data" / "mappings" / "bdo_wwise_midi_map.json"), "data/mappings"),
    (str(project_root / "data" / "profiles" / "bdo_global_v9.json"), "data/profiles"),
]

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=["PySide6.QtMultimedia"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BDO-Music-Composer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "assets" / "icons" / "app_icon.ico"),
)
