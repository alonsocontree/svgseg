# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""End-to-end orchestration: raster image in, editable SVG out."""

from __future__ import annotations

from pathlib import Path

from . import assemble, preprocess, quantize, regions, tracing
from .progress import (
    STAGE_LOAD,
    STAGE_QUANTIZE,
    STAGE_REGIONS,
    STAGE_TRACE,
    STAGE_WRITE,
    ProgressCallback,
    ProgressReporter,
)


def vectorize(
    input_path: Path,
    output_path: Path,
    max_colors: int = 32,
    min_delta_e: float | None = None,
    flat_tol: float = 4.0,
    min_area: int | None = None,
    min_length: int | None = None,
    connectivity: int = 8,
    alphamax: float = 1.0,
    opttolerance: float = 0.2,
    regularize: bool = True,
    line_tol: float = 0.35,
    axis_tol: float = 0.6,
    circle_tol: float = 0.8,
    progress: ProgressCallback | None = None,
) -> dict:
    """Vectorize one image and write the SVG. Returns a dict of diagnostics.

    ``min_delta_e``, ``min_area`` and ``min_length`` default to values derived
    from the image noise; see :func:`svgseg.quantize.auto_parameters`.

    Feed the image at its **native** resolution. The same logo reduced to 1024 px
    loses twice as much fine detail as at 2815 px, because the thresholds scale
    with the pixel count.

    ``progress`` receives (stage, overall fraction) as the work proceeds. Raising
    from inside it cancels the run: the exception is not caught here, so it
    propagates and no output file is written.
    """
    reporter = ProgressReporter(progress)

    reporter.stage(STAGE_LOAD)
    rgb, alpha = preprocess.load(input_path)
    height, width = rgb.shape[:2]
    inside = alpha >= 0.5

    reporter.stage(STAGE_QUANTIZE)
    quantized = quantize.quantize(
        rgb,
        max_colors=max_colors,
        min_delta_e=min_delta_e,
        flat_tol=flat_tol,
        inside=inside,
    )
    # Thresholds scale with the OPAQUE area rather than the canvas: in a PNG with
    # transparency half the canvas may have nothing to vectorize.
    _, auto_area, auto_length = quantize.auto_parameters(
        quantized.texture, int(inside.sum())
    )
    if min_area is None:
        min_area = auto_area
    if min_length is None:
        min_length = auto_length

    reporter.stage(STAGE_REGIONS)
    raw = regions.segment_raw(quantized.labels, alpha, connectivity)
    merged = regions.merge_specks(raw, min_area=min_area, min_length=min_length)

    reporter.stage(STAGE_TRACE)
    shapes = tracing.trace_regions(
        merged,
        quantized.palette,
        alphamax=alphamax,
        opttolerance=opttolerance,
        regularize=regularize,
        line_tol=line_tol,
        axis_tol=axis_tol,
        circle_tol=circle_tol,
        progress=lambda fraction: reporter.stage(STAGE_TRACE, fraction),
    )

    reporter.stage(STAGE_WRITE)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(assemble.build_svg(shapes, width, height))
    reporter.done()

    return {
        "colors": len(quantized.palette),
        "regions": len(merged.areas),
        "paths": len(shapes),
        "mixed_pixels_pct": float((~quantized.pure).mean() * 100),
        "texture": quantized.texture,
        "opaque_pct": float(inside.mean() * 100),
        "min_area": min_area,
        "min_length": min_length,
    }
