# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Loading and normalization of the input image."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def load(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return (rgb, alpha), both float64 in [0, 1].

    The RGB is handed over **as stored**, without compositing over white. PNG
    keeps alpha non-premultiplied, so each pixel's true colour is already in the
    file; compositing corrupts it exactly along the outline fringe, where alpha
    falls from 1 to 0, and leaves a whitish 1-2 px halo inside the silhouette that
    later turns into regions of its own.

    Areas with alpha below 0.5 produce no path, and their RGB may be garbage (many
    encoders store black where alpha is 0), so the later stages receive the mask
    and never look there.
    """
    array = np.asarray(Image.open(path).convert("RGBA")).astype(np.float64) / 255.0
    return np.ascontiguousarray(array[..., :3]), np.ascontiguousarray(array[..., 3])
