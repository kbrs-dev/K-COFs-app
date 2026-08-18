# -*- mode: python ; coding: utf-8 -*-
#
# Build with: pyinstaller kbrs_markup.spec
#
# Note: PyInstaller's bundled tkinterdnd2 hook only collects the legacy
# Tcl 8.6 native tkdnd binaries (e.g. tkdnd/osx-arm64), not the newer
# Tcl 9-specific ones (tkdnd/osx-arm64-tcl9) that tkinterdnd2 ships and
# that recent Python builds (Tcl/Tk 9) actually need at runtime. Without
# this, TkinterDnD.Tk() raises "compiled for Tcl 8.6" / "Unable to load
# tkdnd library" in the packaged app even though it works fine unpackaged.
# We add whichever -tcl9 platform folders exist so the frozen app can find
# a build matching the host's Tcl version.

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
app = BUNDLE(
    coll,
    name="KBRS Markup.app",
    icon=None,
    bundle_identifier="com.kbrs.markup",
)
