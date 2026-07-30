# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Entry point of the portable Windows executable.

PyInstaller freezes a script, not an entry point, so this file exists to be that
script. It does two things: start the GUI, and answer ``--selftest``.

The self test is the only way CI can tell a working build from a broken one. The
executable is built without a console, so nothing it prints is visible and the
exit code is the whole signal; and the failures that matter here -- numpy, scipy,
scikit-image, OpenCV or lxml not surviving the freeze, or potrace.exe not landing
where the resolver looks -- all happen at import or first use, not at build time.
So the self test vectorizes a bundled example and checks the result.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


def _say(message: str) -> None:
    """Print, unless there is nowhere to print to.

    A windowed PyInstaller build has no console and sets ``sys.stdout`` to None,
    where a bare ``print`` raises AttributeError.
    """
    stream = sys.stdout or sys.stderr
    if stream is not None:
        print(message, file=stream)


def _bundled_example() -> Path:
    """The example image packed into the executable."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / "examples" / "flat_logo.png"


def selftest() -> int:
    """Vectorize a bundled example. Returns 0 only if the SVG is real."""
    from svgseg import __version__, potrace, vectorize

    _say(f"svgseg {__version__}")
    _say(f"frozen: {getattr(sys, 'frozen', False)}")

    try:
        binary = potrace.executable()
    except FileNotFoundError as error:
        _say(f"FAIL potrace not found: {error}")
        return 1
    _say(f"potrace: {binary}")

    source = _bundled_example()
    if not source.is_file():
        _say(f"FAIL example image missing: {source}")
        return 1

    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "selftest.svg"
        try:
            info = vectorize(source, output)
        except Exception as error:  # noqa: BLE001 - any failure fails the build
            _say(f"FAIL vectorize raised {type(error).__name__}: {error}")
            return 1
        svg = output.read_text(encoding="utf-8")

    if info["paths"] < 1 or "path" not in svg:
        _say(f"FAIL no paths produced: {info}")
        return 1

    _say(f"OK {info['regions']} regions, {info['paths']} paths, {len(svg)} bytes")
    return 0


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()

    from svgseg.gui.app import main as gui_main

    # Qt would try to open a file named --selftest, so only the real arguments
    # reach it. There are none to pass on: the window opens empty.
    return gui_main([sys.argv[0]])


if __name__ == "__main__":
    raise SystemExit(main())
