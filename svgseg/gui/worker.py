# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Background worker: runs the vectorizer off the UI thread.

Vectorizing takes between 0.6 s and 45 s depending on image size, so calling it
from the UI thread would freeze the window. The window never calls
:func:`svgseg.vectorize` directly; it goes through this worker.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from svgseg import vectorize


class Cancelled(Exception):  # noqa: N818 - a cancellation is not an error
    """Raised inside the progress callback to abort a run.

    The pipeline does not catch it, so it unwinds without writing the output.
    """


class RemainingTime:
    """Estimates how much longer the run will take.

    ``elapsed * (1 - fraction) / fraction`` is the whole formula. It is noise
    while the fraction is tiny, so nothing is reported below ``min_fraction``, and
    the value is smoothed because the stage weights are only approximate and the
    raw estimate jumps whenever one stage hands over to the next.
    """

    def __init__(self, min_fraction: float = 0.05, smoothing: float = 0.3):
        self._min_fraction = min_fraction
        self._smoothing = smoothing
        self._started = time.monotonic()
        self._estimate: float | None = None

    def update(self, fraction: float) -> float | None:
        """Return the smoothed seconds remaining, or None when not yet reliable."""
        if fraction < self._min_fraction or fraction >= 1.0:
            return None
        elapsed = time.monotonic() - self._started
        raw = elapsed * (1.0 - fraction) / fraction
        if self._estimate is None:
            self._estimate = raw
        else:
            self._estimate += self._smoothing * (raw - self._estimate)
        return self._estimate


class VectorizeWorker(QObject):
    """Runs one vectorization and reports progress.

    Lives in its own QThread. ``cancel`` is safe to call from the UI thread: it
    only sets a flag that the progress callback checks.
    """

    progressed = Signal(str, float, float)  # stage, fraction, seconds remaining
    finished = Signal(dict)  # diagnostics from vectorize()
    failed = Signal(str)  # human-readable error message
    cancelled = Signal()

    def __init__(self, input_path: Path, output_path: Path, options: dict):
        super().__init__()
        self._input = input_path
        self._output = output_path
        self._options = options
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        remaining = RemainingTime()

        def on_progress(stage: str, fraction: float) -> None:
            if self._cancel_requested:
                raise Cancelled
            seconds_left = remaining.update(fraction)
            self.progressed.emit(
                stage, fraction, -1.0 if seconds_left is None else seconds_left
            )

        try:
            info = vectorize(
                self._input, self._output, progress=on_progress, **self._options
            )
        except Cancelled:
            # The pipeline unwound before writing, but a previous run may have
            # left a file at this path; leaving it would be misleading.
            self._output.unlink(missing_ok=True)
            self.cancelled.emit()
        except FileNotFoundError as error:
            # The most common real failure: potrace is not installed.
            missing = getattr(error, "filename", "") or ""
            if "potrace" in str(missing):
                self.failed.emit("potrace-missing")
            else:
                self.failed.emit(str(error))
        except Exception as error:  # noqa: BLE001 - surfaced to the user verbatim
            self.failed.emit(f"{type(error).__name__}: {error}")
        else:
            self.finished.emit(info)


def start_worker(worker: VectorizeWorker) -> QThread:
    """Move ``worker`` onto a fresh thread, start it and return the thread.

    The caller MUST hold on to the returned thread until its own ``finished``
    signal fires. A worker signal such as ``finished`` is emitted while the thread
    is still winding down, so dropping the reference at that point destroys a
    running QThread and aborts the process with "Destroyed while thread is still
    running". Release the reference from ``thread.finished`` instead.
    """
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    for signal in (worker.finished, worker.failed, worker.cancelled):
        signal.connect(thread.quit)
    thread.start()
    return thread
