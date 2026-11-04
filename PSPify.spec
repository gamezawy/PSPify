# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for PSPify.
#   Normal build (PyQt6):   pyinstaller PSPify.spec
#   Legacy build (PyQt5):   pyinstaller "PSPify (Legacy).spec"
# See BUILDING.txt for the full steps.
#
# ffmpeg and atracdenc are deliberately NOT bundled: users install them themselves
# (README.txt section 1), so no third-party tool is redistributed.

import os

QT = os.environ.get("PSPIFY_QT", "6")          # "5" selects the PyQt5 legacy build
LEGACY = QT == "5"

# The notices must say where the PSPify source code can be obtained (GPL requirement).
with open(os.path.join(SPECPATH, "THIRD_PARTY_NOTICES.txt"), encoding="utf-8") as handle:
    if "<<FILL IN" in handle.read():
        raise SystemExit("THIRD_PARTY_NOTICES.txt still has a '<<FILL IN' field: add the URL of your PSPify source code.")

# Only what the app reads at run time (the unused artwork in Resources/Icon stays out).
DATAS = [
    ("Resources/Config.zip", "Resources"),
    ("Resources/PBOOT.PBP", "Resources"),
    ("Resources/Icon/app_icon.png", "Resources/Icon"),
    ("Resources/Icon/app_logo.png", "Resources/Icon"),
    ("Resources/SVG", "Resources/SVG"),
]
for doc in ("README.txt", "LICENSE", "THIRD_PARTY_NOTICES.txt"):    # copied next to the EXE on first run
    DATAS.append((doc, "Resources/Docs"))

a = Analysis(
    ["pspify_gui.py"],
    pathex=[],
    binaries=[],
    datas=DATAS,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt6" if LEGACY else "PyQt5", "tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PSPify (Legacy)" if LEGACY else "PSPify",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # UPX slows startup and often triggers antivirus false positives
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join("Resources", "Icon", "app_icon.png")],
)
