# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""PyInstaller spec for the portable Windows executable.

Build it with::

    set SVGSEG_POTRACE_EXE=C:\\path\\to\\potrace.exe
    pyinstaller --noconfirm --clean packaging/windows/svgseg.spec

The result is one ``dist/svgseg.exe`` that needs nothing installed: no Python, no
PySide6 and no separate potrace. Bundling potrace is the reason the project is
GPL-3; see the licence section of the README.

This is a spec file rather than a pile of command-line flags because several of
the decisions below need an explanation, and a flag cannot carry one.

``SPECPATH``, ``Analysis``, ``PYZ`` and ``EXE`` are injected by PyInstaller when
it executes this file, which is why they appear undefined. Written against the
PyInstaller 6 API.
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

HERE = Path(SPECPATH).resolve()  # noqa: F821
ROOT = HERE.parents[1]

# --- potrace ----------------------------------------------------------------
# Not vendored in the repository: the workflow downloads it, verifies its
# checksum and points here. A missing binary has to stop the build, because the
# executable would look complete and then fail on the first conversion.
potrace_exe = Path(
    os.environ.get("SVGSEG_POTRACE_EXE", str(HERE / "potrace" / "potrace.exe"))
).resolve()
if not potrace_exe.is_file():
    raise SystemExit(
        f"potrace not found at {potrace_exe}. Set SVGSEG_POTRACE_EXE to its "
        "path; see .github/workflows/windows-release.yml"
    )

# The root of the bundle is where svgseg/potrace.py looks first when frozen,
# at sys._MEIPASS / potrace.exe.
binaries = [(str(potrace_exe), ".")]

# The compiled catalogues, kept at the path i18n.py derives from __file__. A new
# language needs no change here.
datas = [
    (str(qm), "svgseg/gui/translations")
    for qm in sorted((ROOT / "svgseg/gui/translations").glob("*.qm"))
]

# The image --selftest converts, so the build can prove itself.
datas.append((str(ROOT / "examples/flat_logo.png"), "examples"))

# scikit-image resolves its submodules through lazy_loader, which reads .pyi stub
# files at run time. Those are data, not code, so nothing in the import graph
# points at them: without this line the freeze succeeds and then raises on
# ``from skimage.color import rgb2lab`` during the first conversion.
datas += collect_data_files("skimage")

analysis = Analysis(  # noqa: F821
    [str(HERE / "svgseg_gui.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    excludes=[
        # Reachable from scipy and friends, never used here, and together the
        # largest easy saving in the download.
        "tkinter",
        "matplotlib",
        "pytest",
        "IPython",
    ],
    noarchive=False,
)

pyz = PYZ(analysis.pure)  # noqa: F821

# Passing binaries and datas to EXE with no COLLECT step is what makes this a
# one-file build.
exe = EXE(  # noqa: F821
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="svgseg",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX is deliberately off. It shrinks the file but rewrites the executable in
    # a way antivirus heuristics flag, and an unsigned binary already has enough
    # trouble getting past SmartScreen.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # A GUI app: a console window flashing up would be a bug. It also means the
    # process has no stdout, which is why --selftest reports through its exit
    # code.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
