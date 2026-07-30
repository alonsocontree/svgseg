# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Raster to SVG vectorizer where every piece is an editable ``<path>``.

Unlike a colour-layer tracer, the output is a clean partition: each piece is a
closed, disjoint path carrying its exact colour, so it can be selected and moved
on its own.
"""

from .pipeline import vectorize

__version__ = "0.1.0"
__all__ = ["vectorize", "__version__"]
