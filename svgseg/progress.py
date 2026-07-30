# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Progress reporting for the vectorization pipeline.

``vectorize`` used to be an opaque call, which is fine for a script but not for a
GUI: the work takes between 0.6 s and 45 s depending on image size (measured:
0.6 s at 1024 px, 42 s on a 34 Mpx logo), so something has to say how far along it
is.

A caller passes a callback that receives the current stage and the overall
fraction done. Cancellation needs no extra API: the callback may raise, and the
pipeline does not catch it, so the exception propagates out of ``vectorize``. The
granularity is one region during tracing, which is fine in practice.
"""

from __future__ import annotations

from collections.abc import Callable

# (stage key, overall fraction completed in [0, 1])
ProgressCallback = Callable[[str, float], None]

# Stage keys, kept as plain identifiers so the UI layer owns the wording and its
# translation.
STAGE_LOAD = "load"
STAGE_QUANTIZE = "quantize"
STAGE_REGIONS = "regions"
STAGE_TRACE = "trace"
STAGE_WRITE = "write"

# Share of the total runtime each stage takes. Anchored on profiling a 2000 px
# logo, which measured quantization 62%, regions 4.5% and tracing 33%.
#
# These weights are APPROXIMATE and shift with image content: an image with many
# regions spends proportionally more time tracing. The estimate is therefore
# rough early on and tightens as work proceeds, which is why the UI hides the
# remaining time until enough progress has accumulated to mean anything.
STAGE_WEIGHTS: dict[str, float] = {
    STAGE_LOAD: 0.02,
    STAGE_QUANTIZE: 0.60,
    STAGE_REGIONS: 0.05,
    STAGE_TRACE: 0.32,
    STAGE_WRITE: 0.01,
}

STAGE_ORDER = [STAGE_LOAD, STAGE_QUANTIZE, STAGE_REGIONS, STAGE_TRACE, STAGE_WRITE]


class ProgressReporter:
    """Turns per-stage progress into one monotonic overall fraction.

    Each stage occupies its slice of [0, 1] according to STAGE_WEIGHTS, so a
    stage reporting its own 0..1 never makes the overall figure go backwards.
    """

    def __init__(self, callback: ProgressCallback | None = None):
        self._callback = callback
        self._offsets: dict[str, float] = {}
        running = 0.0
        for stage in STAGE_ORDER:
            self._offsets[stage] = running
            running += STAGE_WEIGHTS[stage]

    def stage(self, stage: str, fraction: float = 0.0) -> None:
        """Report ``fraction`` of ``stage`` complete."""
        if self._callback is None:
            return
        clamped = 0.0 if fraction < 0.0 else (1.0 if fraction > 1.0 else fraction)
        overall = self._offsets[stage] + STAGE_WEIGHTS[stage] * clamped
        self._callback(stage, min(overall, 1.0))

    def done(self) -> None:
        if self._callback is not None:
            self._callback(STAGE_WRITE, 1.0)
