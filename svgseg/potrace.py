# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Locating the potrace executable.

Installed from a package manager, potrace is on the PATH and there is nothing to
decide. The Windows release is the reason this module exists: it is a single
self-contained ``.exe`` that carries ``potrace.exe`` inside it, so there is no
PATH entry to find and the location is only known at runtime.

Resolution order, first match wins:

1. ``SVGSEG_POTRACE``, an explicit path. The escape hatch for a build the
   packaging below does not anticipate.
2. Next to this program, when frozen. PyInstaller unpacks a one-file build into a
   temporary directory it points at with ``sys._MEIPASS``; a one-folder build has
   no such attribute and the binary sits beside the executable instead.
3. The PATH.

The answer is cached because tracing calls potrace once per region, which is
thousands of times on a real logo, and each miss would otherwise walk the PATH.
"""

from __future__ import annotations

import os
import shutil
import sys
from functools import cache
from pathlib import Path

ENV_VAR = "SVGSEG_POTRACE"

#: What the binary is called, which differs only by extension.
BINARY_NAME = "potrace.exe" if sys.platform == "win32" else "potrace"


def _bundled_candidates() -> list[Path]:
    """Directories a frozen build may have unpacked potrace into."""
    if not getattr(sys, "frozen", False):
        return []
    roots = []
    unpacked = getattr(sys, "_MEIPASS", None)  # One-file build.
    if unpacked:
        roots.append(Path(unpacked))
    roots.append(Path(sys.executable).parent)  # One-folder build.
    return [root / BINARY_NAME for root in roots]


@cache
def executable() -> str:
    """Return the path to invoke potrace with.

    Raises FileNotFoundError, naming ``potrace``, when it is nowhere to be found.
    Callers surface that as an install hint, so the name has to stay in the
    message.
    """
    override = os.environ.get(ENV_VAR)
    if override:
        if not Path(override).is_file():
            raise FileNotFoundError(
                2, f"{ENV_VAR} points at a file that does not exist", override
            )
        return override

    for candidate in _bundled_candidates():
        if candidate.is_file():
            return str(candidate)

    found = shutil.which("potrace")
    if found:
        return found

    raise FileNotFoundError(
        2,
        "potrace was not found on the PATH. Install it (apt install potrace, "
        "brew install potrace) or point at it with " + ENV_VAR,
        "potrace",
    )
