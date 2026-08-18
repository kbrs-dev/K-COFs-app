# -*- mode: python ; coding: utf-8 -*-
#
# Windows build. Must run ON Windows (or a windows-latest GitHub Actions
# runner) -- PyInstaller does not cross-compile from macOS. See
# .github/workflows/build-windows.yml, which builds this automatically on
# every push to main.
#
# Same tkinterdnd2 Tcl9 gap as the Mac build (see kbrs_markup.spec for the
# full explanation): Windows ships both a Tcl 8.6 and a Tcl 9 tkdnd build
# (win-x64 vs win-x64-tcl9), and PyInstaller's bundled tkinterdnd2 hook only
# collects the 8.6 one automatically. We add whichever -tcl9 folder(s) exist
# so the frozen app can find a build matching the host's Tcl version,
# whichever that turns out to be on the Actions runner's Python build.

import os
import tkinterdnd2

tkdnd_root = os.path.join(os.path.dirname(tkinterdnd2.__file__), "tkdnd")
tcl9_datas = [
    (os.path.join(tkdnd_root, name), os.path.join("tkinterdnd2", "tkdnd", name))
    for name in os.listdir(tkdnd_root)
    if name.endswith("-tcl9") and os.path.isdir(os.path.join(tkdnd_root, name))
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=tcl9_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KBRS Markup",
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
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="KBRS Markup",
)
