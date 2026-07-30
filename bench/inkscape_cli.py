# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Serialized access to the Inkscape CLI, used only as a rasterizer.

Inkscape aborts with SIGABRT when invoked in parallel (measured: 6 of 12 runs
succeeded with six threads, and giving each process its own
INKSCAPE_PROFILE_DIR does not fix it). Serially it is completely stable, so only
the Inkscape leg goes through this lock while the rest of the bench stays
parallel.

Inkscape is a dependency of the measurement bench only, never of the vectorizer.
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()
_ATTEMPTS = 3


def _run(command: list[str], timeout: int) -> None:
    last_error: Exception | None = None
    for attempt in range(_ATTEMPTS):
        with _LOCK:
            process = subprocess.run(command, capture_output=True, timeout=timeout)
        if process.returncode == 0:
            return
        last_error = subprocess.CalledProcessError(
            process.returncode, command, process.stdout, process.stderr
        )
        time.sleep(0.3 * (attempt + 1))
    raise last_error  # type: ignore[misc]


def export_png(
    svg_path: Path, png_path: Path, px: int, background: str = "#ffffff"
) -> None:
    _run(
        [
            "inkscape",
            str(svg_path),
            "--export-type=png",
            f"--export-filename={png_path}",
            f"--export-width={px}",
            f"--export-height={px}",
            f"--export-background={background}",
            "--export-background-opacity=1",
        ],
        timeout=300,
    )
