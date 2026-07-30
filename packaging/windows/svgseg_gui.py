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

The self test is the only way CI can tell a working build from a broken one: the
failures that matter here -- numpy, scipy, scikit-image, OpenCV or lxml not
surviving the freeze, or potrace.exe not landing where the resolver looks -- all
happen at import or first use, never at build time. So it vectorizes a bundled
example and checks that real paths come out.

It reports through a **file**, not through stdout. The executable is built
without a console, so a windowed process has no stdout at all: the first version
of this printed into the void and the only thing CI could say was "it failed".
Every line therefore also goes to ``svgseg-selftest.log`` in the working
directory, and nothing is allowed to escape uncaught, because an unhandled
exception in a windowed build is a modal dialog that would hang a runner until
its six-hour timeout.
"""

from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

LOG_NAME = "svgseg-selftest.log"

_transcript: list[str] = []


def _say(message: str) -> None:
    """Record a line, and print it too if there is anywhere to print to.

    A windowed PyInstaller build sets ``sys.stdout`` to None, where a bare
    ``print`` raises AttributeError.
    """
    _transcript.append(message)
    stream = sys.stdout or sys.stderr
    if stream is not None:
        print(message, file=stream)


def _write_transcript() -> None:
    """Leave the report on disk. Failing to write it must not fail the run."""
    try:
        Path.cwd().joinpath(LOG_NAME).write_text(
            "\n".join(_transcript) + "\n", encoding="utf-8"
        )
    except OSError as error:
        _say(f"could not write {LOG_NAME}: {error}")


def _bundled_example() -> Path:
    """The example image packed into the executable."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / "examples" / "flat_logo.png"


def _selftest() -> int:
    """Vectorize a bundled example. Returns 0 only if the SVG is real."""
    _say(f"python {sys.version.split()[0]} on {sys.platform}")
    _say(f"frozen: {getattr(sys, 'frozen', False)}")
    _say(f"bundle: {getattr(sys, '_MEIPASS', 'not frozen')}")

    # Imported here, and reported one by one, because a library that did not
    # survive the freeze fails at import and the name of the failing one is the
    # whole diagnosis.
    from svgseg import __version__, potrace, vectorize

    _say(f"svgseg {__version__}")

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
    _say(f"example: {source}")

    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "selftest.svg"
        info = vectorize(source, output)
        svg = output.read_text(encoding="utf-8")

    if info["paths"] < 1 or "path" not in svg:
        _say(f"FAIL no paths produced: {info}")
        return 1

    _say(f"OK {info['regions']} regions, {info['paths']} paths, {len(svg)} bytes")
    return 0


def selftest() -> int:
    """Run the self test, and let nothing escape.

    An unhandled exception in a windowed build opens a modal dialog nobody is
    there to dismiss, so the traceback is caught, written down and turned into an
    exit code.
    """
    try:
        code = _selftest()
    except BaseException:  # noqa: BLE001 - the traceback is the deliverable
        _say("FAIL uncaught:")
        _say(traceback.format_exc())
        code = 1
    _write_transcript()
    return code


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()

    from svgseg.gui.app import main as gui_main

    # Qt would try to open a file named --selftest, so only the real arguments
    # reach it. There are none to pass on: the window opens empty.
    return gui_main([sys.argv[0]])


if __name__ == "__main__":
    raise SystemExit(main())
