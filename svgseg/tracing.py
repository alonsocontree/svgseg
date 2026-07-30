# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Vectorize each region with potrace, without white hairlines between pieces.

The problem: tracing every region separately makes potrace smooth each outline
independently, leaving a sub-pixel gap between two neighbouring pieces. That gap
is the defect that gives an amateur vectorizer away.

The rule that fixes it without side effects: regions are painted from largest to
smallest area, and **each region grows by 1 px only towards regions painted
after it** (the smaller ones). The large region then sits underneath covering the
seam, and the small one is drawn on top with its exact outline.

Dilating in every direction, which is the obvious thing to do, would be a
mistake: it turns a 1 px stroke into a 3 px one. With this rule thin strokes are
never fattened, because they only grow towards neighbours smaller than themselves.

Each region is processed cropped to its bounding box. Working on the full image
per region is O(regions x pixels), and on a real 2048 px logo with thousands of
regions it becomes unusable: 567 s were measured, most of it dilations of
6144x6174 repeated thousands of times.

The module is named ``tracing`` rather than ``trace`` to avoid shadowing the
standard library module of that name.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np
from scipy import ndimage

from . import geometry, potrace
from .regions import Regions

_KERNEL = np.ones((3, 3), np.uint8)
_RE_TRANSFORM = re.compile(r'transform="([^"]+)"')
_RE_PATH = re.compile(r'<path[^>]*\sd="([^"]*)"')
_RE_AFFINE = re.compile(
    r"translate\(([-\d.eE]+)[,\s]+([-\d.eE]+)\)\s*scale\(([-\d.eE]+)[,\s]+([-\d.eE]+)\)"
)


def _affine(
    transform: str, x0: int, y0: int
) -> tuple[float, float, float, float] | None:
    """Compose the potrace -> crop -> image chain into a single diagonal affine.

    potrace emits ``translate(0,H) scale(0.1,-0.1)``: coordinates scaled by ten
    with the Y axis flipped. The crop offset goes on top of that. Everything
    collapses to (sx, sy, tx, ty) because there is no rotation.
    """
    match = _RE_AFFINE.search(transform or "")
    if not match:
        return None
    tx, ty, sx, sy = (float(v) for v in match.groups())
    return sx, sy, tx + x0, ty + y0


@dataclass
class Shape:
    region: int
    d: str
    fill: str
    area: int
    # Maps crop coordinates into image space; empty once regularized.
    transform: str


# On Windows every subprocess started from a windowed program flashes up a
# console. One region is one potrace call, and a real logo has thousands, so
# without this the GUI would strobe the screen with black rectangles for the
# whole conversion. The flag does not exist on other platforms, where 0 means
# "no special creation flags".
_NO_CONSOLE = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _pbm(mask: np.ndarray) -> bytes:
    """Binary PBM (P4). In PBM a set bit is black, which is what potrace traces."""
    height, width = mask.shape
    header = b"P4\n%d %d\n" % (width, height)
    return header + np.packbits(mask.astype(np.uint8), axis=1).tobytes()


def _run_potrace(
    mask: np.ndarray, alphamax: float, opttolerance: float
) -> tuple[str, str]:
    """Trace one binary mask. Returns (path data, potrace transform).

    potrace is invoked as a subprocess with PBM on stdin and SVG on stdout, which
    avoids depending on ``pypotrace``, a notoriously painful build.
    """
    process = subprocess.run(
        [
            potrace.executable(),
            "-s",
            "-o",
            "-",
            "-t",
            "0",  # Speck filtering already happened in regions.py.
            "-a",
            str(alphamax),
            "-O",
            str(opttolerance),
            "-",
        ],
        input=_pbm(mask),
        capture_output=True,
        check=True,
        creationflags=_NO_CONSOLE,
    )
    output = process.stdout.decode("utf-8", "replace")
    transform = _RE_TRANSFORM.search(output)
    paths = _RE_PATH.findall(output)
    return (
        " ".join(path.strip() for path in paths),
        transform.group(1) if transform else "",
    )


def trace_regions(
    regions: Regions,
    palette: np.ndarray,
    alphamax: float = 1.0,
    opttolerance: float = 0.2,
    regularize: bool = True,
    line_tol: float = 0.35,
    axis_tol: float = 0.6,
    circle_tol: float = 0.8,
    progress: Callable[[float], None] | None = None,
) -> list[Shape]:
    """Trace every region and return the shapes in paint order.

    ``progress`` receives the fraction of regions processed. This is the stage
    with real granularity, because it walks one region at a time; raising from
    inside the callback cancels the run.
    """
    region_map = regions.region_map
    count = len(regions.areas)
    height, width = region_map.shape

    # Paint rank: 0 is painted first, i.e. the largest region.
    rank = np.empty(count, np.int32)
    rank[regions.order] = np.arange(count, dtype=np.int32)
    rank_map = np.full(region_map.shape, -1, np.int32)
    inside = region_map >= 0
    rank_map[inside] = rank[region_map[inside]]

    # Every bounding box in a single pass.
    boxes = ndimage.find_objects(region_map + 1)

    shapes: list[Shape] = []
    total = max(len(regions.order), 1)
    for done, region in enumerate(regions.order):
        if progress is not None:
            progress(done / total)
        box = boxes[region] if region < len(boxes) else None
        if box is None:
            continue
        # One pixel of margin so the dilation fits.
        y0 = max(box[0].start - 1, 0)
        y1 = min(box[0].stop + 1, height)
        x0 = max(box[1].start - 1, 0)
        x1 = min(box[1].stop + 1, width)

        crop_regions = region_map[y0:y1, x0:x1]
        crop_rank = rank_map[y0:y1, x0:x1]

        mask = crop_regions == region
        grown = cv2.dilate(mask.astype(np.uint8), _KERNEL).astype(bool)
        # Only towards regions painted later; never outside the canvas.
        mask = mask | (grown & (crop_rank > rank[region]))

        data, potrace_transform = _run_potrace(mask, alphamax, opttolerance)
        if not data:
            continue

        affine = _affine(potrace_transform, x0, y0)
        if regularize and affine is not None:
            # The path comes out in pixel coordinates, with no transform of its own.
            data = geometry.regularize_path(
                data,
                *affine,
                line_tol=line_tol,
                axis_tol=axis_tol,
                circle_tol=circle_tol,
            )
            transform = ""
        else:
            parts = []
            if x0 or y0:
                parts.append(f"translate({x0},{y0})")
            parts.append(potrace_transform)
            transform = " ".join(parts)
        if not data:
            continue

        color = palette[regions.color_index[region]]
        shapes.append(
            Shape(
                region=int(region),
                d=data,
                fill=f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}",
                area=int(regions.areas[region]),
                transform=transform,
            )
        )
    if progress is not None:
        progress(1.0)
    return shapes
